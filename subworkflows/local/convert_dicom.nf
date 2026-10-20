include { CONVERT_DICOM_PLAN } from '../../modules/local/convert_dicom_plan/main.nf'

workflow CONVERT_DICOM {
    take:
    organized_dir        // channel: path, re-supplied organized DICOM library (Stage 0 output or direct upload)
    plan                 // channel: path, conversion plan from Stage 1a (optionally user-edited)
    organized_dir_root   // channel: path, text file with the plan-generation task's absolute organized_dicoms root
    nifti_dir_root       // channel: path, text file with the plan-generation task's absolute nifti_out root

    main:
    CONVERT_DICOM_PLAN(organized_dir, plan, organized_dir_root, nifti_dir_root)

    emit:
    nifti_dir   = CONVERT_DICOM_PLAN.out.nifti_dir
    convert_log = CONVERT_DICOM_PLAN.out.log
}
