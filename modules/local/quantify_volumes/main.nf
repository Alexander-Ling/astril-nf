// Stage 3b: per-class segmentation volumes for a whole segmentation tree in ONE
// `quantify_segmentation_volumes()` call, not fanned out per exam.
//
// Which levels get quantified is always pinned down by a contract -- `--total_levels`, an
// explicit `--labels_json`, or each file's own `segmentation_provenance.json` sidecar (written
// automatically by astril's `segment` in Stage 3a) -- never inferred by scanning voxel data for whichever values
// happen to appear (see astril's quantify_segmentation_volumes()). Different exams can be
// missing different levels without that being a real absence from the model's output space, and
// a per-exam Nextflow task would only ever see one file's own sidecar, so this runs as one task
// over everything to let a single contract apply consistently across the whole batch. Astril's
// own `--number_of_threads` already parallelizes the file I/O internally (same reasoning as
// Stage 2's single whole-library preprocess call), so there's nothing to gain from fanning out.
//
// `seg_dirs` may be a single root directory (Stage 3a output / a direct upload, nesting
// preserved) or a list of independently-produced per-exam directories (from the optional
// per-exam MERGE_SEG_VOLUMES step) -- either way everything is staged flat into this task's
// work dir and astril's own recursive glob finds every matching file regardless of depth.
process QUANTIFY_VOLUMES {
    tag 'quantify_volumes'
    label 'process_low'
    publishDir "${params.outdir}/03b-quantify", mode: 'copy'
    // Nextflow's default staging symlinks each input into the work dir; astril's own
    // `rglob('*')`-based file discovery does NOT descend into a symlinked child directory
    // (confirmed: Python's pathlib recursive wildcard only resolves symlinks at the path you
    // start the glob from, not ones it encounters partway through the walk) -- so with `.` as
    // root_directory (needed to see every staged item when seg_dirs is a list), a plain symlink
    // stage-in would make quantify-volumes silently find zero files. `stageInMode 'copy'` makes
    // every staged item a real, recursively-copied directory instead.
    stageInMode 'copy'

    input:
    path seg_dirs
    path labels_json_file   // a real labels.json contract, or the NO_LABELS_JSON sentinel

    output:
    path 'volumes.tsv',   emit: volumes_tsv
    path 'quantify.log',  emit: console_log

    script:
    // After an upstream merge, the file to quantify is the merged output, not the original
    // per-source pattern used only to locate exam directories.
    def pattern = params.merge_before_quantify ? params.merge_output_pattern : params.seg_filename_pattern
    def n_threads = params.quantify_n_threads ?: task.cpus
    def total_levels_flag = params.total_levels ? "--total_levels ${params.total_levels}" : ''
    def has_labels_json = labels_json_file.name != 'NO_LABELS_JSON'
    def labels_json_flag = has_labels_json ? "--labels_json ${labels_json_file}" : ''
    """
    set -o pipefail
    quantify-volumes \\
        . \\
        '${pattern}' \\
        volumes.tsv \\
        --number_of_threads ${n_threads} \\
        ${total_levels_flag} \\
        ${labels_json_flag} \\
        2>&1 | tee quantify.log
    """
}
