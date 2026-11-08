#!/usr/bin/env python3
"""Summarize what's left in a de-identified DICOM tree, for a human to review before sharing.

Reads every file's header (not pixel data), INCLUDING nested sequence items, and reports:
  - PatientName / PatientID values (should be only the pseudonym)
  - study dates per study (should be shifted, with intervals intact)
  - elements outside the de-identification allowlist (scripts/deid_headers.py), by tag path:
    identifiers, dates other than the shifted Study/Series/Acquisition/Content dates, person
    names, free-text comments, OriginalAttributesSequence, ClinicalTrial* ... (should be none)
  - with --originals: values matching the patient's real identifiers (MRN, accession, names,
    unshifted dates, original UIDs) taken from the ORIGINAL files (should be none)
  - series likely to carry burned-in text in the pixels (secondary captures, screenshots,
    BurnedInAnnotation=YES): header de-identification can't clean those, drop them
  - private tags, if any were kept
  - every distinct free-text description / protocol name, which the de-identification keeps
    (astril classifies series by them) and which must be read by a person

Flagged elements are reported by tag path only, never by value, so the summary down to the
free-text section can be shared for troubleshooting. The free-text section shows values: don't
share it unreviewed.

Exit status 1 if anything in the third-to-fifth categories is found. This is a review aid, not
a guarantee: free text and pixel data still need a human look.

    python scripts/check_deidentified_dicom.py DEIDENTIFIED_DIR [--originals ORIGINAL_DIR]
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pydicom

from deid_headers import Identifiers, structural_problems

FREE_TEXT = ["StudyDescription", "SeriesDescription", "ProtocolName", "PerformedProcedureStepDescription",
             "RequestedProcedureDescription", "ImageComments", "SeriesComments"]
SECONDARY_CAPTURE_PREFIX = "1.2.840.10008.5.1.4.1.1.7"   # all Secondary Capture SOP classes


def dicom_files(root):
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        try:
            yield f, pydicom.dcmread(f, stop_before_pixels=True)
        except Exception:
            yield f, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", type=Path)
    ap.add_argument("--originals", type=Path, help="the ORIGINAL (identified) files of the same patient: search "
                                                   "the de-identified headers for their identifiers")
    args = ap.parse_args()

    idents = None
    if args.originals:
        idents = Identifiers()
        idents.add_id(args.originals.resolve().name)
        for _, ds in dicom_files(args.originals):
            if ds is not None:
                idents.harvest(ds)
        patterns = idents._patterns()

    names, ids, not_dicom = Counter(), Counter(), 0
    study_dates = defaultdict(set)
    flagged = Counter()
    leaks = Counter()
    burned_in = set()
    private = Counter()
    free_text = defaultdict(Counter)
    n = 0
    for f, ds in dicom_files(args.root):
        if ds is None:
            not_dicom += 1
            continue
        n += 1
        names[str(ds.get("PatientName", ""))] += 1
        ids[str(ds.get("PatientID", ""))] += 1
        study_dates[str(ds.get("StudyInstanceUID", ""))].add(str(ds.get("StudyDate", "")))
        flagged.update(structural_problems(ds))
        if idents:
            leaks.update(idents.find_leaks(ds, patterns))
            leaks.update(("file/folder name", w) for w in idents.find_leaks_in_text(str(f.relative_to(args.root)), patterns))
        series = f"{ds.get('SeriesNumber', '?')} {ds.get('SeriesDescription', '')}".strip()
        if str(ds.get("SOPClassUID", "")).startswith(SECONDARY_CAPTURE_PREFIX) \
                or str(ds.get("BurnedInAnnotation", "")).upper() == "YES" \
                or "SCREEN" in " ".join(ds.get("ImageType", [])).upper():
            burned_in.add(series)
        for elem in ds:
            if elem.tag.is_private:
                private[f"({elem.tag.group:04x},xxxx)"] += 1
        for kw in FREE_TEXT:
            v = ds.get(kw)
            if v not in (None, ""):
                free_text[kw][str(v)] += 1

    print(f"{n} DICOM files ({not_dicom} other files)\n")
    print("PatientName:", dict(names))
    print("PatientID:  ", dict(ids))
    print("\nStudy dates (one line per study):")
    for uid, dates in sorted(study_dates.items(), key=lambda kv: sorted(kv[1])):
        print(f"  {', '.join(sorted(dates)) or '(none)'}   study {uid[-12:]}")
    problems = 0
    undated = [uid for uid, dates in study_dates.items() if not any(dates)]
    if undated:
        problems += 1
        print(f"  !! {len(undated)} stud(ies) with no StudyDate: the date shift may have failed (CTP blanks dates it "
              "can't parse, e.g. in some compressed files). astril needs dates for timepoints.")
    print("\nElements outside the de-identification allowlist (tag path: files):" + (" none" if not flagged else ""))
    for path, c in sorted(flagged.items()):
        problems += 1
        print(f"  !! {path}: {c}")
    if idents:
        print("\nValues matching the original identifiers (tag path: what it matched, files):" + (" none" if not leaks else ""))
        for (path, what), c in sorted(leaks.items()):
            problems += 1
            print(f"  !! {path}: {what}, {c}")
    print("\nSeries likely to have burned-in text (drop them):" + (" none" if not burned_in else ""))
    for s in sorted(burned_in):
        problems += 1
        print(f"  !! {s}")
    print("\nPrivate tag groups kept:" + (" none" if not private else ""))
    for g, c in sorted(private.items()):
        print(f"  {g}: {c} elements")
    if len(names) > 1 or len(ids) > 1:
        problems += 1
        print("\n!! More than one PatientName/PatientID value: expected only the pseudonym.")
    print("\nFree text kept for series classification -- READ for names, MRNs, dates (shows values: don't share unreviewed):")
    for kw in FREE_TEXT:
        for v, c in sorted(free_text[kw].items()):
            print(f"  {kw}: {v!r} ({c} files)")
    print(f"\n{'PROBLEMS FOUND' if problems else 'No automatic problems found'}; free text and pixel data still need a human review.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
