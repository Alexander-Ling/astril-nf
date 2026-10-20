include { ORGANIZE_DICOMS } from '../../modules/local/organize_dicoms/main.nf'

workflow ORGANIZE_DICOM {
    take:
    dicom_dir   // channel: path to arbitrary/unstructured DICOM root

    main:
    ORGANIZE_DICOMS(dicom_dir)

    emit:
    organized_dir      = ORGANIZE_DICOMS.out.organized_dir
    index               = ORGANIZE_DICOMS.out.index
    metadata_template   = ORGANIZE_DICOMS.out.metadata_template
    organized_dir_root  = ORGANIZE_DICOMS.out.organized_dir_root
}
