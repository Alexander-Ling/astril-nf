// Stage 2: co-register, skull-strip (HD-BET), and normalize a whole NIfTI library in one
// `preprocess_brain_mris` call.
//
// This is deliberately ONE Nextflow task for the whole (merged) library, not fanned out per
// patient or per exam: `preprocess_library()` already does exam-level fan-out internally via
// its own `--n_workers` thread pool, AFTER selecting every patient's registration reference and
// precomputing each patient's shared brainmask (one batched HD-BET folder call across all
// patients needing one) -- see astril/preprocess_brain_mris.py. It also already auto-budgets
// nested SimpleITK/HD-BET thread counts per worker (`n_workers_per_registration_process`/
// `n_workers_per_hd_bet_process`, derived from `cpu_count() // n_workers`) to avoid
// oversubscription. Re-implementing any of that at the Nextflow level (e.g. one task per
// patient) would just duplicate logic astril already gets right, while losing astril's own
// cross-patient HD-BET batching and forcing this pipeline to depend on astril's *private*
// reference-selection functions instead of its public `preprocess_brain_mris` CLI.
//
// The tradeoff: the whole library's preprocessing runs on one instance/task, sized by
// `--n_workers` (see params.preprocess_n_workers) and this process's own cpus/memory request --
// it doesn't scale out across multiple Cirro/Batch instances the way a per-exam fan-out would.
// For a single well-resourced GPU workstation this matches how astril is already run natively;
// revisit if a future deployment needs to spread one library's preprocessing across machines.
process PREPROCESS_LIBRARY {
    tag 'preprocess_library'
    label 'gpu'
    publishDir "${params.outdir}/02-preprocess", mode: 'copy'

    input:
    path union_dir, stageAs: 'in_lib'
    path old_coreg_log

    output:
    path 'preprocessed_library',                             emit: preprocessed_dir
    path 'preprocessed_library/coreg_log_*.csv',              emit: coreg_log,      optional: true
    path 'preprocessed_library/preprocess_log_*.csv',         emit: preprocess_log, optional: true
    path 'preprocess.log',                                    emit: console_log

    script:
    def has_old_log   = old_coreg_log.name != 'NO_OLD_COREG_LOG'
    def old_log_flag  = has_old_log ? "--old_coreg_log ${old_coreg_log}" : ''
    def gpu_flag      = params.use_gpu ? '--use_gpu' : ''
    def tta_flag      = (params.use_gpu && params.enable_tta) ? '--enable_tta' : ''
    def overwrite_flag = params.preprocess_overwrite ? '--overwrite' : ''
    // params.preprocess_n_workers is the source of truth here (unlike the other stages' n_workers
    // params) -- this process's own cpus/memory request is DERIVED from it (conf/gpu.config),
    // not the other way around, so there's no oversubscription risk in using it directly.
    def n_workers = params.preprocess_n_workers
    """
    set -o pipefail
    # No copy of the raw input is kept in the library: it would duplicate data the caller
    # already has, and it's whole-head (identifiable). Incremental runs pass the earlier raw
    # NIfTI back in via params.prior_nifti_dirs instead (see merge_cumulative_nifti_library).
    preprocess_brain_mris \\
        --in_dir in_lib \\
        --out_dir preprocessed_library \\
        ${old_log_flag} \\
        --anchor_label ${params.anchor_label} \\
        --registration_strategy ${params.registration_strategy} \\
        --normalization_method ${params.normalization_method} \\
        --final_dims ${params.final_dims} \\
        --final_voxels ${params.final_voxels} \\
        ${gpu_flag} \\
        ${tta_flag} \\
        ${overwrite_flag} \\
        --skip_qc \\
        --n_workers ${n_workers} \\
        2>&1 | tee preprocess.log
    """
}
