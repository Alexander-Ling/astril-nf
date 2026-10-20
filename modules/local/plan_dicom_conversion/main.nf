// Stage 1a: classify series and propose a DICOM -> NIfTI conversion plan. The plan is a
// CSV the user can review/edit (e.g. deselect series, relabel a modality) before Stage 1b
// executes it -- this is the human-in-the-loop checkpoint the two-stage split exists for.
//
// astril's DICOM index bakes in ABSOLUTE paths (`normalized_path`) computed inside whichever
// task wrote it (see astril/preprocess.py's `plan_dicom_to_nifti_conversion`, which derives
// patient/exam/series structure via `os.path.dirname()` chains on that column). Since this
// runs in a different Nextflow task than Stage 0, the index must be rewritten to point at
// THIS task's own re-staged copy of `organized_dicoms` before it's safe to use. The
// `patientMetadata`'s `Directory` column is already relative, so it needs no rewriting.
process PLAN_DICOM_CONVERSION {
    tag 'plan_conversion'
    label 'process_medium'
    // No `pattern:` restriction here -- `organized_dicoms_root.txt` and `nifti_root.txt` must
    // also land in the published dataset, since Stage 1b reads them back from THIS stage's
    // published output (via Cirro's dataset-lineage, not Nextflow's own work directory) to
    // rewrite the plan's paths onto its own task.
    publishDir "${params.outdir}/01a-plan-conversion", mode: 'copy'

    input:
    path organized_dir, stageAs: 'organized_dicoms'
    path dicom_index
    path organized_dir_root_file
    path patient_metadata

    output:
    path 'conversion_plan.csv',       emit: plan
    path 'organized_dicoms_root.txt', emit: organized_dir_root
    path 'nifti_root.txt',            emit: nifti_dir_root
    path 'plan_generation.log',       emit: log

    script:
    def n_workers = params.organize_n_workers ?: task.cpus
    """
    set -o pipefail
    mkdir -p nifti_out

    OLD_DICOM_ROOT="\$(cat ${organized_dir_root_file})"

    {
        if [ "\${OLD_DICOM_ROOT}" = "NO_ROOT_OVERRIDE" ]; then
            # Direct-upload entry point: no upstream Stage 0 task to rewrite away from.
            cp ${dicom_index} dicom_index.rewritten.csv
        else
            python ${projectDir}/bin/rewrite_path_prefix.py \\
                --input ${dicom_index} \\
                --output dicom_index.rewritten.csv \\
                --rewrite "normalized_path=\${OLD_DICOM_ROOT}::\$PWD/organized_dicoms"
        fi

        python -m astril.preprocess plan_dicom_to_nifti_conversion \\
            --patientMetadata ${patient_metadata} \\
            --dir organized_dicoms \\
            --dicomIndex dicom_index.rewritten.csv \\
            --outDir nifti_out \\
            --planOut conversion_plan.csv \\
            --minSlices ${params.min_slices} \\
            --n_workers ${n_workers} \\
            --noProgress
    } 2>&1 | tee plan_generation.log

    printf '%s' "\$PWD/organized_dicoms" > organized_dicoms_root.txt
    printf '%s' "\$PWD/nifti_out" > nifti_root.txt
    """
}
