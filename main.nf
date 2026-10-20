#!/usr/bin/env nextflow
/*
 * astril-nf: DICOM ingestion, MRI preprocessing, and GBM segmentation for astril, packaged for
 * local runs and Cirro. Model training is out of scope. A run starts at any stage (--stage) and
 * continues through --stop_after; see README.md for the per-stage data contracts (each stage
 * after Stage 0 accepts either the upstream stage's output or a direct upload conforming to
 * astril's own directory/file-naming conventions).
 */
nextflow.enable.dsl = 2

include { ORGANIZE_DICOM     } from './subworkflows/local/organize_dicom.nf'
include { PLAN_CONVERSION    } from './subworkflows/local/plan_dicom_conversion.nf'
include { CONVERT_DICOM      } from './subworkflows/local/convert_dicom.nf'
include { PREPROCESS_MRI     } from './subworkflows/local/preprocess_mri.nf'
include { SEGMENT            } from './subworkflows/local/segment_gbm.nf'
include { QUANTIFY           } from './subworkflows/local/quantify.nf'

def noPriorLibrary() {
    return file("${projectDir}/assets/NO_PRIOR_LIBRARY")
}

def noRootOverride() {
    return file("${projectDir}/assets/NO_ROOT_OVERRIDE")
}

def noLabelsJson() {
    return file("${projectDir}/assets/NO_LABELS_JSON")
}

def noModelDir() {
    return file("${projectDir}/assets/NO_MODEL_DIR")
}

def labelsJsonChannel() {
    return params.labels_json
        ? Channel.value(file(params.labels_json, checkIfExists: true))
        : Channel.value(noLabelsJson())
}

// Subworkflows call channel operators (.flatMap, .first, etc.) directly on their `take:`
// inputs in a few places (e.g. segment_gbm.nf, quantify.nf) -- that only works on a real
// channel, not a plain value, even though a plain value is tolerated when passed straight into
// a process call. Always returning a proper value channel here avoids the distinction mattering.
def requireParam(name) {
    if (!params[name]) {
        exit 1, "Missing required parameter --${name} for stage '${params.stage}'"
    }
    return Channel.value(file(params[name], checkIfExists: true))
}

// organized_dir_root / nifti_dir_root are only needed to rewrite absolute paths baked in by
// an upstream Stage 0/1a task of THIS pipeline; a direct-upload entry point (e.g. an
// externally-generated index/plan, or one already valid as-is) can omit them.
def optionalRootFile(name) {
    def f = params[name] ? file(params[name], checkIfExists: true) : noRootOverride()
    return Channel.value(f)
}

// --stage is where a run STARTS; it then continues through every later stage up to and
// including --stop_after (default: quantify), handing each stage's output straight to the next.
// Every stage still publishes its own outputs under its own NN-<stage>/ folder, so any of them
// can be a later run's starting point (e.g. re-entering at convert with a hand-edited plan).
// Organize is the exception: Stage 1a needs the patient metadata table a person fills in from
// Stage 0's output, so a run starting at organize always stops there.
def stages() {
    return ['organize', 'plan_convert', 'convert', 'preprocess', 'segment', 'quantify']
}

def stopAfter() {
    return params.stop_after ?: (params.stage == 'organize' ? 'organize' : 'quantify')
}

// Whether stage s is part of this run.
def runs(s) {
    def i = stages().indexOf(s)
    return stages().indexOf(params.stage) <= i && i <= stages().indexOf(stopAfter())
}

// Whether this run starts at stage s (so s reads its inputs from params, not an upstream stage).
def starts(s) {
    return params.stage == s
}

workflow {
    def STAGES = stages()
    if (!(params.stage in STAGES)) {
        exit 1, "Specify --stage, one of: ${STAGES.join(' | ')} (got '${params.stage}')"
    }
    if (!(stopAfter() in STAGES) || STAGES.indexOf(stopAfter()) < STAGES.indexOf(params.stage)) {
        exit 1, "--stop_after must be --stage itself or a later stage, one of: " +
            "${STAGES.subList(STAGES.indexOf(params.stage), STAGES.size()).join(' | ')} (got '${stopAfter()}')"
    }
    if (params.stage == 'organize' && stopAfter() != 'organize') {
        exit 1, "A run starting at organize always stops there: fill in its " +
            "patient_metadata_blank.csv, then start the next run at --stage plan_convert."
    }

    if (params.merge_before_quantify && !starts('quantify')) {
        exit 1, "--merge_before_quantify overlays multiple segmentation sources for a single, " +
            "already-fixed set of exams -- it's for runs starting at --stage quantify " +
            "(re-quantifying a manually-edited/replacement mask set), not the quantify that " +
            "follows segmentation within the same run."
    }

    if (runs('organize')) {
        ORGANIZE_DICOM(requireParam('dicom_dir'))
    }

    def plan_ch = null
    def organized_root_ch = null
    def nifti_root_ch = null
    if (runs('plan_convert')) {
        PLAN_CONVERSION(
            requireParam('organized_dir'),
            requireParam('dicom_index'),
            optionalRootFile('organized_dir_root'),
            requireParam('patient_metadata')
        )
        plan_ch           = PLAN_CONVERSION.out.plan
        organized_root_ch = PLAN_CONVERSION.out.organized_dir_root
        nifti_root_ch     = PLAN_CONVERSION.out.nifti_dir_root
    }

    def nifti_ch = null
    if (runs('convert')) {
        CONVERT_DICOM(
            requireParam('organized_dir'),
            starts('convert') ? requireParam('conversion_plan')               : plan_ch,
            starts('convert') ? optionalRootFile('organized_dir_root')        : organized_root_ch,
            starts('convert') ? optionalRootFile('nifti_dir_root')            : nifti_root_ch
        )
        nifti_ch = CONVERT_DICOM.out.nifti_dir
    }

    def preprocessed_ch = null
    if (runs('preprocess')) {
        // astril doesn't budget memory itself (only CPU thread counts, per worker), so a
        // manual preprocess_memory_gb override that looks too low for the requested worker
        // count is worth a warning here -- an OOM kill (exit 137) part-way through a real run
        // is a much more expensive way to discover the same mismatch.
        if (params.preprocess_memory_gb) {
            // .toInteger(): CLI-provided values arrive as Strings regardless of the config
            // default's declared type; comparing/multiplying Strings directly either fails or
            // does lexical (not numeric) comparison.
            def memOverride = params.preprocess_memory_gb.toInteger()
            def nWorkers    = params.preprocess_n_workers.toInteger()
            def perWorker   = params.preprocess_memory_gb_per_worker.toInteger()
            def recommended = nWorkers * perWorker
            if (memOverride < recommended) {
                log.warn(
                    "preprocess_memory_gb=${memOverride} looks low for " +
                    "preprocess_n_workers=${nWorkers} (recommended >= " +
                    "${recommended} GB at ${perWorker} GB/worker). " +
                    "This may OOM-kill (exit 137) partway through -- lower preprocess_n_workers " +
                    "or raise preprocess_memory_gb if that happens."
                )
            }
        }
        prior_ch = params.prior_preprocessed_dir
            ? Channel.value(file(params.prior_preprocessed_dir, checkIfExists: true))
            : Channel.value(noPriorLibrary())
        PREPROCESS_MRI(starts('preprocess') ? requireParam('nifti_dir') : nifti_ch, prior_ch)
        // Segment from the face-free export, not the full library, so a chained run exercises
        // exactly the files a user would upload to start at segment (see
        // modules/local/export_face_free_library).
        preprocessed_ch = PREPROCESS_MRI.out.export_dir
    }

    def segmented_ch = null
    if (runs('segment')) {
        // --model_dir (a self-trained model not published through astril's model manifest) takes
        // precedence over --model_family when both happen to be set, since Nextflow can't
        // distinguish "left at its default" from "explicitly set to the default" -- the module
        // only ever passes ONE of --model_family/--model_dir to astril's `segment` CLI.
        model_dir_ch = params.model_dir
            ? Channel.value(file(params.model_dir, checkIfExists: true))
            : Channel.value(noModelDir())
        SEGMENT(starts('segment') ? requireParam('preprocessed_dir') : preprocessed_ch, model_dir_ch)
        segmented_ch = SEGMENT.out.segmented.map { _name, dir -> dir }.collect()
    }

    if (runs('quantify')) {
        QUANTIFY(starts('quantify') ? requireParam('seg_dir') : segmented_ch, labelsJsonChannel())
    }
}
