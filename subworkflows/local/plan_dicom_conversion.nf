include { PLAN_DICOM_CONVERSION } from '../../modules/local/plan_dicom_conversion/main.nf'

workflow PLAN_CONVERSION {
    take:
    organized_dir        // channel: path, either from Stage 0 or a direct "organized DICOM" upload
    index                // channel: path, dicom_index.csv from Stage 0
    organized_dir_root   // channel: path, text file with Stage 0's absolute organized_dicoms root
    patient_metadata     // channel: path, the user-filled-in metadata table

    main:
    PLAN_DICOM_CONVERSION(organized_dir, index, organized_dir_root, patient_metadata)

    emit:
    plan                = PLAN_DICOM_CONVERSION.out.plan
    organized_dir_root  = PLAN_DICOM_CONVERSION.out.organized_dir_root
    nifti_dir_root      = PLAN_DICOM_CONVERSION.out.nifti_dir_root
}
