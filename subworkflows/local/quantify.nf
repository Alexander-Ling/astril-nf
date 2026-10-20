include { MERGE_SEG_VOLUMES } from '../../modules/local/merge_seg_volumes/main.nf'
include { QUANTIFY_VOLUMES  } from '../../modules/local/quantify_volumes/main.nf'
include { findLeafDirsContaining } from './utils.nf'

workflow QUANTIFY {
    take:
    seg_dir      // channel: path, Stage 3a output or a manually-edited/replacement set of
                 // segmentation masks -- flat or {patient}/{exam}/... nested, depth is discovered
    labels_json  // channel: path, an explicit labels.json contract, or the NO_LABELS_JSON
                 // sentinel -- only needed when matched files have no segmentation_provenance.json
                 // sidecar of their own (e.g. entering Stage 3b directly with externally-produced masks)

    main:
    if (params.merge_before_quantify) {
        // Overlaying multiple segmentation sources (model output + a manually corrected mask,
        // say) is an independent, per-exam operation, so it's still worth Nextflow-level fan-out
        // here even though quantification itself no longer is (see QUANTIFY_VOLUMES).
        exam_dirs = seg_dir.flatMap { root -> findLeafDirsContaining(root, params.seg_filename_pattern) }
        MERGE_SEG_VOLUMES(exam_dirs)
        quantify_input = MERGE_SEG_VOLUMES.out.merged.map { _name, dir -> dir }.collect()
    } else {
        // No per-exam pre-step needed -- hand the whole tree to QUANTIFY_VOLUMES as-is and let
        // astril's own recursive scan find every exam, at whatever depth it's nested.
        quantify_input = seg_dir
    }

    QUANTIFY_VOLUMES(quantify_input, labels_json)

    emit:
    aggregate_tsv = QUANTIFY_VOLUMES.out.volumes_tsv
}
