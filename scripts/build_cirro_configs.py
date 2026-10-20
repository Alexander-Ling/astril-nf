#!/usr/bin/env python3
"""Generate the per-entry-point Cirro config files under .cirro/<stage>/.

Each Cirro pipeline is an ENTRY POINT: it starts at one stage (main.nf --stage) and runs every
later stage up to the user's "Stop after" choice (--stop_after). Its form, input mapping and
preprocess script therefore need the fields of every stage it can run, and those must stay
identical across the entry points that share them. This script defines each stage's fields ONCE
and writes, for every .cirro/<stage>/ folder:

    process-form.json, process-input.json, preprocess.py, process-compute.config,
    process-output.json (entry points that can reach quantify)

process-definition.json (id, name, description, parents) stays hand-written.

    python scripts/build_cirro_configs.py           # regenerate
    python scripts/build_cirro_configs.py --check   # fail if the committed files are stale
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CIRRO_DIR = REPO_ROOT / ".cirro"

STAGES = ["organize", "plan_convert", "convert", "preprocess", "segment", "quantify"]
FOLDER = {
    "organize": "00-organize",
    "plan_convert": "01a-plan-conversion",
    "convert": "01b-convert",
    "preprocess": "02-preprocess",
    "segment": "03-segment",
    "quantify": "03b-quantify",
}
PROCESS_ID = {
    "organize": "process-astril-organize-1-0",
    "plan_convert": "process-astril-plan-conversion-1-0",
    "convert": "process-astril-convert-1-0",
    "preprocess": "process-astril-preprocess-1-0",
    "segment": "process-astril-segment-1-0",
    "quantify": "process-astril-quantify-1-0",
}
STAGE_TITLE = {
    "organize": "Organize DICOM",
    "plan_convert": "Plan conversion",
    "convert": "Convert to NIfTI",
    "preprocess": "Preprocess (register / skull-strip / normalize)",
    "segment": "Segment",
    "quantify": "Quantify volumes",
}


def produced_by(stage):
    """Our process IDs whose datasets can contain `stage`'s outputs: every entry point from
    plan_convert up to `stage` itself (organize never runs past itself)."""
    return [PROCESS_ID[s] for s in STAGES[1:STAGES.index(stage) + 1]]


# Everything before skull-stripping is PHI: DICOM headers, and faces in the image data itself.
PHI_ENTRIES = ("organize", "plan_convert", "convert", "preprocess")
PHI_CONFIRMATION = ("I confirm the input contains NO PHI: it is de-identified, face-free test data "
                    "(not real patient images)")
PHI_FORM_DESCRIPTION = (
    "PHI WARNING: this pipeline starts from data BEFORE skull-stripping (DICOM or whole-head "
    "NIfTI). Real patient data at this point contains PHI -- DICOM headers, and identifiable "
    "faces in the image data itself -- and must NOT be uploaded to Cirro. Use these entry points "
    "only with de-identified, face-free test data. For real patients, run stages up to "
    "preprocessing locally (see the astril-nf README), upload the face-free "
    "02-preprocess/upload_preprocessed/ folder, and start at 'astril - Run from preprocessed images'."
)

# ---- Per-stage form fields -------------------------------------------------------------------
# "always": shown whenever the stage is part of the run. "entry": only when the run STARTS at
# this stage (inputs that otherwise come from the upstream stage in the same run).

FIELDS = {
    "organize": {
        "always": {
            "organize_n_workers": {
                "type": "integer",
                "title": "Organize/plan: parallel workers",
                "description": "Threads for DICOM metadata reads/copies (I/O bound). Leave blank to use the task's allocated CPU count (recommended); set only to override.",
            },
        },
    },
    "plan_convert": {
        "entry": {
            "patient_metadata_dataset": {
                "type": "string",
                "title": "Filled-in patient metadata table",
                "description": "An uploaded dataset (type 'Tables (TSV/CSV)' or 'Files') containing exactly one .csv: the Organize step's patient_metadata_blank.csv after you've filled it in.",
                "pathType": "dataset",
                "process": ["table_csv_tsv", "custom_dataset"],
            },
        },
        "always": {
            "min_slices": {
                "type": "integer",
                "title": "Plan: minimum slices",
                "description": "Minimum slice count for a series to be considered a real 3D volume.",
                "default": 10,
            },
            "organize_n_workers": {
                "type": "integer",
                "title": "Organize/plan: parallel workers",
                "description": "Leave blank to use the task's allocated CPU count (recommended); set only to override.",
            },
        },
        "required_entry": ["patient_metadata_dataset"],
    },
    "convert": {
        "entry": {
            "organized_dataset": {
                "type": "string",
                "title": "Organized DICOM dataset",
                "description": "The 'astril - Organize DICOM' dataset the selected conversion plan was generated from.",
                "pathType": "dataset",
                "process": [PROCESS_ID["organize"]],
            },
            "edited_plan_dataset": {
                "type": "string",
                "title": "Edited conversion plan (optional)",
                "description": "Leave blank to convert using the input dataset's plan as-is. To use a hand-edited plan instead, upload it (type 'Tables (TSV/CSV)' or 'Files', exactly one .csv) and select it here. Edit rows/selections only -- keep the folder/path columns unchanged so they can be re-pointed at this run's copies.",
                "pathType": "dataset",
                "process": ["table_csv_tsv", "custom_dataset"],
            },
        },
        "always": {
            "convert_n_workers": {
                "type": "integer",
                "title": "Convert: parallel workers",
                "description": "Leave blank to use the task's allocated CPU count (recommended); set only to override.",
            },
            "convert_overwrite": {
                "type": "boolean",
                "title": "Convert: overwrite existing NIfTI outputs",
                "default": False,
            },
        },
        "required_entry": ["organized_dataset"],
    },
    "preprocess": {
        "always": {
            "prior_preprocessed_dataset": {
                "type": "string",
                "title": "Preprocess: prior preprocessed library (optional, test data only)",
                "description": "Leave blank for a first-time run. To add new exams to an existing library without changing any patient's reference space, select the dataset of an earlier run that preprocessed it (its coreg log pins each patient's reference), AND select the earlier NIfTI inputs that library was built from below -- every exam is re-preprocessed together. NIfTI is PHI for real patients, so incremental preprocessing of real data is done locally.",
                "pathType": "dataset",
                "process": produced_by("preprocess"),
            },
            "prior_nifti_pipeline_datasets": {
                "type": "string",
                "title": "Preprocess: earlier NIfTI from astril-nf runs (with a prior library)",
                "description": "Datasets of earlier astril-nf runs whose converted NIfTI (01b-convert/nifti_out) the prior library was built from.",
                "pathType": "dataset",
                "process": produced_by("convert"),
                "multiple": True,
            },
            "prior_nifti_upload_datasets": {
                "type": "string",
                "title": "Preprocess: earlier NIfTI uploads (with a prior library)",
                "description": "Uploaded NIfTI datasets ({patient}/{exam}/... at the top level) the prior library was built from.",
                "pathType": "dataset",
                "process": ["custom_dataset"],
                "multiple": True,
            },
            "preprocess_n_workers": {
                "type": "integer",
                "title": "Preprocess: parallel workers",
                "description": "Exam-level parallelism within this run. Also sets the compute request: this many CPUs, and this many x 'Memory per worker' GB, unless 'Total memory override' is set. The default (14 workers x 4 GB = 56 GB) fits a g5.4xlarge (16 vCPU / 64 GiB); going above that moves the task to a larger, more expensive instance.",
                "default": 14,
            },
            "preprocess_memory_gb_per_worker": {
                "type": "integer",
                "title": "Preprocess: memory per worker (GB)",
                "description": "astril doesn't budget memory itself -- this is a starting heuristic, not a measured figure. Tune against your own data if runs OOM-kill (exit 137) or over-provision.",
                "default": 4,
            },
            "preprocess_memory_gb": {
                "type": "integer",
                "title": "Preprocess: total memory override (GB)",
                "description": "Leave blank to auto-compute as parallel workers x memory per worker. If set too low for the worker count, a warning is logged before the run starts.",
            },
            "anchor_label": {
                "type": "string",
                "title": "Preprocess: anchor modality",
                "description": "Modality co-registration and skull-stripping are anchored to.",
                "default": "T1c",
            },
            "registration_strategy": {
                "type": "string",
                "title": "Preprocess: registration strategy",
                "enum": ["fast", "medium", "accurate"],
                "default": "medium",
            },
            "normalization_method": {
                "type": "string",
                "title": "Preprocess: intensity normalization method",
                "enum": ["robust_zscore", "zscore"],
                "default": "robust_zscore",
            },
            "final_dims": {
                "type": "string",
                "title": "Preprocess: final voxel grid (NX,NY,NZ)",
                "default": "240,240,155",
            },
            "final_voxels": {
                "type": "string",
                "title": "Preprocess: final voxel spacing mm (SX,SY,SZ)",
                "default": "1.0,1.0,1.0",
            },
            "use_gpu": {
                "type": "boolean",
                "title": "Preprocess: use GPU for skull-stripping (HD-BET)",
                "default": True,
            },
            "enable_tta": {
                "type": "boolean",
                "title": "Preprocess: enable HD-BET test-time augmentation",
                "description": "Improves mask quality; recommended when GPU is available.",
                "default": True,
            },
            "generate_qc": {
                "type": "boolean",
                "title": "Preprocess: generate QC PDFs",
                "default": True,
            },
            "preprocess_overwrite": {
                "type": "boolean",
                "title": "Preprocess: overwrite existing preprocessed outputs",
                "default": False,
            },
        },
    },
    "segment": {
        "always": {
            "model_dataset": {
                "type": "string",
                "title": "Segment: custom model (optional)",
                "description": "Leave blank to use 'Model family' below. To run a self-trained model not published through astril's model manifest, upload its directory (its pipeline.json plus checkpoints) as a 'Files' dataset and select it here -- it then takes precedence over 'Model family'.",
                "pathType": "dataset",
                "process": ["custom_dataset"],
            },
            "model_family": {
                "type": "string",
                "title": "Segment: model family",
                "description": "A model family registered in astril's models.json. Ignored if a custom model is selected above. This dropdown is a static list, not a live registry lookup -- add a new family here by hand when one is added to astril's models.json.",
                "enum": ["GBM_seg_v2"],
                "default": "GBM_seg_v2",
            },
            "slice_batch_size": {
                "type": "integer",
                "title": "Segment: slice batch size",
                "description": "Memory/throughput tradeoff for 2.5D inference.",
                "default": 1,
            },
            "brainmask_pattern": {
                "type": "string",
                "title": "Segment: brainmask filename pattern",
                "default": "_brainmask.nii.gz",
            },
            "segment_overwrite": {
                "type": "boolean",
                "title": "Segment: overwrite existing segmentation outputs",
                "default": False,
            },
        },
    },
    "quantify": {
        "always": {
            "seg_filename_pattern": {
                "type": "string",
                "title": "Segmentation filename pattern",
                "description": "Suffix segmentation writes, and quantify looks for.",
                "default": "_GBM-seg.nii.gz",
            },
            "labels_json_dataset": {
                "type": "string",
                "title": "Quantify: labels contract (optional)",
                "description": "Rarely needed: masks produced by this pipeline's segmentation carry their labels in a segmentation_provenance.json sidecar. Needed only for masks without one (e.g. produced elsewhere) when 'Number of segmentation levels' isn't set: upload a labels.json ({\"labels\": {\"1\": \"...\", ...}}) as a 'Files' dataset (exactly one .json) and select it here.",
                "pathType": "dataset",
                "process": ["custom_dataset"],
            },
            "quantify_n_threads": {
                "type": "integer",
                "title": "Quantify: threads",
                "description": "File I/O parallelism across the whole run. Leave blank to use the task's allocated CPU count (recommended); set only to override.",
            },
        },
        "entry": {
            "total_levels": {
                "type": "integer",
                "title": "Quantify: number of segmentation levels (optional)",
                "description": "Levels 1..N, generically named. Not needed if 'Labels contract' is set, or if the masks carry a segmentation_provenance.json sidecar (this pipeline's segmentation output does). One of the three is required.",
            },
            "merge_before_quantify": {
                "type": "boolean",
                "title": "Quantify: merge multiple segmentation sources first",
                "description": "Enable if supplying more than one segmentation per exam (e.g. model output plus a manual correction).",
                "default": False,
            },
            "merge_input_patterns": {
                "type": "string",
                "title": "Quantify: merge input patterns (comma-separated, priority order)",
                "description": "Required if merging; e.g. '_GBM-seg.nii.gz,_manual-seg.nii.gz'.",
            },
            "merge_output_pattern": {
                "type": "string",
                "title": "Quantify: merged output filename pattern",
                "default": "_merged-seg.nii.gz",
            },
        },
    },
}

# Input dataset -> param mapping for each entry point. Entries whose input may be either one of
# our own datasets (outputs under a stage subfolder) or a direct upload (top level) map the root
# here and let preprocess.py append ENTRY_INPUT_SUBDIR when the input came from our pipelines.
ENTRY_INPUTS = {
    "organize": {"dicom_dir": "$.inputs[0].dataPath"},
    "plan_convert": {
        "organized_dir": "$.inputs[0].dataPath|/00-organize/organized_dicoms",
        "dicom_index": "$.inputs[0].dataPath|/00-organize/dicom_index.csv",
        "organized_dir_root": "$.inputs[0].dataPath|/00-organize/organized_dicoms_root.txt",
    },
    "convert": {
        "conversion_plan": "$.inputs[0].dataPath|/01a-plan-conversion/conversion_plan.csv",
        "organized_dir_root": "$.inputs[0].dataPath|/01a-plan-conversion/organized_dicoms_root.txt",
        "nifti_dir_root": "$.inputs[0].dataPath|/01a-plan-conversion/nifti_root.txt",
        "organized_dir": "$.dataset.params.organized_dataset|/data/00-organize/organized_dicoms",
    },
    "preprocess": {"nifti_dir": "$.inputs[0].dataPath"},
    "segment": {"preprocessed_dir": "$.inputs[0].dataPath"},
    "quantify": {"seg_dir": "$.inputs[0].dataPath"},
}
# Form fields consumed by an ENTRY_INPUTS mapping rather than passed through as their own param.
MAPPED_ONLY_FIELDS = {"organized_dataset"}

COMPUTE_CONFIG = """\
// Generated by scripts/build_cirro_configs.py -- edit there, not here. Identical in every
// .cirro/<stage>/ folder: each entry point can run every later stage, and withName selectors
// only affect the processes a given run actually has.
process {
    errorStrategy = 'retry'
    maxRetries = 2

    // CPU-only stages (organize, plan, convert, library merge, QC, export).
    cpus = 4
    memory = 8.GB

    // No cpus/memory here deliberately: PREPROCESS_LIBRARY's cpus and memory are DERIVED from
    // the form fields preprocess_n_workers / preprocess_memory_gb_per_worker /
    // preprocess_memory_gb (see conf/gpu.config) so a user's worker-count choice always gets
    // proportional memory. Setting static cpus/memory here would override that formula. The
    // form's default (14 workers x 4 GB = 56 GB) fits a g5.4xlarge (16 vCPU / 64 GiB) with
    // headroom for AWS Batch's own per-instance memory reservation.
    withName: 'PREPROCESS_LIBRARY' {
        accelerator = 1
        // conf/gpu.config only adds --shm-size when Nextflow's container engine is 'docker',
        // which isn't the case under Cirro's AWS Batch executor -- set it explicitly here.
        // Nextflow translates --shm-size into the Batch job's sharedMemorySize (other docker
        // flags such as --gpus are silently ignored on Batch; `accelerator` requests the GPU).
        // A closure, not a plain GString: this overlay file is parsed before the pipeline's own
        // params are bound, so an eager "${params.docker_shm_size}" resolves to "null" here.
        containerOptions = { "--shm-size=${params.docker_shm_size}" }
        // One long, whole-library task: run on-demand rather than spot, so an interruption
        // can't throw away hours of registration/skull-stripping.
        queue = env('PW_ONDEMAND_JOB_QUEUE')
    }

    // GBM_seg_v2 loads up to 6 models simultaneously (2 stages x 3 planes) -- easily fits one
    // A10G's 24 GB. 4 vCPU / 14 GB fits a g5.xlarge (4 vCPU / 16 GiB) once AWS Batch's own
    // per-instance memory reservation is accounted for.
    //
    // maxForks explicitly raised: conf/gpu.config sets maxForks=1 as a LOCAL safeguard (one
    // shared workstation GPU). Each Batch task gets its own GPU instance, and Nextflow merges
    // config per-directive, so omitting maxForks here would NOT reset the local limit. Tune to
    // the number of concurrent GPU Batch jobs your project's GPU quota supports.
    withName: 'SEGMENT_GBM' {
        accelerator = 1
        cpus = 4
        memory = 14.GB
        maxForks = 10
        // --shm-size has to be set explicitly under AWS Batch (see PREPROCESS_LIBRARY above).
        // Kept below this task's memory request.
        containerOptions = '--shm-size=8g'
    }

    withName: 'QUANTIFY_VOLUMES|MERGE_SEG_VOLUMES' {
        cpus = 2
        memory = 4.GB
    }
}
"""

PROCESS_OUTPUT = {
    "commands": [
        {
            "command": "hot.Parquet",
            "params": {
                "desc": "Segmentation volumes (mm3), one row per segmentation file. Columns are named from the segmenting model's own labels (declared in the model's pipeline.json, carried through astril's segmentation_provenance.json sidecar) -- this list matches GBM_seg_v2, today's only available model. A manually edited mask (no provenance sidecar) or a future model family can add columns not listed here; they still appear in 03b-quantify/volumes.tsv.",
                "name": "Segmentation Volumes",
                "source": "$data_directory/03b-quantify/volumes.tsv",
                "target": "volumes.parquet",
                "url": "",
                "read_csv": {"parse": {"delimiter": "\t"}},
                "cols": [
                    {"col": "File_path", "name": "File path", "desc": "Full path to the segmentation file this row was computed from"},
                    {"col": "File_name", "name": "File name", "desc": "Segmentation file name"},
                    {"col": "necrosis_non_enhancing_tumor_Volume_mm3", "name": "Necrosis / non-enhancing tumor volume (mm3)", "desc": "GBM_seg_v2 label 1"},
                    {"col": "edema_non_flair_hyperintensity_Volume_mm3", "name": "Edema volume (mm3)", "desc": "GBM_seg_v2 label 2: edema / surrounding non-FLAIR hyperintensity"},
                    {"col": "enhancing_tumor_tissue_Volume_mm3", "name": "Enhancing tumor volume (mm3)", "desc": "GBM_seg_v2 label 3: enhancing tumor / tissue"},
                    {"col": "resection_cavity_Volume_mm3", "name": "Resection cavity volume (mm3)", "desc": "GBM_seg_v2 label 4: resection cavity"},
                ],
            },
        },
        {"command": "hot.Manifest", "params": {}},
    ]
}


def build_form(entry):
    stages = [entry] if entry == "organize" else STAGES[STAGES.index(entry):]
    props, required = {}, []
    if entry in PHI_ENTRIES:
        props["phi_confirmation"] = {
            "type": "string",
            "title": "PHI check (required)",
            "description": "Data from before skull-stripping must never be real patient data on Cirro. Select to confirm.",
            "enum": [PHI_CONFIRMATION],
        }
        required.append("phi_confirmation")
    # Order: PHI check, this entry point's own inputs, "Stop after", then each stage's settings.
    props.update(FIELDS[entry].get("entry", {}))
    required += FIELDS[entry].get("required_entry", [])
    if entry not in ("organize", "quantify"):  # single-stage entry points: nothing to stop early
        later = STAGES[STAGES.index(entry):]
        props["stop_after"] = {
            "type": "string",
            "title": "Stop after",
            "description": "Every stage from this pipeline's starting point runs in one go, through quantification by default. Stop earlier to review or edit an intermediate result (e.g. the conversion plan, or masks before quantifying), then continue from that dataset with the matching 'Run from ...' pipeline.",
            "enum": later,
            "enumNames": [STAGE_TITLE[s] for s in later],
            "default": "quantify",
        }
    for s in stages:
        for k, v in FIELDS[s].get("always", {}).items():
            props.setdefault(k, v)
    form = {"type": "object", "properties": props}
    if entry in PHI_ENTRIES:
        form["description"] = PHI_FORM_DESCRIPTION
    if required:
        form["required"] = required
    return {"ui": {}, "form": form}


def build_input(entry, form):
    mapping = {"stage": entry, "outdir": "$.dataset.dataPath"}
    mapping.update(ENTRY_INPUTS[entry])
    for k in form["form"]["properties"]:
        if k not in MAPPED_ONLY_FIELDS:
            mapping[k] = f"$.dataset.params.{k}"
    return mapping


PREPROCESS_TEMPLATE = '''\
#!/usr/bin/env python3
"""Cirro pre-run staging for the astril-nf entry point that starts at '{entry}'.

Generated by scripts/build_cirro_configs.py -- edit there, not here. Every .cirro/<stage>/
preprocess.py is this same script; only ENTRY_STAGE differs.

Resolves what process-input.json can't map statically:
- PHI gate (entry points before skull-stripping): refuse to run unless the form's PHI
  confirmation was given.
- Where the input data sits: one of this pipeline's own datasets keeps each stage's output in a
  stage subfolder; a direct upload has it at the top level. Decided by the input dataset's own
  process id -- an explicit fact Cirro records, not a guess from the files.
- Face-free guard (entry points from preprocessed images onward): refuse input that contains
  anything that may hold un-skull-stripped images.
- Dataset pickers -> concrete file paths.
"""
from urllib.parse import urlparse

import boto3
from cirro.helpers.preprocess_dataset import PreprocessDataset

ENTRY_STAGE = {entry!r}
PHI_CONFIRMATION = {phi_confirmation!r}
PHI_ENTRIES = {phi_entries!r}
OUR_PROCESS_PREFIX = "process-astril-"
# Entry stage -> (param holding the input dataset root, subfolder holding that stage's input
# inside one of our own datasets). The segment entry reads the face-free export, never the full
# preprocessed_library (which also holds logs with absolute paths).
ENTRY_INPUT_SUBDIR = {{
    "preprocess": ("nifti_dir", "01b-convert/nifti_out"),
    "segment": ("preprocessed_dir", "02-preprocess/upload_preprocessed"),
    "quantify": ("seg_dir", "03-segment"),
}}
FACE_FREE_ENTRIES = {{"segment", "quantify"}}
# Path components that may hold un-skull-stripped (face-containing) images: the raw-input copy
# kept by astril-nf < 0.2.0 libraries, astril's opt-in skull-on outputs, and its scratch dirs.
UNSAFE_DIR_NAMES = {{"_raw_passthrough", "with-skulls", "temp_preprocessing"}}
UNSAFE_DIR_PREFIXES = (".astril_tmp_", "astril_tmp_")


def _data_root(dataset_uri: str) -> str:
    # Dataset pickers return the dataset's root; its files live under `data/`.
    root = dataset_uri.rstrip("/")
    return root if root.endswith("/data") else f"{{root}}/data"


def _list_files(prefix_uri: str) -> list[str]:
    parsed = urlparse(prefix_uri.rstrip("/") + "/")
    bucket, prefix = parsed.netloc, parsed.path.lstrip("/")
    paginator = boto3.client("s3").get_paginator("list_objects_v2")
    return [
        f"s3://{{bucket}}/{{obj['Key']}}"
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
    ]


def _find_single(dataset_uri: str, suffix: str, what: str) -> str:
    matches = [f for f in _list_files(_data_root(dataset_uri)) if f.lower().endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {{suffix}} file in the selected {{what}} dataset, found "
            f"{{len(matches)}}: {{matches[:10]}}"
        )
    return matches[0]


def _check_face_free(input_dir: str, ds: PreprocessDataset) -> None:
    root = input_dir.rstrip("/") + "/"
    unsafe = []
    for f in _list_files(root):
        parts = f[len(root):].split("/")[:-1]
        if any(p in UNSAFE_DIR_NAMES or p.startswith(UNSAFE_DIR_PREFIXES) for p in parts):
            unsafe.append(f)
    if unsafe:
        raise ValueError(
            "PHI RISK: the input dataset contains folders that may hold un-skull-stripped "
            f"(face-containing) images, e.g. {{unsafe[:5]}}. Only upload the face-free "
            "02-preprocess/upload_preprocessed/ folder written by local preprocessing. Delete "
            "this dataset from Cirro and report it per your institution's PHI policy."
        )
    ds.logger.info(f"Face-free check passed for {{root}}")


def _pick(ds, form_key, param, resolve, what):
    picked = ds.params.get(form_key)
    if picked:
        value = resolve(picked)
        ds.logger.info(f"Using {{what}}: {{value}}")
        ds.add_param(param, value, overwrite=True)
    ds.remove_param(form_key, force=True)


def _picked_list(value) -> list[str]:
    # A multi-select dataset picker may arrive as a list or a comma-separated string.
    if not value:
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    return [str(v).strip() for v in items if str(v).strip()]


def _resolve_prior_nifti(ds) -> None:
    # Which folder holds the NIfTI is explicit from which picker it came through: astril-nf
    # datasets keep it under 01b-convert/nifti_out, uploads at their top level.
    dirs = [_data_root(d) + "/01b-convert/nifti_out" for d in _picked_list(ds.params.get("prior_nifti_pipeline_datasets"))]
    dirs += [_data_root(d) for d in _picked_list(ds.params.get("prior_nifti_upload_datasets"))]
    if dirs:
        ds.logger.info(f"Earlier NIfTI inputs for the incremental run: {{dirs}}")
        ds.add_param("prior_nifti_dirs", ",".join(dirs), overwrite=True)
    ds.remove_param("prior_nifti_pipeline_datasets", force=True)
    ds.remove_param("prior_nifti_upload_datasets", force=True)


def run(ds: PreprocessDataset):
    # Separate from main() so it can also be exercised against real project datasets from
    # outside Cirro via the SDK's DataPortal().developer_helper.generate_preprocess_for_input_datasets().
    if ENTRY_STAGE in PHI_ENTRIES:
        if ds.params.get("phi_confirmation") != PHI_CONFIRMATION:
            raise ValueError(
                "This entry point takes data from before skull-stripping, which for real patients "
                "is PHI. Confirm the input is de-identified, face-free test data (form field "
                "'PHI check') to run it."
            )
        ds.remove_param("phi_confirmation", force=True)

    if ENTRY_STAGE in ENTRY_INPUT_SUBDIR:
        param, subdir = ENTRY_INPUT_SUBDIR[ENTRY_STAGE]
        parent = ds.metadata["inputs"][0]["processId"]
        if parent.startswith(OUR_PROCESS_PREFIX):
            path = ds.params[param].rstrip("/") + "/" + subdir
            ds.logger.info(f"Input is an astril-nf dataset ({{parent}}); {{param}} = {{path}}")
            ds.add_param(param, path, overwrite=True)
        else:
            ds.logger.info(f"Input is a direct upload ({{parent}}); {{param}} = dataset top level")
        if ENTRY_STAGE in FACE_FREE_ENTRIES:
            _check_face_free(ds.params[param], ds)

    _pick(ds, "patient_metadata_dataset", "patient_metadata",
          lambda d: _find_single(d, ".csv", "patient metadata"), "patient metadata table")
    _pick(ds, "edited_plan_dataset", "conversion_plan",
          lambda d: _find_single(d, ".csv", "edited conversion plan"), "edited conversion plan")
    _pick(ds, "prior_preprocessed_dataset", "prior_preprocessed_dir",
          lambda d: _data_root(d) + "/02-preprocess/preprocessed_library", "prior preprocessed library")
    _resolve_prior_nifti(ds)
    _pick(ds, "model_dataset", "model_dir",
          lambda d: _find_single(d, "/pipeline.json", "custom model").rsplit("/", 1)[0], "custom model")
    _pick(ds, "labels_json_dataset", "labels_json",
          lambda d: _find_single(d, ".json", "labels contract"), "labels contract")


def main():
    run(PreprocessDataset.from_running())


if __name__ == "__main__":
    main()
'''


def build_all():
    files = {}
    for entry in STAGES:
        folder = CIRRO_DIR / FOLDER[entry]
        form = build_form(entry)
        files[folder / "process-form.json"] = json.dumps(form, indent=2) + "\n"
        files[folder / "process-input.json"] = json.dumps(build_input(entry, form), indent=2) + "\n"
        files[folder / "preprocess.py"] = PREPROCESS_TEMPLATE.format(
            entry=entry, phi_confirmation=PHI_CONFIRMATION, phi_entries=PHI_ENTRIES)
        files[folder / "process-compute.config"] = COMPUTE_CONFIG
        if entry != "organize":
            files[folder / "process-output.json"] = json.dumps(PROCESS_OUTPUT, indent=2) + "\n"
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit non-zero if any generated file is out of date")
    args = ap.parse_args()
    stale = []
    for path, content in build_all().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != content:
            stale.append(path.relative_to(REPO_ROOT).as_posix())
            if not args.check:
                path.write_text(content, encoding="utf-8", newline="\n")
    if args.check:
        if stale:
            sys.exit("Out of date (run scripts/build_cirro_configs.py): " + ", ".join(stale))
        print("All generated Cirro configs are up to date.")
    else:
        print("\n".join(f"wrote {p}" for p in stale) or "Nothing to change.")


if __name__ == "__main__":
    main()
