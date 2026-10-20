#!/usr/bin/env nextflow
/*
 * astril-nf: DICOM ingestion, MRI preprocessing, and GBM segmentation for astril, packaged to
 * run stage-by-stage in Cirro. Model training is out of scope. See README.md for the full
 * per-stage data contracts (each stage after Stage 0 accepts either the upstream stage's
 * output or a direct upload conforming to astril's own directory/file-naming conventions).
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

workflow {
    if (!params.stage) {
        exit 1, "Specify --stage one of: organize | plan_convert | convert | preprocess | segment | quantify"
    }

    if (params.stage == 'organize') {
        ORGANIZE_DICOM(requireParam('dicom_dir'))
    }
    else if (params.stage == 'plan_convert') {
        PLAN_CONVERSION(
            requireParam('organized_dir'),
            requireParam('dicom_index'),
            optionalRootFile('organized_dir_root'),
            requireParam('patient_metadata')
        )
    }
    else if (params.stage == 'convert') {
        CONVERT_DICOM(
            requireParam('organized_dir'),
            requireParam('conversion_plan'),
            optionalRootFile('organized_dir_root'),
            optionalRootFile('nifti_dir_root')
        )
    }
    else if (params.stage == 'preprocess') {
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
        PREPROCESS_MRI(requireParam('nifti_dir'), prior_ch)
    }
    else if (params.stage == 'segment') {
        // Stage 3b (quantify) now runs automatically right after Stage 3a (segment) by default --
        // the two have a well-defined contract between them (segmentation_provenance.json) that
        // makes chaining them the normal case. Pass --skip_quantify to stop after segmentation
        // alone, e.g. to manually correct masks before quantifying; re-enter quantification on
        // its own afterward with --stage quantify --seg_dir <corrected masks>.
        //
        // --model_dir (a self-trained model not published through astril's model manifest) takes
        // precedence over --model_family when both happen to be set, since Nextflow can't
        // distinguish "left at its default" from "explicitly set to the default" -- the module
        // only ever passes ONE of --model_family/--model_dir to astril's `segment` CLI.
        model_dir_ch = params.model_dir
            ? Channel.value(file(params.model_dir, checkIfExists: true))
            : Channel.value(noModelDir())
        SEGMENT(requireParam('preprocessed_dir'), model_dir_ch)

        if (!params.skip_quantify) {
            if (params.merge_before_quantify) {
                exit 1, "--merge_before_quantify overlays multiple segmentation sources for a " +
                    "single, already-fixed set of exams -- it's for the standalone --stage " +
                    "quantify entry point (re-quantifying a manually-edited/replacement mask " +
                    "set), not the automatic quantify that runs right after --stage segment. " +
                    "Pass --skip_quantify here and run --stage quantify separately if you need it."
            }
            seg_for_quantify = SEGMENT.out.segmented.map { _name, dir -> dir }.collect()
            QUANTIFY(seg_for_quantify, labelsJsonChannel())
        }
    }
    else if (params.stage == 'quantify') {
        QUANTIFY(requireParam('seg_dir'), labelsJsonChannel())
    }
    else {
        exit 1, "Unknown --stage '${params.stage}'. Expected one of: organize | plan_convert | convert | preprocess | segment | quantify"
    }
}
