#!/usr/bin/env python3
"""Cirro pre-run staging for astril-nf Stage 3a (segment).

1. Where the preprocessed library sits inside the input dataset: a Stage 2 dataset publishes it
   under `02-preprocess/preprocessed_library/`; a direct upload has it at the dataset's top level.
   Decided by the input dataset's own process id.
2. The optional custom model (form picker): an uploaded directory with its own pipeline.json plus
   checkpoints. If selected, model_dir points at the folder holding that pipeline.json -- and it
   is an error, not a silent fallback to `model_family`, if there isn't exactly one, since the
   user explicitly asked for a custom model.
3. The optional labels.json override for the automatic quantify (form picker), resolved to that
   dataset's single .json.
"""
from urllib.parse import urlparse

import boto3
from cirro.helpers.preprocess_dataset import PreprocessDataset

PREPROCESS_PROCESS_ID = "process-astril-preprocess-1-0"


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
    if parent == PREPROCESS_PROCESS_ID:
        lib = ds.params["preprocessed_dir"].rstrip("/") + "/02-preprocess/preprocessed_library"
        ds.logger.info(f"Input is a Stage 2 dataset; preprocessed library at {lib}")
        ds.add_param("preprocessed_dir", lib, overwrite=True)
    else:
        ds.logger.info(f"Input is a direct upload ({parent}); preprocessed library at the dataset's top level.")

    model = ds.params.get("model_dataset")
    if model:
        pipeline_json = _find_single(model, "/pipeline.json", "custom model")
        model_dir = pipeline_json.rsplit("/", 1)[0]
        ds.logger.info(f"Using custom model at {model_dir} (model_family is ignored).")
        ds.add_param("model_dir", model_dir, overwrite=True)
    else:
        ds.logger.info(f"No custom model selected; using model_family={ds.params.get('model_family')}.")
    ds.remove_param("model_dataset", force=True)

    labels = ds.params.get("labels_json_dataset")
    if labels:
        labels_json = _find_single(labels, ".json", "labels contract")
        ds.logger.info(f"Using labels contract {labels_json} for the automatic quantify.")
        ds.add_param("labels_json", labels_json, overwrite=True)
    ds.remove_param("labels_json_dataset", force=True)


def main():
    run(PreprocessDataset.from_running())


if __name__ == "__main__":
    main()
