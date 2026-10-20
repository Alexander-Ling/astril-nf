// Stage 0: organize an arbitrary DICOM library into astril's structured
// Patient/Exam/Series tree, and generate a blank per-patient metadata table for the
// user to fill in before Stage 1a (plan conversion) can run.
//
// organize_dicoms() and create_patient_metadata() are run in the SAME task (not split into
// two Nextflow processes) so that create_patient_metadata's `--index` lookup resolves
// against the exact same absolute `organized_dicoms` path organize_dicoms just wrote --
// astril's DICOM index stores absolute paths (`normalized_path`), and splitting this across
// two tasks would silently corrupt the metadata table's `Directory` column. No human editing
// happens between these two calls, so there is no need for a task boundary here; the human
// checkpoint is the (separate) manual fill-in of the metadata output before Stage 1a.
process ORGANIZE_DICOMS {
    tag 'organize'
    label 'process_medium'
    publishDir "${params.outdir}/00-organize", mode: 'copy'

    input:
    path dicom_dir, stageAs: 'raw_dicom'

    output:
    path 'organized_dicoms',            emit: organized_dir
    path 'dicom_index.csv',             emit: index
    path 'patient_metadata_blank.csv',  emit: metadata_template
    path 'organized_dicoms_root.txt',   emit: organized_dir_root
    path 'unresolved.csv',              emit: unresolved, optional: true
    path 'organize_log.csv',            emit: log, optional: true
    path 'organize.log',                emit: console_log

    script:
    // Defaults to this task's own resolved CPU allocation so astril's internal thread pool
    // never asks for more workers than the task is actually guaranteed (see nextflow.config).
    def n_workers = params.organize_n_workers ?: task.cpus
    """
    set -o pipefail

    {
        python -m astril.preprocess organize_dicoms \\
            --dir raw_dicom \\
            --outDir organized_dicoms \\
            --indexOut dicom_index.csv \\
            --unresolvedOut unresolved.csv \\
            --logOut organize_log.csv \\
            --n_workers ${n_workers} \\
            --noProgress

        python -m astril.preprocess create_patient_metadata \\
            --dir organized_dicoms \\
            --metadataOut patient_metadata_blank.csv \\
            --index dicom_index.csv \\
            --n_workers ${n_workers}
    } 2>&1 | tee organize.log

    printf '%s' "\$PWD/organized_dicoms" > organized_dicoms_root.txt
    """
}
