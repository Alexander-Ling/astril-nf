// Stage 1b: execute the (optionally user-edited) conversion plan from Stage 1a, producing
// the NIfTI library. Accepts either the plan straight from Stage 1a or a replacement dataset
// the user has hand-edited outside the pipeline -- either way it's just a CSV with the same
// schema.
//
// The plan's `folder` (source DICOM series) and `proposed_nifti_path` / `PrimarySeriesPath`
// (converted-NIfTI targets, incl. for derived-sequence generation) columns hold ABSOLUTE
// paths rooted in Stage 1a's task directory (see astril/preprocess.py's `convert_dicom_plan`,
// which uses these values directly with no re-joining against any `--dir`). They're rewritten
// here to point at this task's own re-staged copies before executing.
process CONVERT_DICOM_PLAN {
    tag 'convert'
    label 'process_medium'
    publishDir "${params.outdir}/01b-convert", mode: 'copy'

    input:
    path organized_dir, stageAs: 'organized_dicoms'
    path plan
    path organized_dir_root_file
    path nifti_dir_root_file

    output:
    path 'nifti_out',        emit: nifti_dir
    path 'convert_log.csv',  emit: log
    path 'convert.log',      emit: console_log

    script:
    def overwrite_flag = params.convert_overwrite ? '--overwrite' : ''
    def n_workers = params.convert_n_workers ?: task.cpus
    """
    set -o pipefail
    mkdir -p nifti_out

    OLD_DICOM_ROOT="\$(cat ${organized_dir_root_file})"
    OLD_NIFTI_ROOT="\$(cat ${nifti_dir_root_file})"

    {
        if [ "\${OLD_DICOM_ROOT}" = "NO_ROOT_OVERRIDE" ]; then
            # Direct-upload entry point: no upstream Stage 1a task to rewrite away from.
            cp ${plan} conversion_plan.rewritten.csv
        else
            python ${projectDir}/bin/rewrite_path_prefix.py \\
                --input ${plan} \\
                --output conversion_plan.rewritten.csv \\
                --rewrite "folder=\${OLD_DICOM_ROOT}::\$PWD/organized_dicoms" \\
                --rewrite "proposed_nifti_path=\${OLD_NIFTI_ROOT}::\$PWD/nifti_out" \\
                --rewrite "PrimarySeriesPath=\${OLD_NIFTI_ROOT}::\$PWD/nifti_out"
        fi

        python -m astril.preprocess convert_dicom_plan \\
            --plan conversion_plan.rewritten.csv \\
            --n_workers ${n_workers} \\
            ${overwrite_flag} \\
            --logOut convert_log.csv
    } 2>&1 | tee convert.log
    """
}
