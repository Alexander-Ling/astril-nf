// Stage 2 pre-step: union new NIfTI exams with the raw exams carried forward from the prior
// preprocessed-library run, and verify every patient's previously-chosen registration
// reference exam is still present -- see bin/merge_cumulative_nifti_library.py for the full
// rationale (astril's own `--old_coreg_log` reuse silently re-picks a reference if the old
// one is missing; this step fails loudly instead).
process MERGE_CUMULATIVE_NIFTI_LIBRARY {
    tag 'merge_library'
    label 'process_low'
    // Published under its own subfolder, separate from the final preprocessed_library output,
    // so this pre-step's diagnostics (the union safety-check log, and the accumulated coreg log
    // before preprocessing runs) are still inspectable without cluttering it.
    // `union_nifti` itself is excluded -- it's a large staging copy consumed by
    // PREPROCESS_LIBRARY, not something worth duplicating into the published output.
    publishDir "${params.outdir}/02-preprocess/_merge_library", mode: 'copy', pattern: '{merge_library.log,old_coreg_log.csv}'

    input:
    path new_nifti_dir, stageAs: 'new_nifti'
    path prior_library_dir

    output:
    path 'union_nifti',        emit: union_dir
    path 'old_coreg_log.csv',  emit: old_coreg_log, optional: true
    path 'merge_library.log',  emit: console_log

    script:
    def prior_flag = prior_library_dir.name != 'NO_PRIOR_LIBRARY'
        ? "--prior-library-dir ${prior_library_dir}" : ''
    """
    set -o pipefail
    python ${projectDir}/bin/merge_cumulative_nifti_library.py \\
        --new-nifti-dir new_nifti \\
        ${prior_flag} \\
        --output-dir union_nifti \\
        --old-coreg-log-out old_coreg_log.csv \\
        2>&1 | tee merge_library.log
    """
}
