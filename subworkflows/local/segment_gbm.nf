include { SEGMENT_GBM } from '../../modules/local/segment_gbm/main.nf'
include { findLeafDirsContaining } from './utils.nf'

workflow SEGMENT {
    take:
    preprocessed_dir   // channel: path, {patient}/{exam}/... (Stage 2 output or a direct upload
                        // conforming to astril's preprocessed-library structure) -- may also be
                        // a flat collection of exam dirs; depth is discovered, not assumed.
    model_dir           // channel: path, a self-trained model's own directory, or the
                        // NO_MODEL_DIR sentinel -- see modules/local/segment_gbm/main.nf

    main:
    // Fan out to one task per PATIENT (not per exam): astril's `segment` engine loads every
    // stage's models once per invocation regardless of how many exams it's given, so grouping a
    // patient's exams into a single call amortizes that load across them instead of repeating it
    // per exam. An exam dir
    // is identified by containing a brainmask file, regardless of how deeply it's nested under
    // `preprocessed_dir`; patient dirs are then the unique immediate parents of those exam dirs.
    // A flat input (exam dirs with no shared patient parent) collapses to one task for the
    // whole thing -- correct, if less parallel; astril's own directory naming convention
    // (patient/exam nested) is what this is designed around.
    patient_dirs = preprocessed_dir
        .flatMap { root -> findLeafDirsContaining(root, params.brainmask_pattern) }
        .map { examDir -> examDir.getParent() }
        .unique()
        // An empty channel would otherwise skip segmentation AND quantify silently while the run
        // still reports success.
        .ifEmpty { error("No exam folders containing '${params.brainmask_pattern}' found in the preprocessed library -- nothing to segment.") }

    SEGMENT_GBM(patient_dirs, model_dir)

    emit:
    segmented = SEGMENT_GBM.out.segmented   // path: one patient folder of segmentation outputs per task
}
