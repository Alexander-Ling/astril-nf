#!/usr/bin/env python3
"""Build the cumulative, reference-space-safe input directory for Stage 2 (preprocess).

astril's `preprocess_brain_mris` (`preprocess_library()`) picks one shared registration
reference per patient and can reuse a previously-chosen reference via `--old_coreg_log`
(matched by an exact *relative* path under `in_dir`, columns `Patient` /
`ReferenceRelativePath` -- see `preprocess_brain_mris.py::_read_old_coreg_logs` and
`_choose_reference_for_patient`). If that reference file isn't present in the current run's
`in_dir`, astril silently falls back to picking a *new* reference for that patient instead of
failing -- which is exactly the reference-space drift this pipeline must prevent when merging
new exams into an existing preprocessed library.

This script:
  1. Unions the new NIfTI exams with the earlier raw NIfTI inputs supplied explicitly via
     --prior-nifti-dir (if any), preserving the `{patient}/{exam}/...` layout astril expects.
     The prior preprocessed library itself carries no raw images (they're whole-head, i.e.
     identifiable, and would only duplicate data the caller already has), so the earlier exams
     must be passed in rather than carried forward inside it.
  2. Locates the most recent `coreg_log_*.csv` in the prior library (if any) and copies it out
     for the caller to pass as `--old_coreg_log`.
  3. Fails loudly -- instead of letting astril silently re-pick -- if any patient's previously
     logged reference exam is missing from the union.
"""
import argparse
import csv
import glob
import os
import shutil
import sys
from pathlib import Path


def _copy(src: Path, dst: Path) -> None:
    # Always a real copy, never a symlink: the union directory built here gets staged into a
    # SEPARATE Nextflow task (often a different Docker container entirely) than the one that
    # ran this script. A symlink to an absolute path from THIS task's work directory would not
    # resolve inside that other container, which typically only has its own task's files
    # bind-mounted -- confirmed by a real "No such file or directory" failure when the
    # preprocess task tried to read a symlinked file left behind by this step.
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def _union_patient_trees(source_root: Path, union_root: Path, source_label: str) -> None:
    if not source_root or not source_root.is_dir():
        return
    for patient_dir in sorted(p for p in source_root.iterdir() if p.is_dir()):
        for exam_dir in sorted(p for p in patient_dir.iterdir() if p.is_dir()):
            dest_exam_dir = union_root / patient_dir.name / exam_dir.name
            if dest_exam_dir.exists():
                print(
                    f"[merge_cumulative_nifti_library] NOTE: exam {patient_dir.name}/"
                    f"{exam_dir.name} already present in union; keeping the copy already "
                    f"staged and ignoring the one from {source_label}.",
                    file=sys.stderr,
                )
                continue
            for item in exam_dir.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(source_root)
                    _copy(item, union_root / rel)


def _find_most_recent_coreg_log(prior_library_dir: Path | None) -> Path | None:
    if not prior_library_dir or not prior_library_dir.is_dir():
        return None
    candidates = sorted(glob.glob(str(prior_library_dir / "coreg_log_*.csv")))
    return Path(candidates[-1]) if candidates else None


def _read_reference_map(coreg_log: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with coreg_log.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        patient_key = path_key = None
        for k in reader.fieldnames or []:
            lk = k.strip().lower()
            if lk in ("patient", "patientid", "patient_id"):
                patient_key = k
            if lk in ("referencerelativepath", "reference_relative_path", "relative_ref_path"):
                path_key = k
        if not patient_key or not path_key:
            return mapping
        for row in reader:
            pat = (row.get(patient_key) or "").strip()
            rel = (row.get(path_key) or "").strip()
            if pat and rel:
                mapping[pat] = rel
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-nifti-dir", required=True, type=Path,
                         help="Newly converted/uploaded NIfTI exams, {patient}/{exam}/...")
    parser.add_argument("--prior-library-dir", type=Path, default=None,
                         help="Prior Stage 2 preprocessed library (optional; omit for a first "
                              "run). Only its coreg log is used: it pins each patient's "
                              "registration reference.")
    parser.add_argument("--prior-nifti-dir", type=Path, action="append", default=[],
                         help="Earlier raw NIfTI library, {patient}/{exam}/... (repeatable). "
                              "Together with --new-nifti-dir it must contain every exam to "
                              "preprocess, including each prior patient's reference exam.")
    parser.add_argument("--output-dir", required=True, type=Path,
                         help="Union directory to build; pass this as preprocess_brain_mris's "
                              "--in_dir.")
    parser.add_argument("--old-coreg-log-out", type=Path, default=None,
                         help="If a prior coreg log is found, copy it here.")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Earlier inputs first: on a duplicate exam, keep the copy the prior run's references
    # were chosen from.
    for prior_nifti in args.prior_nifti_dir:
        _union_patient_trees(prior_nifti, args.output_dir, f"earlier NIfTI {prior_nifti}")
    _union_patient_trees(args.new_nifti_dir, args.output_dir, "new NIfTI exams")

    coreg_log = _find_most_recent_coreg_log(args.prior_library_dir)
    if coreg_log is not None:
        if args.old_coreg_log_out is not None:
            args.old_coreg_log_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(coreg_log, args.old_coreg_log_out)
        reference_map = _read_reference_map(coreg_log)
        missing = []
        for patient, rel_path in reference_map.items():
            if not (args.output_dir / rel_path).exists():
                missing.append((patient, rel_path))
        if missing:
            lines = "\n".join(f"  - {p}: expected {r}" for p, r in missing)
            raise SystemExit(
                "[merge_cumulative_nifti_library] REFUSING to continue: the following "
                "patients' previously-chosen registration reference exam is missing from "
                "this run's merged NIfTI input. Continuing would let astril silently pick a "
                "*new* reference for these patients, putting their older and newer exams in "
                "different reference spaces. Supply the earlier NIfTI input(s) holding these "
                "exams (prior_nifti_dirs), or exclude these patients from this run:\n" + lines
            )
        print(
            f"[merge_cumulative_nifti_library] Verified reference exams present for "
            f"{len(reference_map)} patient(s) from {coreg_log}.",
            file=sys.stderr,
        )
    else:
        print(
            "[merge_cumulative_nifti_library] No prior coreg log found; treating this as a "
            "first-time (or all-new-patient) run.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
