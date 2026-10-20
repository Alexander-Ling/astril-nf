// Stage 2 output for upload: a copy of the preprocessed library holding ONLY skull-stripped
// images and brain masks -- the face-free subset that's safe to take off-site (e.g. to Cirro)
// and is all Stage 3a (segment) needs.
//
// Built as an ALLOWLIST, never a denylist: preprocessed_library/ also contains logs and
// transform records with absolute local paths, and libraries built by astril < 0.7.31 after an
// interrupted run may hold `.astril_tmp_*` folders of unmasked registered volumes (libraries
// from astril-nf < 0.2.0 also carry `_raw_passthrough/`, a whole-head copy of the raw input).
// Only files at exactly {patient}/{exam}/<file> depth whose names end in one of the patterns
// below are copied, and patient/exam folders starting with `_` or `.` are skipped, so none of
// those can get through however they're named. Every pattern below is masked by astril's
// preprocessing (astril preprocess_single_brain_mri.py: `_brain`/`_brain-norm` are written
// after the brainmask is applied; `_brainmask` is the binary mask itself).
process EXPORT_FACE_FREE_LIBRARY {
    tag 'export'
    label 'process_low'
    publishDir "${params.outdir}/02-preprocess", mode: 'copy'

    input:
    path preprocessed_dir, stageAs: 'lib'

    output:
    path 'upload_preprocessed', emit: export_dir

    script:
    """
    set -euo pipefail
    # Absolute, captured BEFORE cd: `lib` is a symlink into the upstream task's work dir, and
    # a relative ../ after cd-ing through it resolves THERE, not here.
    out="\$PWD/upload_preprocessed"
    mkdir "\$out"
    cd lib
    n=0
    for f in */*/*; do
        [ -f "\$f" ] || continue
        patient=\${f%%/*}; rest=\${f#*/}; exam=\${rest%%/*}; name=\${f##*/}
        case "\$patient" in _*|.*) continue ;; esac
        case "\$exam"    in _*|.*) continue ;; esac
        case "\$name" in
            *_brain-norm.nii.gz|*_brain.nii.gz|*_brainmask.nii.gz) ;;
            *) continue ;;
        esac
        mkdir -p "\$out/\$patient/\$exam"
        cp -L "\$f" "\$out/\$f"
        n=\$((n + 1))
    done
    if [ "\$n" -eq 0 ]; then
        echo "No skull-stripped images found to export under {patient}/{exam}/" >&2
        exit 1
    fi
    echo "Exported \$n face-free files to upload_preprocessed/"
    """
}
