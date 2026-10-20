// Stage 3b optional pre-step (standalone --stage quantify only): overlay multiple segmentation sources for one exam (e.g. the
// model's own output plus a manually corrected mask a user uploaded) into one merged volume.
// `merge_seg_volumes()` finds subjects by recursing for SUBDIRECTORIES (astril/
// merge_seg_volumes.py's `rglob('*')` filtered to `is_dir()`, unlike quantify's file-based
// scan), so the exam directory is nested one level deep here to be discovered as a subject.
process MERGE_SEG_VOLUMES {
    tag { exam_dir.name }
    label 'process_low'
    publishDir "${params.outdir}/03b-quantify/_merge_logs", mode: 'copy', pattern: '*.merge_seg.log'

    input:
    path exam_dir

    output:
    tuple val("${exam_dir.name}"), path("merged/${exam_dir.name}"), emit: merged
    path "${exam_dir.name}.merge_seg.log", emit: console_log

    script:
    def patterns = params.merge_input_patterns.tokenize(',').collect { it.trim() }.join(' ')
    """
    set -o pipefail
    {
        mkdir -p merge_input merged
        cp -rL ${exam_dir} merge_input/${exam_dir.name}

        merge-seg-volumes \\
            --inputVolumePatterns ${patterns} \\
            --inputVolumeDirectory merge_input \\
            --outputVolumeDirectory in_place \\
            --outputVolumePatterns "${params.merge_output_pattern}"

        cp -rL merge_input/${exam_dir.name} merged/${exam_dir.name}
    } 2>&1 | tee "${exam_dir.name}.merge_seg.log"
    """
}
