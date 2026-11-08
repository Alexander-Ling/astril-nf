#!/usr/bin/env python3
"""De-identify AND face-mask one patient's DICOM files, producing a test dataset safe to share.

Pipeline, for one patient (any number of exams/series, any folder layout):
  1. Header de-identification with RSNA CTP's anonymizer (scripts/deidentify_dicom_ctp.sh):
     pseudonym, one per-patient date shift, PS3.15 Basic profile. mask_face does NOT touch headers.
  2. Group files into exams (StudyInstanceUID) and series (SeriesInstanceUID). Series that can't
     be masked or can't be trusted are dropped and reported: non-MR, secondary captures /
     screenshots / BurnedInAnnotation=YES (burned-in text), localizers, fewer than --min-slices
     slices.
  3. Face masking per exam with WUSTL NRG's mask_face (Docker image), all of an exam's series in
     one call with a reference series (-r) so every series is masked consistently. Brain
     protection via HD-BET (-bhd 1, GPU) by default. If the whole-exam call fails, each series is
     retried on its own (with the reference), so one bad series can't sink the exam.
  4. Only series that were verifiably masked are written out: same slice count and geometry as
     the input, and some voxels actually changed. Anything else is DROPPED, never copied through
     unmasked.
  5. Header allowlist (scripts/deid_headers.py): CTP's default profile passes through anything it
     doesn't list (e.g. OriginalAttributesSequence with pre-correction accession numbers and real
     dates, ClinicalTrial* elements), so every output header is cut down to what astril, dcm2niix
     and mask_face use, recursively. Then every remaining value is searched for the patient's real
     identifiers (MRN, accession, study ID, names, unshifted dates, original UIDs, the source
     folder name), collected from the original headers. Any match DELETES the output and the
     report lists the tag paths (never the values).
  6. Output: OUT/exam<N>_<shifted StudyDate>/<series>/*.dcm. Next to (not inside) OUT:
     OUT.deid_key.txt (date shift = re-identification key, keep private), OUT.report.txt, and
     OUT.qc/ (mask_face's per-series mosaics: check every face and both ears are obscured).
  7. scripts/check_deidentified_dicom.py on OUT.

All intermediate data (de-identified but NOT yet face-masked) lives in a private scratch folder
that is deleted at the end, also on failure, unless --keep-work.

Requirements (Linux/WSL): python3 with pydicom, numpy and a JPEG decoder for compressed DICOM
(pip install pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg, or python-gdcm); Docker with the mask_face image
(docker pull mmilch01/facemasking:1.21) and, for HD-BET, GPU support (--gpus); plus
deidentify_dicom_ctp.sh's requirements (DicomAnonymizerTool, Java 25+).

    python scripts/deidentify_and_deface.py -i patient_dicom/ -o TEST001_dicom/ -p TEST001
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pydicom
from pydicom.uid import ImplicitVRLittleEndian

from deid_headers import Identifiers, scrub

SCRIPTS = Path(__file__).resolve().parent
SECONDARY_CAPTURE_PREFIX = "1.2.840.10008.5.1.4.1.1.7"
MASKFACE_IMAGE = "mmilch01/facemasking:1.21"


def log(msg):
    print(msg, flush=True)


def run(cmd, logfile=None, **kw):
    with (open(logfile, "w") if logfile else open(os.devnull, "w")) as fh:
        return subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, **kw).returncode


def safe_name(text, fallback):
    s = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")[:40]
    return s or fallback


def scan_series(root):
    """{study_uid: {series_uid: info}} from headers only."""
    studies = defaultdict(dict)
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        try:
            ds = pydicom.dcmread(f, stop_before_pixels=True)
        except Exception:
            continue
        st, se = str(ds.get("StudyInstanceUID", "")), str(ds.get("SeriesInstanceUID", ""))
        info = studies[st].setdefault(se, {
            "files": [], "number": int(ds.get("SeriesNumber", 0) or 0),
            "desc": str(ds.get("SeriesDescription", "") or ds.get("ProtocolName", "")),
            "protocol": str(ds.get("ProtocolName", "")), "modality": str(ds.get("Modality", "")),
            "sop_class": str(ds.get("SOPClassUID", "")), "image_type": " ".join(ds.get("ImageType", [])).upper(),
            "burned_in": str(ds.get("BurnedInAnnotation", "")).upper() == "YES",
            "rows": int(ds.get("Rows", 0) or 0), "cols": int(ds.get("Columns", 0) or 0),
            "frames": int(ds.get("NumberOfFrames", 1) or 1), "study_date": str(ds.get("StudyDate", "")),
            "orientations": set(), "positions": set(),
        })
        info["files"].append(f)
        iop, ipp = ds.get("ImageOrientationPatient"), ds.get("ImagePositionPatient")
        if iop is not None:
            info["orientations"].add(tuple(round(float(v), 3) for v in iop))
        if ipp is not None:
            info["positions"].add(tuple(round(float(v), 2) for v in ipp))
    return studies


def skip_reason(info, min_slices):
    if info["modality"] != "MR":
        return f"modality {info['modality'] or '?'}"
    if info["sop_class"].startswith(SECONDARY_CAPTURE_PREFIX) or info["burned_in"] or "SCREEN" in info["image_type"]:
        return "secondary capture / screenshot (possible burned-in text)"
    if "LOCALIZER" in info["image_type"]:
        return "localizer"
    if info["frames"] > 1:
        return "multi-frame (enhanced) DICOM, not supported by mask_face"
    if len(info["files"]) < min_slices:
        return f"only {len(info['files'])} slice(s) (< --min-slices {min_slices})"
    # mask_face needs ONE 3D volume per series.
    if len(info["orientations"]) > 1:
        return f"slices in {len(info['orientations'])} different orientations (e.g. a localizer)"
    if len(info["positions"]) < len(info["files"]):
        return (f"{len(info['files'])} files but {len(info['positions'])} slice positions: several volumes in one "
                f"series (e.g. DWI/SWI/perfusion); mask_face needs a single 3D volume")
    return None


def series_volume(folder):
    """(array, geometry) of a DICOM series folder, sorted along the slice normal."""
    dss = [pydicom.dcmread(f) for f in sorted(folder.iterdir()) if f.is_file()]
    iop = np.array([float(v) for v in dss[0].ImageOrientationPatient])
    normal = np.cross(iop[:3], iop[3:])
    dss.sort(key=lambda d: float(np.dot(normal, [float(v) for v in d.ImagePositionPatient])))
    arr = np.stack([d.pixel_array.astype(np.float32) for d in dss])
    geom = (len(dss), dss[0].Rows, dss[0].Columns, tuple(np.round(iop, 4)),
            tuple(round(float(v), 2) for v in dss[0].ImagePositionPatient),
            tuple(round(float(v), 4) for v in dss[0].PixelSpacing))
    return arr, geom


def decompress_tree(src_root, dst_root, idents):
    """Copy src_root to dst_root, decompressing every compressed DICOM file.

    Both downstream tools mishandle compressed transfer syntaxes (e.g. JPEG Lossless, common in
    PACS exports), silently: mask_face's DICOM reader produces no output, and CTP's anonymizer can
    fail to parse dates in some encapsulated files and blank them. Also collects the patient's real
    identifiers into idents, for the final leak scan. Returns (number of DICOM files that carried a
    StudyDate, list of files that couldn't be decompressed).
    """
    dated, failed = 0, []
    for i, f in enumerate(sorted(p for p in src_root.rglob("*") if p.is_file())):
        dst = dst_root / f"{i:06d}.dcm"   # flat, neutral names: source names can hold PHI
        try:
            ds = pydicom.dcmread(f)
        except Exception:
            continue   # not DICOM
        dated += bool(str(ds.get("StudyDate", "")).strip())
        idents.harvest(ds)
        try:
            if ds.file_meta.TransferSyntaxUID.is_compressed:
                ds.decompress()   # pydicom plugins: pylibjpeg-libjpeg / -openjpeg, or python-gdcm
            # Implicit VR Little Endian, DICOM's default encoding: mask_face cross-checks its own
            # old reader (dcm2analyze) against dcm2niix and gives up when they disagree, which
            # they did on explicit-VR copies of the same data.
            ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian
            ds.save_as(dst, implicit_vr=True, little_endian=True, enforce_file_format=True)
        except Exception as e:
            failed.append(type(e).__name__)
    return dated, failed


# mmilch01/facemasking:1.21 ships FSL's fslpy helper scripts with #! lines pointing at the image
# builder's Python (/nrgpackages/packages/fsl6/...), which doesn't exist in the image, so they fail
# with "not found". fslswapdim needs imcp whenever it copies a volume -- e.g. reorienting an
# OBLIQUE series -- so every oblique exam failed. Replacements run the same fslpy entry points
# with the image's own Python, and are mounted over the broken scripts for each run.
FSL_BIN_IN_IMAGE = "/nrgpackages/packages/fsl/bin"
IMAGE_PYTHON = "/usr/local/miniconda3/bin/python"
FSLPY_HELPERS = ("imcp", "imglob", "immv", "imrm")


def write_fsl_shims(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for name in FSLPY_HELPERS:
        shim = folder / name
        shim.write_text(f"#!{IMAGE_PYTHON}\nimport sys\nfrom fsl.scripts.{name} import main\nsys.exit(main())\n")
        shim.chmod(0o755)


def mask_face(exam_dir, series_names, ref, args, logfile):
    """Run mask_face in exam_dir (a scratch copy); masked series land in exam_dir/masked_out/."""
    cmd = ["docker", "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}", "-v", f"{exam_dir}:/docker_mount"]
    if args.fsl_shims:
        for name in FSLPY_HELPERS:
            cmd += ["-v", f"{args.fsl_shims / name}:{FSL_BIN_IN_IMAGE}/{name}:ro"]
    if args.brain_protect == "hdbet" and args.gpus != "none":
        cmd += ["--gpus", args.gpus]
    opts = f"-m {args.method} -o masked_out"
    if len(series_names) > 1:
        opts += f" -r {ref}"
    opts += {"hdbet": " -bhd 1", "bet": " -b 1", "none": ""}[args.brain_protect]
    if args.mask_ears:
        opts += " -e 1"
    cmd += [args.image, f"mask_face_nomatlab {','.join(series_names)} {opts}"]
    return run(cmd, logfile)


def scrub_and_scan(out, idents, keep_private):
    """Allowlist-scrub every output header in place, then search what's left for the patient's real
    identifiers. Returns (Counter of removed element names, [(file, tag path, what matched)])."""
    removed, leaks = Counter(), []
    patterns = idents._patterns()
    for f in sorted(p for p in out.rglob("*") if p.is_file()):
        rel = f.relative_to(out)
        for what in idents.find_leaks_in_text(str(rel), patterns):
            leaks.append((rel, "file/folder name", what))
        try:
            ds = pydicom.dcmread(f)
        except Exception:
            continue
        removed.update(path.rsplit(" > ", 1)[-1] for path in scrub(ds, keep_private))
        ds.save_as(f, enforce_file_format=True)
        leaks += [(rel, path, what) for path, what in idents.find_leaks(pydicom.dcmread(f, stop_before_pixels=True), patterns)]
    return removed, leaks


def verify_masked(src, dst):
    """None if dst is a masked version of src, else the reason it isn't."""
    if not dst.is_dir() or not any(dst.iterdir()):
        return "no masked output"
    try:
        a, ga = series_volume(src)
        b, gb = series_volume(dst)
    except Exception as e:
        return f"unreadable output ({e})"
    if ga != gb:
        return "masked output has different slices/geometry"
    changed = float(np.mean(np.abs(a - b) > 1))
    if changed == 0:
        return "output identical to input (nothing was masked)"
    if changed > 0.5:
        return f"{changed:.0%} of voxels changed (implausible for face masking)"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("-i", "--input", required=True, type=Path, help="one patient's DICOM files (all exams)")
    ap.add_argument("-o", "--output", required=True, type=Path, help="output folder (must not exist)")
    ap.add_argument("-p", "--pseudonym", required=True, help="PatientName/PatientID to write, e.g. TEST001")
    ap.add_argument("-d", "--date-shift", type=int, help="days to shift all dates (default: random, see deidentify_dicom_ctp.sh)")
    ap.add_argument("--ref-pattern", help="regex (case-insensitive) on SeriesDescription/ProtocolName choosing each exam's "
                                          "reference series, e.g. 'mprage|t1.*(post|gad|\\+c)'. Default: the series with the most voxels")
    ap.add_argument("--brain-protect", choices=["hdbet", "bet", "none"], default="hdbet",
                    help="exclude the brain from masking with HD-BET (GPU, default), FSL BET, or not at all")
    ap.add_argument("--gpus", default="all", help="docker --gpus value for HD-BET ('none' to omit)")
    ap.add_argument("--method", default="normfilter", choices=["normfilter", "coating", "blur"], help="mask_face obscuring method")
    ap.add_argument("--mask-ears", action=argparse.BooleanOptionalAction, default=True,
                    help="also mask the ears (mask_face -e 1); default on")
    ap.add_argument("--min-slices", type=int, default=10, help="drop series with fewer slices than this")
    ap.add_argument("--keep-private", action="store_true", help="keep private DICOM tags (see deidentify_dicom_ctp.sh -k)")
    ap.add_argument("--image", default=MASKFACE_IMAGE, help="mask_face Docker image")
    ap.add_argument("--no-fsl-shims", action="store_true",
                    help="don't mount replacements for the image's broken FSL helper scripts (imcp etc.); "
                         "only for a fixed future image")
    ap.add_argument("--work-dir", type=Path, help="parent for the private scratch folder (default: system temp)")
    ap.add_argument("--keep-work", action="store_true", help="keep the scratch folder (contains UNMASKED faces)")
    args = ap.parse_args()

    out = args.output.resolve()
    if out.exists():
        sys.exit(f"ERROR: output folder already exists: {out}")
    if not args.input.is_dir():
        sys.exit(f"ERROR: input folder not found: {args.input}")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.pseudonym):
        sys.exit("ERROR: pseudonym may only contain letters, digits, _ and -")
    ref_re = re.compile(args.ref_pattern, re.I) if args.ref_pattern else None

    os.umask(0o077)
    work = Path(tempfile.mkdtemp(prefix="astril_deface_", dir=args.work_dir))
    # No input path here: source folder names often hold MRNs or names. It's recorded only in the
    # private key file.
    report = [f"pseudonym: {args.pseudonym}",
              f"brain protection: {args.brain_protect}, method: {args.method}, ears masked: "
              f"{'yes' if args.mask_ears else 'no'}, image: {args.image}", ""]
    scrubbed = False   # until the header scrub and leak scan pass, OUT must not survive the run
    try:
        args.fsl_shims = None
        if not args.no_fsl_shims:
            args.fsl_shims = work / "fsl_shims"
            write_fsl_shims(args.fsl_shims)

        # 0. Uncompressed working copy (private scratch; still identifiable at this point).
        raw = work / "raw"
        raw.mkdir()
        log("Decompressing a working copy...")
        idents = Identifiers()
        idents.add_id(args.input.resolve().name)   # source folder names are often MRNs
        n_dated, undecodable = decompress_tree(args.input, raw, idents)
        if undecodable:
            report.append(f"{len(undecodable)} file(s) could not be decompressed and were left out "
                          f"({', '.join(sorted(set(undecodable)))}); install pylibjpeg-libjpeg / python-gdcm?")

        # 1. Header de-identification.
        deid = work / "deid"
        cmd = ["bash", str(SCRIPTS / "deidentify_dicom_ctp.sh"), "-i", str(raw), "-o", str(deid), "-p", args.pseudonym]
        if args.date_shift is not None:
            cmd += ["-d", str(args.date_shift)]
        if args.keep_private:
            cmd.append("-k")
        if subprocess.run(cmd).returncode != 0:
            sys.exit("ERROR: header de-identification failed")

        # 2. Exams and series.
        studies = scan_series(deid)
        if not studies:
            sys.exit("ERROR: no DICOM files found after de-identification")
        undated = sum(1 for se in studies.values() for inf in se.values() if not inf["study_date"])
        if n_dated and undated:
            sys.exit(f"ERROR: the input had study dates but {undated} de-identified series have none: the date "
                     "shift failed (CTP blanks dates it can't parse). Nothing was written.")
        out.mkdir(parents=True)
        qc = Path(str(out) + ".qc")
        qc.mkdir()
        kept_total = dropped_total = 0
        for n, (study_uid, series) in enumerate(sorted(studies.items(), key=lambda kv: next(iter(kv[1].values()))["study_date"]), 1):
            date = next(iter(series.values()))["study_date"] or "nodate"
            exam_label = f"exam{n}_{date}"
            report.append(f"== {exam_label} ({len(series)} series)")
            exam_dir = work / "mask" / exam_label
            exam_dir.mkdir(parents=True)
            usable = {}
            for uid, info in sorted(series.items(), key=lambda kv: kv[1]["number"]):
                name = f"s{info['number']:03d}_{safe_name(info['desc'], 'series')}"
                while name in usable:
                    name += "_b"
                reason = skip_reason(info, args.min_slices)
                if reason:
                    report.append(f"   DROPPED {name}: {reason}")
                    dropped_total += 1
                    continue
                (exam_dir / name).mkdir()
                for i, f in enumerate(info["files"]):
                    shutil.copy2(f, exam_dir / name / f"{i:05d}.dcm")
                usable[name] = info
            if not usable:
                report.append("   (nothing to mask)")
                continue

            # Reference series: explicit pattern, else the most voxels (usually the 3D T1).
            ref = None
            if ref_re:
                ref = next((nm for nm, inf in usable.items() if ref_re.search(inf["desc"]) or ref_re.search(inf["protocol"])), None)
                if ref is None:
                    report.append(f"   no series matches --ref-pattern; falling back to the largest series")
            if ref is None:
                ref = max(usable, key=lambda nm: usable[nm]["rows"] * usable[nm]["cols"] * len(usable[nm]["files"]))
            report.append(f"   reference: {ref}")
            names = [ref] + [nm for nm in usable if nm != ref]
            log(f"[{exam_label}] masking {len(names)} series (reference {ref})...")

            # 3. Mask the whole exam; fall back to one series at a time.
            rc = mask_face(exam_dir, names, ref, args, work / f"{exam_label}.maskface.log")
            failed = [nm for nm in names if verify_masked(exam_dir / nm, exam_dir / "masked_out" / nm)]
            qc_from = {nm: exam_dir for nm in names}
            if rc != 0 or failed:
                log(f"[{exam_label}] whole-exam run {'exited with an error' if rc else 'finished'}; {len(failed)} of "
                    f"{len(names)} series not verifiably masked{', retrying them individually' if failed else ''}")
                # Only the series without verified output: a failed exit often comes from one bad
                # series after the rest were masked, and verify_masked rejects partial writes.
                for nm in failed:
                    # Each retry in a FRESH folder: mask_face leaves intermediates behind that make
                    # a second run in the same folder fail ("multiple possible filenames").
                    retry_dir = work / "retry" / exam_label / nm
                    single = [ref] if nm == ref else [ref, nm]
                    for s_nm in single:
                        shutil.copytree(exam_dir / s_nm, retry_dir / s_nm)
                    mask_face(retry_dir, single, ref, args, work / f"{exam_label}.{nm}.maskface.log")
                    shutil.rmtree(exam_dir / "masked_out" / nm, ignore_errors=True)
                    if (retry_dir / "masked_out" / nm).is_dir():
                        shutil.copytree(retry_dir / "masked_out" / nm, exam_dir / "masked_out" / nm)
                    qc_from[nm] = retry_dir

            # 4. Keep only verifiably masked series.
            for nm in names:
                reason = verify_masked(exam_dir / nm, exam_dir / "masked_out" / nm)
                if reason:
                    report.append(f"   DROPPED {nm}: masking failed ({reason})")
                    dropped_total += 1
                    continue
                shutil.copytree(exam_dir / "masked_out" / nm, out / exam_label / nm)
                kept_total += 1
                report.append(f"   kept    {nm} ({len(usable[nm]['files'])} slices)")
                for png in (qc_from[nm] / "maskface").glob(f"{nm}*.png"):
                    shutil.copy2(png, qc / f"{exam_label}_{png.name}")

        # 5. Header allowlist + leak scan against the ORIGINAL identifiers (CTP's default profile
        # passes through anything it doesn't list, e.g. OriginalAttributesSequence, ClinicalTrial*).
        log("Scrubbing headers and scanning them for the original identifiers...")
        removed, leaks = scrub_and_scan(out, idents, args.keep_private)
        report.append("")
        report.append("Header elements removed after CTP (allowlist), files affected:")
        report += [f"   {name}: {n}" for name, n in sorted(removed.items())] or ["   none"]
        if leaks:
            by_path = Counter((path, what) for _, path, what in leaks)
            report.append("")
            report.append(f"!! LEAK: {len(leaks)} value(s) still match the patient's original identifiers. The output "
                          f"was DELETED. Tag paths (values not shown):")
            report += [f"   {path}: {what} ({n} files)" for (path, what), n in sorted(by_path.items())]
            Path(str(out) + ".report.txt").write_text("\n".join(report) + "\n")
            log("\n".join(report))
            return 2
        scrubbed = True

        # mask_face logs (commands and scratch-folder series names only) for diagnosing failures.
        logs = Path(str(out) + ".logs")
        logs.mkdir()
        for lf in work.glob("*.maskface.log"):
            shutil.copy2(lf, logs / lf.name)

        # 6. Key and report next to the output.
        key_src = Path(str(deid) + ".deid_key.txt")
        key_dst = Path(str(out) + ".deid_key.txt")
        key_dst.write_text(key_src.read_text().replace(str(deid), str(out)))
        report.append("")
        report.append(f"{kept_total} series masked and written, {dropped_total} dropped.")
        Path(str(out) + ".report.txt").write_text("\n".join(report) + "\n")
        log("\n".join(report))
        log(f"\nOutput: {out}\nKey (keep private): {key_dst}\nQC mosaics (check every face and ear is obscured): {qc}\n"
            f"mask_face logs: {logs}\n")

        # 7. Header check, with its own independent leak scan against the originals.
        rc = subprocess.run([sys.executable, str(SCRIPTS / "check_deidentified_dicom.py"), str(out),
                             "--originals", str(args.input)]).returncode
        return rc
    finally:
        if not scrubbed and out.exists():
            shutil.rmtree(out, ignore_errors=True)
            log("Output folder DELETED: its headers were not verified clean (leak found, or the run stopped early).")
        if args.keep_work:
            log(f"Scratch folder kept (contains UNMASKED faces -- delete it when done): {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
