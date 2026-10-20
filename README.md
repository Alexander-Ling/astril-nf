# astril-nf

A Nextflow wrapper around [astril](https://github.com/Alexander-Ling/astril)'s DICOM ingestion, MRI
preprocessing, and GBM segmentation, for local runs and for [Cirro](https://cirro.bio). **Model
training is explicitly out of scope** -- this pipeline covers astril's preprocessing and
segmentation functionality only.

> **PHI: everything before skull-stripping is identifiable.** Raw DICOM, the organize/plan
> outputs, and converted NIfTI all contain PHI -- DICOM headers, and faces in the image data
> itself. Run Stages 0-2 **locally** on real patient data, and take only the face-free
> `02-preprocess/upload_preprocessed/` folder off-site (e.g. to Cirro, starting at
> "Run from preprocessed images"). The DICOM/NIfTI entry points exist on Cirro for completeness
> and must only be used with de-identified, face-free test data. See "PHI and what is safe to
> upload" below.

Every Nextflow process here is a thin wrapper around astril's existing console scripts
(`organize_dicoms`, `preprocess_brain_mris`, `segment`, `quantify-volumes`, etc.). Stage 3a uses
astril's generic, contract-driven `segment` CLI (reads the selected model's own `pipeline.json`)
rather than the older `segment-gbm`, which hardcoded GBM_seg_v2's specific cascade in Python --
see "Model provenance and level labels" below.

## Stages

| Stage | `--stage` value | What it does |
|---|---|---|
| 0. Organize | `organize` | Route an arbitrary DICOM library into astril's structured `Patient/Exam/Series` tree; generate a blank per-patient metadata table for you to fill in. |
| 1a. Plan conversion | `plan_convert` | Classify DICOM series and propose an editable DICOM→NIfTI conversion plan, using your filled-in metadata table. **Review/edit the plan before Stage 1b.** |
| 1b. Convert | `convert` | Execute the (optionally edited) plan, producing the NIfTI library. |
| 2. Preprocess | `preprocess` | Co-register, skull-strip (HD-BET), and normalize a NIfTI library, via ONE `preprocess_brain_mris` call over the whole (merged) library -- astril itself selects every patient's reference before fanning out per exam internally (`--n_workers`), so Nextflow doesn't re-implement that. Supports incrementally merging new exams into an existing preprocessed library without changing a patient's already-assigned reference space. QC PDFs are an optional extra output. |
| 3a. Segment | `segment` | Segmentation inference via a selected model (`--model_family GBM_seg_v2` by default, or `--model_dir` for a self-trained model), one Nextflow task per PATIENT (all of that patient's exams in one call, since the model's own pipeline loads its models once per invocation regardless of exam count -- fanning out per exam would reload them per exam for no benefit). Writes a `segmentation_provenance.json` sidecar next to each exam's output recording the model's identity and label meanings. |
| 3b. Quantify | `quantify` | Per-class segmentation volumes (mm³) for the whole segmentation tree in ONE `quantify-volumes` call, aggregated directly into one table (not fanned out per exam -- see Multi-threading below). Which levels to quantify comes from an explicit contract: `total_levels`, `labels_json`, or (automatically) each file's own `segmentation_provenance.json` sidecar from Stage 3a. Starting a run here (`--stage quantify --seg_dir ...`) quantifies a manually corrected/replacement set of masks, with an optional merge-multiple-sources step first. |

## One run, many stages: `--stage` and `--stop_after`

`--stage` is where a run **starts**; it then runs every later stage in the same invocation, each
handing its output straight to the next, through `--stop_after` (default: `quantify`). Every
stage still publishes its outputs under its own `NN-<stage>/` folder, so each one is a checkpoint
a later run can start from. The usual flow needs only one stop:

1. `--stage organize` -- always stops here: fill in `00-organize/patient_metadata_blank.csv`.
2. `--stage plan_convert ...` -- plans, converts, preprocesses, segments and quantifies.

Stop earlier to intervene by hand, then start the next run at the matching stage:

| To... | Stop with | Then start the next run with |
|---|---|---|
| review/edit the conversion plan | `--stop_after plan_convert` | `--stage convert --conversion_plan <edited.csv>` |
| take face-free data off-site (see PHI below) | `--stop_after preprocess` | `--stage segment --preprocessed_dir <upload_preprocessed>` |
| correct masks by hand before quantifying | `--stop_after segment` | `--stage quantify --seg_dir <corrected masks>` |

`--merge_before_quantify` only applies to runs starting at `quantify` (it overlays several mask
sources for an already-fixed set of exams), and is rejected otherwise.

## Starting from your own data

Stages 2, 3a, and 3b also accept a direct upload that follows astril's directory/file-naming
conventions for that boundary, not just this pipeline's own output. The patient folders must sit
at the top level of the upload (or of `--nifti_dir`/`--preprocessed_dir`/`--seg_dir` when running
locally), not inside an extra wrapper folder:

- **Stage 2 (preprocess):** NIfTI library, `{patient}/{exam}/{label}.nii.gz` -- **PHI** (faces)
- **Stage 3a (segment):** preprocessed NIfTI library, `{patient}/{exam}/..._brain-norm.nii.gz` +
  `..._brainmask.nii.gz` -- normally the face-free `02-preprocess/upload_preprocessed/` folder
- **Stage 3b (quantify):** segmentation masks, `{patient}/{exam}/..._GBM-seg.nii.gz`
  (or a flat collection of exam dirs -- depth is auto-detected, see `subworkflows/local/utils.nf`).
  This is the entry point for manually corrected or externally produced masks.

Stages 1a and 1b only run on this pipeline's own upstream output (Stage 0's organized DICOM tree
and index; Stage 1a's plan), since their absolute-path bookkeeping is specific to it -- though
Stage 1b accepts a hand-edited copy of Stage 1a's plan. Only Stage 0 has to tolerate genuinely
arbitrary input structure.

## PHI and what is safe to upload

Everything before skull-stripping is PHI for real patients: raw DICOM (headers), the organize and
plan outputs, and converted NIfTI (identifiable faces in the image data, even after astril's
sidecar scrubbing). Stage 2's full output, `02-preprocess/preprocessed_library/`, holds only
skull-stripped images, but its logs and transform records contain absolute local paths, so it
isn't the thing to upload either. (Libraries built by astril-nf before 0.2.0 also contain
`_raw_passthrough/`, a whole-head copy of the raw input: never upload those.)

Stage 2 therefore also writes `02-preprocess/upload_preprocessed/`: an allowlisted copy holding
only `{patient}/{exam}/` files ending in `_brain-norm.nii.gz`, `_brain.nii.gz` or
`_brainmask.nii.gz` -- all masked by astril's skull-stripping, and everything Stage 3a needs
(`modules/local/export_face_free_library`). Upload that folder, and nothing else from before it.
Chained runs segment from this same export, so local and Cirro runs exercise exactly the files
you'd upload. Patient and exam folder names come from your metadata table, so use
non-identifying patient IDs there.

On Cirro, every entry point before "Run from preprocessed images" requires a PHI confirmation in
its form and is labelled "test data only"; "Run from preprocessed images" and "Quantify
segmentation masks" refuse inputs containing `_raw_passthrough/`, `with-skulls/`,
`temp_preprocessing/` or astril scratch folders. Incremental preprocessing re-preprocesses the
earlier raw NIfTI alongside the new exams (see below), so for real patient data it is local-only.

No stage copies its inputs into its outputs: each stage publishes only what it produced, and a
later run is pointed back at the earlier datasets it needs (on Cirro, by selecting them).

## Running locally (outside Cirro)

```
# Stage 0, then fill in results/00-organize/patient_metadata_blank.csv
nextflow run main.nf -profile docker --stage organize --dicom_dir /path/to/raw_dicom --outdir results

# Plan -> convert -> preprocess, stopping before anything leaves the machine
nextflow run main.nf -profile docker --stage plan_convert --stop_after preprocess \
    --organized_dir results/00-organize/organized_dicoms \
    --dicom_index results/00-organize/dicom_index.csv \
    --organized_dir_root results/00-organize/organized_dicoms_root.txt \
    --patient_metadata patient_metadata_filled.csv --outdir results
# -> upload results/02-preprocess/upload_preprocessed/ to Cirro ("Run from preprocessed images"),
#    or continue locally with --stage segment --preprocessed_dir results/02-preprocess/upload_preprocessed
```
Add `-profile docker,test` for small machines (fewer workers, CPU-only HD-BET).

Every process runs in `params.container` (default: the published
`ghcr.io/alexander-ling/astril-nf:<version>` image); pass `--container astril-nf:test` to use a
locally built image instead.

See `nextflow.config` for the full parameter list per stage. GPU wiring is applied per process,
not per profile: `conf/gpu.config` gives every `gpu`-labeled process (`PREPROCESS_LIBRARY`,
`SEGMENT_GBM`) its accelerator request, `--gpus all --shm-size=...` under Docker, and resource
sizing. `-profile gpu` is kept only as a no-op so existing `-profile docker,gpu` commands still work.

## Multi-threading

Two independent layers of parallelism, deliberately kept from fighting each other:

- **Nextflow task fan-out** -- one task per PATIENT for Stage 3a (all of that patient's exams in
  one `segment` call, since the selected model's pipeline loads its models once per invocation
  regardless of exam count -- see the Stage 3a note below), one task per EXAM for Stage 3b's
  optional standalone pre-merge step only (`merge_before_quantify`), or none at all for Stages
  0/1a/1b/2/QC/3b's actual quantify call (each runs as a single task over the whole
  library/plan/tree, since astril's own functions there aren't structured to be split across
  tasks -- and for Stage 3b specifically, splitting it would break applying one consistent level
  contract across the whole batch, see the Stage 3b note below).
- **astril's own internal threading** (`--n_workers`/`--number_of_threads`/`--n_threads`), used
  *within* a task. For the whole-library stages this defaults to `task.cpus` (override via
  `organize_n_workers`/`convert_n_workers`/`preprocess_n_workers`/`quantify_n_threads`), so
  astril is never asked for more workers than the task's resource label actually allocates it.

**Stage 2 in particular is one task running `preprocess_brain_mris` over the whole merged
library**, not fanned out per patient or per exam by Nextflow. `preprocess_library()` already
does exam-level fan-out internally (via `--n_workers`) *after* selecting every patient's
registration reference and precomputing each patient's shared brainmask (one batched HD-BET call
across all patients needing one) -- and it already auto-budgets nested SimpleITK/HD-BET thread
counts per worker to avoid CPU oversubscription. Re-implementing any of that at the Nextflow
level would just duplicate logic astril already gets right, while forcing a dependency on
astril's *private* reference-selection functions instead of its public CLI. The tradeoff: the
whole library's preprocessing runs on one instance/task -- it doesn't scale out across multiple
Cirro/Batch instances the way per-exam fan-out would.

Unlike the other stages, **`preprocess_n_workers` is the primary knob here and drives this
stage's compute allocation directly** (not the other way around), because astril auto-budgets
*CPU thread counts* per worker but has no equivalent for memory:
- `cpus` = `preprocess_n_workers`
- `memory` = `preprocess_n_workers x preprocess_memory_gb_per_worker` GB (default 4 GB/worker --
  a starting heuristic, not a measured figure), or `preprocess_memory_gb` directly if you want to
  set the total yourself.

If you set `preprocess_memory_gb` manually and it looks low for the requested worker count, a
warning is logged before the run starts -- an OOM kill (exit 137) part-way through a real run is
a much more expensive way to discover the same mismatch. Size these the same way you'd size a
native `preprocess_brain_mris --n_workers N` call on a given machine.

**Stage 3a fans out per patient, not per exam**, for a different reason than Stage 2: astril's
`segment` engine loads every stage's models once per invocation (before the per-subject loop,
regardless of how many subjects that invocation finds), and recursively discovers every matching
exam under whatever directory it's given -- so passing one patient's whole directory (however
many exams it has) amortizes that model load across them, while a separate task per exam would
repeat it for no benefit. `SEGMENT_GBM` also sets `maxForks = 1` (see `conf/gpu.config`) as a
local-testing safeguard: this stage's per-patient tasks could otherwise run concurrently, and this
machine's single shared GPU can't serve several `segment` processes (each holding GBM_seg_v2's ~6
loaded models) at once without VRAM contention -- a real
Cirro/Batch deployment gives each task its own dedicated GPU instance, so
`.cirro/03-segment/process-compute.config` explicitly raises this back up.

**Stage 3b (quantify) runs as one task over the whole segmentation tree**, not fanned out per exam.
A single contract (an explicit `labels_json`, or the union of each file's own
`segmentation_provenance.json`, or `total_levels`) decides which levels every file in the batch
gets quantified against -- see "Model provenance and level labels" below. A per-exam Nextflow
task would only ever see that one file's own sidecar, forcing a separate merge step to reconcile
per-exam tables that could end up with different column sets -- so, like Stage 2, this is one
task, sized by `quantify_n_threads`/`task.cpus` the same way as the others. The one place per-exam
fan-out still applies is the *optional* `merge_before_quantify` pre-step (`MERGE_SEG_VOLUMES`),
which genuinely is independent per exam -- available only to runs starting at `--stage quantify`,
not the quantify that follows segmentation within a run (see "One run, many stages" above).
Within a run, `SEGMENT`'s per-patient output is collected into one list and handed to `QUANTIFY`
as a single whole-tree call, exactly as if you'd passed that same tree to `--stage quantify
--seg_dir ...` yourself.

## Model provenance and level labels (Stage 3a → Stage 3b)

Which segmentation levels `quantify-volumes` reports is always pinned down by an explicit
contract, **never inferred by scanning voxel data for whichever values happen to appear** -- that
would be fragile (data-dependent, and could silently drift from what the segmentation model was
actually designed to output). The contract comes from one of, in priority order:

1. an explicit `labels_json` contract file (`params.labels_json` / `--labels_json`),
2. each matched file's own `segmentation_provenance.json` sidecar -- written automatically by
   `segment` into each exam's output directory, recording which model produced it (its
   `pipeline.json`'s own declared `model_family`, `GBM_seg_v2` today) and that model's
   level->label mapping, sourced from the SAME `pipeline.json` contract that describes its
   inference stages (`src/astril/models/<family>/pipeline.json`, or a self-trained model's own
   directory via `--model_dir`) -- living alongside that model's own downloaded weights/README/
   CITATIONS, not shipped as astril package data (see `astril.model_labels`), or
3. `total_levels` (`params.total_levels` / `--total_levels`), a plain count with generic
   `SegmentN` column names.

One of these three must resolve to a non-empty level set, or `quantify-volumes` fails loudly
rather than silently producing an empty or wrong table. Whichever contract applies, every level
it declares is reported for every file, even at 0 mm³, rather than only whatever happens to be
present in a given exam -- so the output table always has a stable column set. The normal
Stage 3a → Stage 3b flow (whether auto-chained or standalone) needs no manual configuration at
all (the sidecar handles it); `labels_json` exists for entering Stage 3b directly with
segmentation masks that have no sidecar of their own.

Only one registered model family (`GBM_seg_v2`, `params.model_family`'s default) exists today, but
Stage 3a now runs astril's generic `segment` engine (see `astril.segment`/`astril.pipeline_contract`),
which drives ANY model from its own `pipeline.json` contract -- adding a second registered family
is just a new `models.json` entry plus that family's own `pipeline.json`, no new Python code,
*unless* it needs a genuinely different pipeline shape (a different derived-output op type, say),
which the contract schema doesn't cover yet. `params.model_dir` is the escape hatch for a
self-trained model that hasn't been (or won't be) published through astril's model manifest at
all: point it at that model's own directory (its own `pipeline.json` + checkpoints) and it runs
identically to a registered family, with no astril release or OSF upload needed first. Locally
that's a plain filesystem path; in Cirro it's the optional "Custom model" field on Stage 3a (a
"Files" upload containing `pipeline.json` + checkpoints -- see "Deploying in Cirro" below),
which takes precedence over the `model_family` dropdown when selected.

## Preprocessing merge / reference-space safety (Stage 2)

`preprocess_brain_mris` picks one shared registration reference per patient and can reuse a
previously-chosen one via `--old_coreg_log`. If that reference exam is missing from the current
run's input, astril's own default behavior is to **silently pick a new one** -- which would put a
patient's older and newer exams in different reference spaces. This pipeline refuses to do that.

To add exams to an existing library, pass the prior Stage 2 library as `--prior_preprocessed_dir`
(its coreg log pins each patient's reference) **and** the earlier raw NIfTI input(s) it was built
from as `--prior_nifti_dirs a,b,...`. `bin/merge_cumulative_nifti_library.py` unions those with
the new exams, every exam is re-preprocessed in the pinned reference spaces, and the run
hard-fails if a patient's logged reference exam isn't in the union, rather than letting astril
silently re-pick. On Cirro, the Stage 2 form has matching pickers (earlier NIfTI from astril-nf
runs, and earlier NIfTI uploads). Omit both for a first-time run.

## Docker image

`Dockerfile` builds one CUDA-capable image used by every stage (Cirro/Nextflow selects CPU vs.
GPU instance types per process), published as `ghcr.io/alexander-ling/astril-nf:<version>` on
GitHub Container Registry (public). astril is installed directly from GitHub, pinned to an exact commit
(`ASTRIL_GIT_REF` in the Dockerfile) so a given image tag always contains the same astril code.
Both the GBM model checkpoints (~1.8GB, via `astril-download-models`) and HD-BET's own pretrained
parameters (~0.5GB, from Zenodo) are downloaded at **build** time, not pipeline runtime. See the
Dockerfile's comments for why containers are *not* run as a remapped host UID
(`-u $(id -u):$(id -g)`) -- astril's own model cache resolution and HD-BET's weight cache are
both gated on the runtime user matching the build-time user.

GPU-labeled containers (`PREPROCESS_LIBRARY`, `SEGMENT_GBM`) also get `--shm-size` (default
16GB, `params.docker_shm_size`) beyond Docker's 64MB default -- PyTorch's multiprocessing (used
internally by nnU-Net/HD-BET's data loading) needs real shared memory once actual MRI volume
sizes are involved, and 64MB fails with `RuntimeError: unable to allocate shared memory(shm)...
No space left on device` deep inside a torch multiprocessing traceback (easy to miss the actual
cause under the `CalledProcessError` astril reports on top of it).

Build and publish with:
```
docker build -t ghcr.io/alexander-ling/astril-nf:0.2.0 .
docker push ghcr.io/alexander-ling/astril-nf:0.2.0
```
To pick up newer astril code, bump `ASTRIL_GIT_REF` and `ASTRIL_VERSION` in the Dockerfile (the
build fails if `ASTRIL_VERSION` doesn't match the installed astril), bump the image tag (here, in
`nextflow.config`'s `params.container` and `manifest.version`, and the Dockerfile's
`ASTRIL_NF_VERSION`), update the "Versions:" line at the end of each
`.cirro/*/process-definition.json` description, and rebuild. The image carries these as labels
(`org.opencontainers.image.version`, `io.github.alexander-ling.astril.version`,
`io.github.alexander-ling.astril.git-ref`; see `docker inspect`). `ASTRIL_CACHEBUST`
(`--build-arg ASTRIL_CACHEBUST=$(date +%s)`) forces the astril install and model downloads to
re-run without changing the ref -- Docker would otherwise cache those layers forever.

The image bundles third-party software and pretrained weights under their own licenses -- the
HD-BET and GBM_seg_v2 weights are both **non-commercial only**. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (also copied into the image at
`/licenses/astril-nf/`).

## Logs

Nextflow always captures every task's stdout/stderr automatically, but only inside its ephemeral
`work/<hash>/` directory (`.command.out`/`.command.err`/`.command.log`) -- not in the published
results, and not visible at all once this runs in Cirro (which only ever shows you a process's
declared outputs). Every process here also redirects astril's console output into a named,
published log file, so it's discoverable the same way regardless of environment:

| Stage | Log file(s) |
|---|---|
| 0. Organize | `00-organize/organize.log` |
| 1a. Plan conversion | `01a-plan-conversion/plan_generation.log` |
| 1b. Convert | `01b-convert/convert.log` |
| 2. Preprocess | `02-preprocess/_merge_library/merge_library.log` (the incremental-merge safety check), `02-preprocess/preprocess.log` (the whole-library `preprocess_brain_mris` call), `02-preprocess/qc/qc.log` |
| 3a. Segment | `03-segment/<patient>.segment.log` (one per patient task, alongside that patient's output folder) |
| 3b. Quantify | `03b-quantify/quantify.log` (the whole-tree `quantify-volumes` call), `03b-quantify/_merge_logs/<exam>.merge_seg.log` (one per exam, if `merge_before_quantify`) |

While a run is in progress, Nextflow's terminal output shows each task's work-directory hash
(e.g. `[e1/9f9e87]`) before it completes -- `tail -f work/e1/9f9e87*/.command.log` gives you a
live view without waiting for the task (or the whole run) to finish. On failure, Nextflow prints
the failing command, exit status, an error excerpt, and the work directory path directly to the
terminal, which is usually enough on its own; `bash work/<hash>/.command.run` re-runs the exact
same task in place for interactive debugging.

## Deploying in Cirro

Each Cirro custom pipeline is an **entry point**: it starts at one stage and runs every later
stage up to the form's "Stop after" choice (through quantification by default). All six point
at this repository and `main.nf`, each with its own configuration folder under `.cirro/`:

| Config folder | Process ID | Name in Cirro | Accepts input from |
|---|---|---|---|
| `.cirro/00-organize` | `process-astril-organize-1-0` | astril - Organize DICOM (de-identified test data only) | Files upload |
| `.cirro/01a-plan-conversion` | `process-astril-plan-conversion-1-0` | astril - Run from patient metadata (test data only) | Organize |
| `.cirro/01b-convert` | `process-astril-convert-1-0` | astril - Run from conversion plan (test data only) | Run from patient metadata |
| `.cirro/02-preprocess` | `process-astril-preprocess-1-0` | astril - Run from NIfTI (face-free test data only) | the two above, Files upload |
| `.cirro/03-segment` | `process-astril-segment-1-0` | **astril - Run from preprocessed images** (normal entry point for real data) | the three above, Files upload |
| `.cirro/03b-quantify` | `process-astril-quantify-1-0` | astril - Quantify segmentation masks | the four above, Files upload |

Process IDs can't be changed after creation (each names the stage its pipeline starts at), and
the `preprocess.py` scripts and dataset pickers refer to them.

**Registering and updating.** `scripts/register_cirro_pipelines.py` creates or updates all six
from their `process-definition.json` (name, description, input processes, upload guidance) via
the Cirro SDK, then syncs each one so Cirro re-reads its config folder from GitHub. Dry run by
default; `--apply` writes; `--sync-only` just re-syncs after pushing config changes. Cirro
throttles its reads of GitHub after a few calls in a row, so the script paces itself and retries.
Only whoever registered a pipeline can sync it.

**Generated config files.** Each entry point's `process-form.json`, `process-input.json`,
`preprocess.py`, `process-compute.config` and `process-output.json` are generated by
`scripts/build_cirro_configs.py` from per-stage field definitions, since every entry point
repeats the fields of all the stages after it. Edit the script, not the files, then run it
(`--check` verifies the committed files are current). `process-definition.json` is hand-written.

How the pieces fit:

- **One input dataset per run.** Each process maps its single selected input to
  `$.inputs[0].dataPath`, and writes its own outputs to `$.dataset.dataPath` (`outdir`) under
  each stage's subfolder (`00-organize/`, `01a-plan-conversion/`, ...).
- **Other datasets are chosen in the form**, via Cirro dataset pickers: the filled-in patient
  metadata table, the organized DICOM dataset and an optional edited plan, an optional prior
  preprocessed library, and an optional custom model or labels contract. Upload the metadata
  table / edited plan as a "Tables (TSV/CSV)" or "Files" dataset containing exactly one `.csv`;
  a custom model as a "Files" dataset containing its `pipeline.json` and checkpoints.
- **`preprocess.py`** (the same generated script in every folder, differing only in its entry
  stage) resolves what can't be mapped statically: it enforces the PHI confirmation on entry
  points before skull-stripping; decides whether the input is one of this pipeline's datasets
  (read the stage subfolder) or a direct upload (top level) from the input's process ID; refuses
  non-face-free input at "Run from preprocessed images" and "Quantify segmentation masks"; and
  turns picked datasets into file paths. Each exposes `run(ds)` so it can be exercised against
  real project datasets with the Cirro SDK's
  `DataPortal().developer_helper.generate_preprocess_for_input_datasets(...)`.
- **GPU:** Cirro's GPU nodes are g5 (NVIDIA A10G, 24 GB). `PREPROCESS_LIBRARY` defaults to 14
  workers -> 14 vCPU / 56 GB (fits g5.4xlarge) on the on-demand queue (`PW_ONDEMAND_JOB_QUEUE`), since
  it's one long task; `SEGMENT_GBM` requests 4 vCPU / 14 GB (fits g5.xlarge) on the default queue.
  Requests sit slightly under each instance's nominal memory because AWS Batch reserves some of it.
  `--shm-size` is set explicitly in these overlays: Nextflow's AWS Batch executor translates it
  into the job's shared-memory size, but ignores `--gpus` (`accelerator = 1` requests the GPU).
- **Results table:** every entry point that can reach quantification exposes
  `03b-quantify/volumes.tsv` in Cirro's table viewer via `process-output.json`.

### Still to confirm in a live Cirro project

- Upload layout: whether a "Files" upload of a folder keeps that folder as a wrapper level (the
  stage 2/3a/3b direct-upload contracts need patient folders at the top level).
- The exact value a dataset picker passes (the dataset root is assumed; `preprocess.py` also
  accepts a path that already ends in `/data`).
- How a multi-select dataset picker (`"multiple": true`, the Stage 2 "earlier NIfTI" fields)
  passes its value; `preprocess.py` accepts a list or a comma-separated string.
- Image pull cost: every *new* Batch instance pulls the ~7.5 GB image from GHCR over the
  internet (instances Batch reuses keep it cached), adding a few minutes of startup per instance.
  If that matters at scale, ask Cirro whether they can host or cache the image inside their AWS
  account (e.g. an ECR pull-through cache) and override `params.container` in the
  `process-compute.config` files.
- `.cirro/*/process-output.json`'s Parquet column list is a static preview of GBM_seg_v2's labels.
  Masks without a provenance sidecar, or a future model family, add columns it doesn't describe
  (they still appear in the TSV/Parquet, just without a curated name). Revisit when a second
  model family is registered in astril's `models.json`.

## License

astril-nf's code is licensed under [CC BY-NC-SA 4.0](LICENSE), the same as astril. The Docker
image also contains third-party software and pretrained weights under their own terms, two of
them non-commercial -- see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Research use only;
not a medical device.
