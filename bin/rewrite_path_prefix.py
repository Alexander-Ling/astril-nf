#!/usr/bin/env python3
"""Rewrite absolute-path prefixes in one or more columns of a CSV/TSV table.

astril's DICOM index (`organize_dicoms`) and conversion plan
(`plan_dicom_to_nifti_conversion`) both bake in *absolute* paths at the moment they are
written (e.g. `os.path.abspath(root_dir)`), because a single astril invocation always runs
in one process. In Nextflow, each stage runs in its own task work directory, so a path
baked in by an upstream task is not valid inside the downstream task even though the same
directory (by content) has been re-staged there under the same relative name.

This script rewrites one or more columns of a plan/index table by replacing an old absolute
prefix with a new one, so the downstream astril CLI call sees paths that resolve inside its
own task directory. No astril source changes are needed; this is pure orchestration glue.
"""
import argparse
import csv
import sys


def _delimiter_for(path: str) -> str:
    return "\t" if path.lower().endswith((".tsv", ".txt")) else ","


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Input CSV/TSV table.")
    parser.add_argument("--output", required=True, help="Output CSV/TSV table.")
    parser.add_argument(
        "--rewrite",
        action="append",
        required=True,
        metavar="COLUMN=OLD_PREFIX::NEW_PREFIX",
        help=(
            "One rewrite rule; repeatable. Any value in COLUMN that starts with "
            "OLD_PREFIX has that prefix replaced with NEW_PREFIX. Rows where the column "
            "is empty, '-', or does not start with OLD_PREFIX are left unchanged."
        ),
    )
    args = parser.parse_args()

    rules = []
    for spec in args.rewrite:
        try:
            column, rest = spec.split("=", 1)
            old_prefix, new_prefix = rest.split("::", 1)
        except ValueError:
            parser.error(f"Malformed --rewrite spec: {spec!r}")
        rules.append((column, old_prefix, new_prefix))

    in_delim = _delimiter_for(args.input)
    out_delim = _delimiter_for(args.output)

    with open(args.input, newline="", encoding="utf-8") as fin:
        reader = csv.DictReader(fin, delimiter=in_delim)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    for column, old_prefix, new_prefix in rules:
        if column not in fieldnames:
            print(
                f"[rewrite_path_prefix] WARNING: column {column!r} not found in "
                f"{args.input}; skipping this rule.",
                file=sys.stderr,
            )
            continue
        n_rewritten = 0
        for row in rows:
            val = (row.get(column) or "").strip()
            if val and val not in ("-",) and val.startswith(old_prefix):
                row[column] = new_prefix + val[len(old_prefix):]
                n_rewritten += 1
        print(
            f"[rewrite_path_prefix] {column}: rewrote {n_rewritten}/{len(rows)} rows "
            f"({old_prefix!r} -> {new_prefix!r})",
            file=sys.stderr,
        )

    with open(args.output, "w", newline="", encoding="utf-8") as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames, delimiter=out_delim)
        writer.writeheader()
        writer.writerows(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
