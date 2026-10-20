# astril-nf

A Nextflow wrapper around [astril](https://github.com/Alexander-Ling/astril)'s DICOM ingestion, MRI
preprocessing, and GBM segmentation, packaged to run as chained processes in
[Cirro](https://cirro.bio). **Model training is explicitly out of scope** -- this pipeline covers
astril's preprocessing and segmentation functionality only.

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
| 3a. Segment | `segment` | Segmentation inference via a selected model (`--model_family GBM_seg_v2` by default, or `--model_dir` for a self-trained model), one Nextflow task per PATIENT (all of that patient's exams in one call, since the model's own pipeline loads its models once per invocation regardless of exam count -- fanning out per exam would reload them per exam for no benefit). Writes a `segmentation_provenance.json` sidecar next to each exam's output recording the model's identity and label meanings. **Automatically chains into Stage 3b** unless `--skip_quantify` is set. |
| 3b. Quantify | `segment` (auto) or `quantify` (standalone) | Per-class segmentation volumes (mm³) for the whole segmentation tree in ONE `quantify-volumes` call, aggregated directly into one table (not fanned out per exam -- see Multi-threading below). Which levels to quantify comes from an explicit contract: `total_levels`, `labels_json`, or (automatically) each file's own `segmentation_provenance.json` sidecar from Stage 3a. Runs automatically right after Stage 3a by default; pass `--skip_quantify` to Stage 3a and re-enter with `--stage quantify --seg_dir ...` separately to quantify a manually corrected/replacement set of masks instead, with an optional merge-multiple-sources step first. |

## Enter at any stage

Stages 2, 3a, and 3b accept either the upstream stage's own output *or* a direct upload that
follows astril's directory/file-naming conventions for that boundary. With a direct upload, the
patient folders must sit at the top level of the upload (or of `--nifti_dir`/`--preprocessed_dir`/
`--seg_dir` when running locally), not inside an extra wrapper folder:

- **Stage 2 (preprocess):** NIfTI library, `{patient}/{exam}/{label}.nii.gz`
- **Stage 3a (segment):** preprocessed NIfTI library, `{patient}/{exam}/..._brain-norm.nii.gz` +
  `..._brainmask.nii.gz`
- **Stage 3b (quantify, standalone):** segmentation masks, `{patient}/{exam}/..._GBM-seg.nii.gz`
  (or a flat collection of exam dirs -- depth is auto-detected, see `subworkflows/local/utils.nf`).
  `--stage segment` always produces its own masks first (Stage 3a) before quantifying them, so
  this is the entry point for manually corrected or externally produced masks.

Stages 1a and 1b only run on this pipeline's own upstream output (Stage 0's organized DICOM tree
and index; Stage 1a's plan), since their absolute-path bookkeeping is specific to it -- though
Stage 1b accepts a hand-edited copy of Stage 1a's plan. Only Stage 0 has to tolerate genuinely
arbitrary input structure.

## Running locally (outside Cirro)

```
nextflow run main.nf -profile docker,test --stage organize --dicom_dir /path/to/raw_dicom
```

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
which genuinely is independent per exam -- available only via the standalone `--stage quantify`
entry point, not the automatic quantify chained after `--stage segment` (see "Chaining Stage 3a
into Stage 3b" below).

## Chaining Stage 3a into Stage 3b

`--stage segment` runs Stage 3a (segmentation) and then, by default, Stage 3b (quantify)
automatically in the same invocation -- the well-defined contract between them
(`segmentation_provenance.json`) makes this the normal case rather than something requiring two
separate commands. `SEGMENT`'s per-patient output is collected into one list and handed to
`QUANTIFY` as a single whole-tree call, exactly as if you'd passed that same tree to `--stage
quantify --seg_dir ...` yourself.

Pass `--skip_quantify` to stop after Stage 3a alone -- e.g. to manually correct masks before
quantifying -- then run quantification on its own afterward: `--stage quantify --seg_dir
<corrected masks>`. `--merge_before_quantify` (overlaying multiple segmentation sources for a
single, already-fixed set of exams) is rejected with a clear error if set during the automatic
chain, since it only makes sense for that standalone re-entry case; the pipeline never runs it
except through `--stage quantify` directly. In Cirro, this reflects a `skip_quantify` toggle on
the segmentation form plus a separate, always-available "astril: Quantify segmentation volumes"
process for the manual-correction path.

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
patient's older and newer exams in different reference spaces. This pipeline refuses to do that:
`bin/merge_cumulative_nifti_library.py` unions new exams with the raw exams carried forward from
the prior preprocessed-library run and hard-fails if a patient's logged reference exam isn't
present in the union, rather than letting astril silently re-pick. Pass a prior Stage 2 output as
`--prior_preprocessed_dir` to run incrementally; omit it for a first-time run.

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
docker build -t ghcr.io/alexander-ling/astril-nf:0.1.0 .
docker push ghcr.io/alexander-ling/astril-nf:0.1.0
```
To pick up newer astril code, bump `ASTRIL_GIT_REF` in the Dockerfile, bump the image tag (here and
in `nextflow.config`'s `params.container`), and rebuild. `ASTRIL_CACHEBUST`
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

Each stage is registered as its own **custom pipeline** in a Cirro project (Project Settings ->
Pipelines -> add a custom pipeline), all pointing at this repository and `main.nf`, each with its
own configuration folder under `.cirro/`. Cirro reads `process-form.json`, `process-input.json`,
`process-compute.config`, and (where present) `preprocess.py` / `process-output.json` from that
folder. `process-definition.json` is *not* read for custom pipelines -- it records the values to
enter in the registration form (id, name, description, input processes):

| Config folder | Process ID | Input processes |
|---|---|---|
| `.cirro/00-organize` | `process-astril-organize-1-0` | `custom_dataset` ("Files" upload of raw DICOM) |
| `.cirro/01a-plan-conversion` | `process-astril-plan-conversion-1-0` | `process-astril-organize-1-0` |
| `.cirro/01b-convert` | `process-astril-convert-1-0` | `process-astril-plan-conversion-1-0` |
| `.cirro/02-preprocess` | `process-astril-preprocess-1-0` | `process-astril-convert-1-0`, `custom_dataset` |
| `.cirro/03-segment` | `process-astril-segment-1-0` | `process-astril-preprocess-1-0`, `custom_dataset` |
| `.cirro/03b-quantify` | `process-astril-quantify-1-0` | `process-astril-segment-1-0`, `custom_dataset` |

Process IDs can't be changed after creation, and the `preprocess.py` scripts and dataset pickers
refer to them, so use exactly these. Pin the Nextflow version to `26.04.0` where the form allows.

How the pieces fit:

- **One input dataset per run.** Each process maps its single selected input to
  `$.inputs[0].dataPath`, and writes its own outputs to `$.dataset.dataPath` (`outdir`) under
  that stage's subfolder (`00-organize/`, `01a-plan-conversion/`, ...).
- **Other datasets are chosen in the form**, via Cirro dataset pickers: the filled-in patient
  metadata table (1a), the organized DICOM dataset and an optional edited plan (1b), an optional
  prior preprocessed library (2), and an optional custom model or labels contract (3a/3b). Upload
  the metadata table / edited plan as a "Tables (TSV/CSV)" or "Files" dataset containing exactly
  one `.csv`; a custom model as a "Files" dataset containing its `pipeline.json` and checkpoints.
- **`preprocess.py`** resolves what can't be mapped statically: whether the input is the upstream
  stage's own dataset (look inside its stage subfolder) or a direct upload (top level), decided by
  the input dataset's process ID; and turning picked datasets into concrete file paths. The
  scripts expose `run(ds)` so they can be exercised against real project datasets from outside
  Cirro with the Cirro SDK's `DataPortal().developer_helper.generate_preprocess_for_input_datasets(...)`.
- **GPU:** Cirro's GPU nodes are g5 (NVIDIA A10G, 24 GB). `PREPROCESS_LIBRARY` defaults to 14
  workers -> 14 vCPU / 56 GB (fits g5.4xlarge) on the on-demand queue (`PW_ONDEMAND_JOB_QUEUE`), since
  it's one long task; `SEGMENT_GBM` requests 4 vCPU / 14 GB (fits g5.xlarge) on the default queue.
  Requests sit slightly under each instance's nominal memory because AWS Batch reserves some of it.
  `--shm-size` is set explicitly in these overlays: Nextflow's AWS Batch executor translates it
  into the job's shared-memory size, but ignores `--gpus` (`accelerator = 1` requests the GPU).
- **Results table:** Stage 3a (with its automatic quantify) and standalone Stage 3b both expose
  `03b-quantify/volumes.tsv` in Cirro's table viewer via `process-output.json`.

### Still to confirm in a live Cirro project

- Upload layout: whether a "Files" upload of a folder keeps that folder as a wrapper level (the
  stage 2/3a/3b direct-upload contracts need patient folders at the top level).
- The exact value a dataset picker passes (the dataset root is assumed; `preprocess.py` also
  accepts a path that already ends in `/data`).
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
