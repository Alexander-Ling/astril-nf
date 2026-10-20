#!/usr/bin/env python3
"""Cirro pre-run staging for astril-nf Stage 1b (execute the DICOM->NIfTI conversion plan).

The input dataset is always this pipeline's own Stage 1a output, so process-input.json maps the
plan and both root markers straight from its `01a-plan-conversion/` folder. If the user also
selected an edited plan (a separate upload, via the optional form picker), resolve it to that
dataset's single .csv and use it in place of Stage 1a's plan. The root markers stay: an edited
plan keeps Stage 1a's folder/path columns, which still need re-pointing at this run's copies.
"""
from urllib.parse import urlparse

import boto3
from cirro.helpers.preprocess_dataset import PreprocessDataset


def _data_root(dataset_uri: str) -> str:
    # Dataset pickers return the dataset's root; its files live under `data/`.
    root = dataset_uri.rstrip("/")
    return root if root.endswith("/data") else f"{root}/data"


def _list_files(prefix_uri: str) -> list[str]:
    parsed = urlparse(prefix_uri.rstrip("/") + "/")
    bucket, prefix = parsed.netloc, parsed.path.lstrip("/")
    paginator = boto3.client("s3").get_paginator("list_objects_v2")
    return [
        f"s3://{bucket}/{obj['Key']}"
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
    ]


def _find_single(dataset_uri: str, suffix: str, what: str) -> str:
    matches = [f for f in _list_files(_data_root(dataset_uri)) if f.lower().endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {suffix} file in the selected {what} dataset, found "
            f"{len(matches)}: {matches[:10]}"
        )
    return matches[0]


def run(ds: PreprocessDataset):
    # Separate from main() so it can also be exercised against real project datasets from
    # outside Cirro via the SDK's DataPortal().developer_helper.generate_preprocess_for_input_datasets().
    edited = ds.params.get("edited_plan_dataset")
    if edited:
        plan_csv = _find_single(edited, ".csv", "edited conversion plan")
        ds.logger.info(f"Using edited conversion plan {plan_csv} instead of Stage 1a's own plan.")
        ds.add_param("conversion_plan", plan_csv, overwrite=True)
    else:
        ds.logger.info("No edited plan selected; using Stage 1a's conversion plan as-is.")
    ds.remove_param("edited_plan_dataset", force=True)


def main():
    run(PreprocessDataset.from_running())


if __name__ == "__main__":
    main()
