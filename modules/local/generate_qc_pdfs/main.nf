// Stage 2 optional output: per-patient QC PDFs (center-axial-slice montages across all of a
// patient's preprocessed exams). Runs over the whole assembled library, not per-patient, so
// it is its own process after COLLECT_PREPROCESS_STATE. `_raw_passthrough/` (carried-forward
// raw exams, not a patient folder) is excluded from the scan.
process GENERATE_QC_PDFS {
    tag 'qc'
    label 'process_low'
    publishDir "${params.outdir}/02-preprocess/qc", mode: 'copy'

    input:
    path preprocessed_dir

    output:
    path 'qc/*.pdf', emit: qc_pdfs, optional: true
    path 'qc.log',   emit: console_log

    script:
    def n_workers = params.organize_n_workers ?: task.cpus
    """
    set -o pipefail
    mkdir -p qc_input qc
    for d in ${preprocessed_dir}/*/; do
        name=\$(basename "\$d")
        [ "\$name" = "_raw_passthrough" ] && continue
        ln -s "\$(readlink -f "\$d")" "qc_input/\$name"
    done

    python -m astril.preprocess generate_preprocessing_qc_pdfs \\
        --dir qc_input \\
        --outDir qc \\
        --n_workers ${n_workers} \\
        --noProgress \\
        2>&1 | tee qc.log
    """
}
