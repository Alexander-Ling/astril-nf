#!/usr/bin/env python3
"""Cirro pre-run staging for astril-nf Stage 3b (quantify), when run on its own.

1. Where the segmentation masks sit inside the input dataset: a Stage 3a dataset publishes them
   under `03-segment/`; a direct upload (e.g. manually corrected masks) has them at the dataset's
   top level. Decided by the input dataset's own process id.
2. The optional labels.json contract (form picker), resolved to that dataset's single .json.
"""
from urllib.parse import urlparse

import boto3
from cirro.helpers.preprocess_dataset import PreprocessDataset

SEGMENT_PROCESS_ID = "process-astril-segment-1-0"


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

    parent = ds.metadata["inputs"][0]["processId"]
    if parent == SEGMENT_PROCESS_ID:
        seg_dir = ds.params["seg_dir"].rstrip("/") + "/03-segment"
        ds.logger.info(f"Input is a Stage 3a dataset; masks at {seg_dir}")
        ds.add_param("seg_dir", seg_dir, overwrite=True)
    else:
        ds.logger.info(f"Input is a direct upload ({parent}); masks at the dataset's top level.")

    labels = ds.params.get("labels_json_dataset")
    if labels:
        labels_json = _find_single(labels, ".json", "labels contract")
        ds.logger.info(f"Using labels contract {labels_json}")
        ds.add_param("labels_json", labels_json, overwrite=True)
    ds.remove_param("labels_json_dataset", force=True)


def main():
    run(PreprocessDataset.from_running())


if __name__ == "__main__":
    main()
