#!/usr/bin/env python3
"""Cirro pre-run staging for astril-nf Stage 1a (plan DICOM->NIfTI conversion).

The input dataset is always this pipeline's own Stage 0 output, so process-input.json maps the
organized tree, index, and root marker straight from its `00-organize/` folder. The one thing
that can't be mapped statically is the filled-in patient metadata table: it's a separate,
user-uploaded dataset chosen via a form picker, and its file name is whatever the user uploaded.
Resolve it here to the dataset's single .csv, and fail loudly if there isn't exactly one.
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
    metadata_csv = _find_single(ds.params["patient_metadata_dataset"], ".csv", "patient metadata")
    ds.logger.info(f"Using patient metadata table {metadata_csv}")
    ds.add_param("patient_metadata", metadata_csv, overwrite=True)
    ds.remove_param("patient_metadata_dataset", force=True)


def main():
    run(PreprocessDataset.from_running())


if __name__ == "__main__":
    main()
