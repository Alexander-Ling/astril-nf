// Stage 3a: segmentation inference for one patient (all of that patient's exams in one call),
// via astril's generic, contract-driven `segment` CLI (reads the selected model's own
// pipeline.json -- see astril's segment.py/pipeline_contract.py). `segment` discovers "subjects"
// the same way the model's own contract describes (astril/create_segmentation_config.py's
// `all_dirs` includes the whole input tree, not just its root), and -- critically -- loads every
// stage's models ONCE per invocation regardless of how many subjects it then finds. Fanning out
// per EXAM instead of per PATIENT would reload those models once per exam, wasting most of the
// per-task time on a multi-exam patient -- passing the whole patient directory here lets one
// task's model load be amortized across all of that patient's exams.
//
// Exactly one of params.model_family (a family registered in astril's models.json -- GBM_seg_v2
// by default) or params.model_dir (a path to a self-trained model's own directory, not published
// through astril's model manifest) is used; model_dir_override, when not the NO_MODEL_DIR
// sentinel, takes precedence -- see main.nf and subworkflows/local/segment_gbm.nf.
process SEGMENT_GBM {
    tag { patient_dir.toString().tokenize('/').last() }
    label 'gpu'
    // Outputs are assembled under seg_out/ (the patient's own name is taken by the staged
    // input link in the task root); publish them as 03-segment/<patient>/...
    publishDir "${params.outdir}/03-segment", mode: 'copy',
        saveAs: { fn -> fn.startsWith('seg_out/') ? fn.substring('seg_out/'.length()) : fn }

    input:
    path patient_dir
    path model_dir_override

    output:
    // Only what segmentation produced (masks, provenance sidecars, configs) -- not the input
    // images, which already live in the input dataset.
    path 'seg_out/*',      emit: segmented
    path '*.segment.log',  emit: console_log

    script:
    def overwrite_flag = params.segment_overwrite ? '--overwrite_existing_outputs' : ''
    def has_model_dir_override = model_dir_override.name != 'NO_MODEL_DIR'
    def model_flag = has_model_dir_override
        ? "--model_dir ${model_dir_override}"
        : "--model_family ${params.model_family}"
    """
    set -euo pipefail
    name=\$(basename "${patient_dir}")
    # astril's `segment` writes its outputs next to its inputs, and the staged input is a link
    # back to the upstream data (the user's own folder when run locally) -- so segment a
    # private copy, never the input itself.
    mkdir work_seg seg_out
    cp -rL "${patient_dir}" "work_seg/\$name"
    segment "work_seg/\$name" \\
        ${model_flag} \\
        --segment_suffix '${params.seg_filename_pattern}' \\
        --slice_batch_size ${params.slice_batch_size} \\
        --input_override brainmask=${params.brainmask_pattern} \\
        ${overwrite_flag} \\
        2>&1 | tee "\$name.segment.log"

    cd work_seg
    find "\$name" -type f \\( -name '*${params.seg_filename_pattern}' -o -name segmentation_provenance.json \\
        -o -path "\$name/Segmentation_Configs/*" \\) -exec cp --parents {} ../seg_out \\;
    cd ..
    rm -rf work_seg
    """
}
