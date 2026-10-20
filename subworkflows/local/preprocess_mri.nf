include { MERGE_CUMULATIVE_NIFTI_LIBRARY } from '../../modules/local/merge_cumulative_nifti_library/main.nf'
include { PREPROCESS_LIBRARY             } from '../../modules/local/preprocess_library/main.nf'
include { GENERATE_QC_PDFS               } from '../../modules/local/generate_qc_pdfs/main.nf'

workflow PREPROCESS_MRI {
    take:
    new_nifti_dir          // channel: path, new/uploaded NIfTI exams, {patient}/{exam}/...
    prior_preprocessed_dir // channel: path, prior Stage 2 output, or the NO_PRIOR_LIBRARY placeholder

    main:
    MERGE_CUMULATIVE_NIFTI_LIBRARY(new_nifti_dir, prior_preprocessed_dir)

    old_coreg_log = MERGE_CUMULATIVE_NIFTI_LIBRARY.out.old_coreg_log
        .ifEmpty(file("${projectDir}/assets/NO_OLD_COREG_LOG"))

    PREPROCESS_LIBRARY(MERGE_CUMULATIVE_NIFTI_LIBRARY.out.union_dir, old_coreg_log)

    qc_pdfs = Channel.empty()
    if (params.generate_qc) {
        GENERATE_QC_PDFS(PREPROCESS_LIBRARY.out.preprocessed_dir)
        qc_pdfs = GENERATE_QC_PDFS.out.qc_pdfs
    }

    emit:
    preprocessed_dir = PREPROCESS_LIBRARY.out.preprocessed_dir
    qc_pdfs          = qc_pdfs
}
