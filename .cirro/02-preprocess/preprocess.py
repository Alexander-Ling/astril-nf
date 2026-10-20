#!/usr/bin/env python3
"""Cirro pre-run staging for astril-nf Stage 2 (preprocess: register/skull-strip/normalize).

Two things can't be mapped statically in process-input.json:

1. Where the NIfTI library sits inside the input dataset. A Stage 1b dataset publishes it under
   `01b-convert/nifti_out/`; a direct upload has `{patient}/{exam}/...` at the dataset's top
   level. Which one applies is decided by the input dataset's own process id -- an explicit
   fact Cirro records, not a guess from the files.
2. The optional prior preprocessed library (form picker). When selected, point
   prior_preprocessed_dir at that Stage 2 dataset's `02-preprocess/preprocessed_library/`
   (which carries the coreg log and `_raw_passthrough/` exams bin/merge_cumulative_nifti_library.py
   needs). When blank, drop it so main.nf's NO_PRIOR_LIBRARY default applies.
"""
from cirro.helpers.preprocess_dataset import PreprocessDataset

CONVERT_PROCESS_ID = "process-astril-convert-1-0"


def _data_root(dataset_uri: str) -> str:
    # Dataset pickers return the dataset's root; its files live under `data/`.
    root = dataset_uri.rstrip("/")
    return root if root.endswith("/data") else f"{root}/data"


def run(ds: PreprocessDataset):
    # Separate from main() so it can also be exercised against real project datasets from
    # outside Cirro via the SDK's DataPortal().developer_helper.generate_preprocess_for_input_datasets().

    parent = ds.metadata["inputs"][0]["processId"]
    if parent == CONVERT_PROCESS_ID:
        nifti_dir = ds.params["nifti_dir"].rstrip("/") + "/01b-convert/nifti_out"
        ds.logger.info(f"Input is a Stage 1b dataset; NIfTI library at {nifti_dir}")
        ds.add_param("nifti_dir", nifti_dir, overwrite=True)
    else:
        ds.logger.info(f"Input is a direct upload ({parent}); NIfTI library at the dataset's top level.")

    prior = ds.params.get("prior_preprocessed_dataset")
    if prior:
        prior_dir = _data_root(prior) + "/02-preprocess/preprocessed_library"
        ds.logger.info(f"Incremental run: continuing prior preprocessed library at {prior_dir}")
        ds.add_param("prior_preprocessed_dir", prior_dir, overwrite=True)
    else:
        ds.logger.info("First-time run: every patient gets a freshly chosen reference.")
    ds.remove_param("prior_preprocessed_dataset", force=True)


def main():
    run(PreprocessDataset.from_running())


if __name__ == "__main__":
    main()
