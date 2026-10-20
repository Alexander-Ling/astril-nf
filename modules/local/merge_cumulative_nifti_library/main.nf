// Stage 2 pre-step: union new NIfTI exams with the earlier raw NIfTI inputs of an incremental
// run, and verify every patient's previously-chosen registration reference exam is still
// present -- see bin/merge_cumulative_nifti_library.py for the full rationale (astril's own
// `--old_coreg_log` reuse silently re-picks a reference if the old one is missing; this step
// fails loudly instead). The prior preprocessed library only contributes its coreg log; the
// earlier raw exams come in explicitly via params.prior_nifti_dirs rather than as a copy kept
// inside the library.
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
    // Zero or more earlier NIfTI roots, or the NO_PRIOR_NIFTI placeholder file.
    path prior_nifti_dirs, stageAs: 'prior_nifti_?'

    output:
    path 'union_nifti',        emit: union_dir
    path 'old_coreg_log.csv',  emit: old_coreg_log, optional: true
    path 'merge_library.log',  emit: console_log

    script:
    def prior_flag = prior_library_dir.name != 'NO_PRIOR_LIBRARY'
        ? "--prior-library-dir ${prior_library_dir}" : ''
    """
    set -o pipefail
    # Directories only: the NO_PRIOR_NIFTI placeholder (staged under the same pattern) is a file.
    prior_nifti_flags=()
    for d in ${prior_nifti_dirs}; do
        [ -d "\$d" ] && prior_nifti_flags+=(--prior-nifti-dir "\$d")
    done
    python ${projectDir}/bin/merge_cumulative_nifti_library.py \\
        --new-nifti-dir new_nifti \\
        ${prior_flag} \\
        "\${prior_nifti_flags[@]}" \\
        --output-dir union_nifti \\
        --old-coreg-log-out old_coreg_log.csv \\
        2>&1 | tee merge_library.log
    """
}
