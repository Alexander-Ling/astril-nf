#!/usr/bin/env bash
# De-identify one patient's DICOM files (any number of scans/series, any folder layout) with
# RSNA CTP's DICOM anonymizer, via RSNA's command-line DicomAnonymizerTool (DAT).
#
# Starts from CTP's default DICOM PS3.15 Basic profile and overrides only what astril needs to
# keep working on the result:
#   - PatientName / PatientID  -> the pseudonym you give (-p), identical for every scan
#   - all dates (Study/Series/Acquisition/Content) -> shifted by ONE per-patient offset (-d), so
#     intervals between scans, and the dN timepoints astril derives from them, are preserved
#   - Study/Series/Acquisition/Content times -> kept (astril orders series and detects
#     pre/post-contrast from acquisition times; the default profile removes them)
#   - Manufacturer, ManufacturerModelName, ProtocolName -> kept (series classification)
#   - PatientBirthDate, AccessionNumber, AcquisitionDateTime -> removed
#   - UIDs -> hashed consistently, so study/series grouping survives
#   - private (odd) groups -> removed, unless -k
#   - OriginalAttributesSequence, ModifiedAttributesSequence, ContributingEquipmentSequence,
#     ClinicalTrial* -> removed (the default profile passes them through)
#
# CTP's default profile is a denylist: elements it doesn't list are KEPT. This script alone is
# therefore not enough for real PACS data; scripts/deidentify_and_deface.py follows it with an
# allowlist pass and a leak scan against the original identifiers. Standalone, run
#   python scripts/check_deidentified_dicom.py OUTPUT_DIR --originals INPUT_DIR
#
# This removes identifiers from the DICOM HEADERS only. It does NOT deface the images, does not
# touch burned-in text in pixel data, and keeps free-text Study/Series descriptions and protocol
# names (astril classifies series by them). Check those with scripts/check_deidentified_dicom.py
# before sharing anything, and see the README's PHI section.
#
# Compressed input (e.g. JPEG Lossless PACS exports): CTP can fail to parse dates in some
# encapsulated files and silently BLANK them; the checker flags studies left without a date.
# scripts/deidentify_and_deface.py decompresses before calling this script, which avoids it.
#
# Requirements: python3 (stdlib only; writes the anonymizer script); DicomAnonymizerTool (unzip DicomAnonymizerTool/ out of
# https://github.com/johnperry/DicomAnonymizerTool/raw/master/products/DicomAnonymizerTool-installer.jar)
# and a Java runtime new enough for it (the 2025-10 release needs Java 25+).
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: deidentify_dicom_ctp.sh -i INPUT_DIR -o OUTPUT_DIR -p PSEUDONYM [options]

  -i DIR   One patient's DICOM files (all scans), any layout; searched recursively.
  -o DIR   Output directory (must not exist). Mirrors the input layout.
  -p ID    Pseudonym written to PatientName and PatientID (e.g. TEST001). Must not be derived
           from any real identifier.
  -d DAYS  Date shift in days for this patient (negative = earlier). Default: random in
           [-3650, -365]. Use the SAME value for every batch of the same patient.
  -k       Keep private (odd-group) tags. Some vendors keep acquisition details there (e.g.
           Siemens mosaic/diffusion info dcm2niix needs) -- but private tags can also hold PHI.
  -t DIR   DicomAnonymizerTool directory (default: $DAT_HOME or ~/opt/DicomAnonymizerTool).
  -j JAVA  Java executable (default: $DAT_JAVA, else ~/opt/jre25/bin/java, else java on PATH).
  -n N     Parallel threads (default: 4).

The date offset is a re-identification key: it is written to OUTPUT_DIR.deid_key.txt, NEXT TO
(not inside) the output directory. Keep it, and never share it with the de-identified data.
EOF
    exit "${1:-1}"
}

in_dir="" out_dir="" pseudonym="" date_inc="" keep_private=0 threads=4
dat_dir="${DAT_HOME:-$HOME/opt/DicomAnonymizerTool}"
java_bin="${DAT_JAVA:-}"
while getopts "i:o:p:d:kt:j:n:h" opt; do
    case "$opt" in
        i) in_dir=$OPTARG ;;
        o) out_dir=$OPTARG ;;
        p) pseudonym=$OPTARG ;;
        d) date_inc=$OPTARG ;;
        k) keep_private=1 ;;
        t) dat_dir=$OPTARG ;;
        j) java_bin=$OPTARG ;;
        n) threads=$OPTARG ;;
        h) usage 0 ;;
        *) usage ;;
    esac
done
[ -n "$in_dir" ] && [ -n "$out_dir" ] && [ -n "$pseudonym" ] || usage

die() { echo "ERROR: $*" >&2; exit 1; }
[ -d "$in_dir" ] || die "input directory not found: $in_dir"
[ -e "$out_dir" ] && die "output directory already exists: $out_dir"
[[ "$pseudonym" =~ ^[A-Za-z0-9_-]+$ ]] || die "pseudonym may only contain letters, digits, _ and -"
[ -f "$dat_dir/DAT.jar" ] || die "DAT.jar not found in $dat_dir (set -t or DAT_HOME)"
if [ -z "$java_bin" ]; then
    if [ -x "$HOME/opt/jre25/bin/java" ]; then java_bin="$HOME/opt/jre25/bin/java"; else java_bin=java; fi
fi
java_major=$("$java_bin" -version 2>&1 | sed -n 's/.*version "\([0-9]*\).*/\1/p' | head -1)
[ "${java_major:-0}" -ge 25 ] || die "$java_bin is Java ${java_major:-?}; DicomAnonymizerTool needs Java 25+ (set -j or DAT_JAVA)"
if [ -z "$date_inc" ]; then
    date_inc=$(( -365 - RANDOM % 3286 ))
fi
[[ "$date_inc" =~ ^-?[0-9]+$ ]] || die "-d must be an integer number of days"

in_abs=$(cd "$in_dir" && pwd)
mkdir -p "$(dirname "$out_dir")"
out_abs="$(cd "$(dirname "$out_dir")" && pwd)/$(basename "$out_dir")"
key_file="$out_abs.deid_key.txt"

# Build this run's anonymizer script: CTP's default profile with the overrides written INTO the
# script. (DAT's -e/-p command-line overrides are NOT used: DAT applies them to a copy of the
# script's properties that its worker threads don't read, so they're silently ignored.)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
python3 - "$dat_dir/dicom-anonymizer.script" "$work/anonymizer.script" "$date_inc" "$pseudonym" "$keep_private" <<'PY'
import sys
import xml.etree.ElementTree as ET

src, dst, date_inc, pseudonym, keep_private = sys.argv[1:]
tree = ET.parse(src)
root = tree.getroot()

params = {p.get("t"): p for p in root.findall("p")}
for name, value in (("DATEINC", date_inc), ("PSEUDONYM", pseudonym)):
    if name not in params:
        params[name] = ET.Element("p", t=name)
        root.insert(0, params[name])
    params[name].text = value

shift_date = "@incrementdate(this,@DATEINC)"
overrides = {
    "00100010": ("PatientName", "@param(@PSEUDONYM)"),
    "00100020": ("PatientID", "@param(@PSEUDONYM)"),
    "00100030": ("PatientBirthDate", "@remove()"),
    "00080050": ("AccessionNumber", "@remove()"),  # the default profile only hashes it
    "00080020": ("StudyDate", shift_date),
    "00080021": ("SeriesDate", shift_date),
    "00080022": ("AcquisitionDate", shift_date),
    "00080023": ("ContentDate", shift_date),
    "0008002a": ("AcquisitionDatetime", "@remove()"),  # astril falls back to Date + Time
    "00080030": ("StudyTime", "@keep()"),
    "00080031": ("SeriesTime", "@keep()"),
    "00080032": ("AcquisitionTime", "@keep()"),
    "00080033": ("ContentTime", "@keep()"),
    "00080070": ("Manufacturer", "@keep()"),
    "00081090": ("ManufacturerModelName", "@keep()"),
    "00181030": ("ProtocolName", "@keep()"),
    # The default profile leaves these disabled or unlisted, i.e. passed through untouched, and
    # PACS exports fill them: Visage puts pre-correction values (accession, real
    # AttributeModificationDateTime) in OriginalAttributesSequence, and MRNs / accession numbers
    # turn up in the ClinicalTrial* elements.
    "04000561": ("OriginalAttributesSequence", "@remove()"),
    "04000550": ("ModifiedAttributesSequence", "@remove()"),
    "0018a001": ("ContributingEquipmentSequence", "@remove()"),
    **{t: (n, "@remove()") for t, n in (
        ("00120010", "ClinicalTrialSponsorName"), ("00120020", "ClinicalTrialProtocolID"),
        ("00120021", "ClinicalTrialProtocolName"), ("00120030", "ClinicalTrialSiteID"),
        ("00120031", "ClinicalTrialSiteName"), ("00120040", "ClinicalTrialSubjectID"),
        ("00120042", "ClinicalTrialSubjectReadingID"), ("00120050", "ClinicalTrialTimePointID"),
        ("00120051", "ClinicalTrialTimePointDescription"), ("00120060", "CoordinatingCenterName"),
        ("00120071", "ClinicalTrialSeriesID"), ("00120072", "ClinicalTrialSeriesDescription"),
        ("00120081", "ClinicalTrialProtocolEthicsCommitteeName"),
        ("00120082", "ClinicalTrialProtocolEthicsCommitteeApprovalNumber"))},
}
elements = {e.get("t"): e for e in root.findall("e")}
for tag, (name, script) in overrides.items():
    e = elements.get(tag)
    if e is None:
        e = ET.SubElement(root, "e", t=tag, n=name)
    e.set("en", "T")
    e.text = script

if keep_private == "1":
    for r in root.findall("r"):
        if r.get("t") == "privategroups":
            r.set("en", "F")
tree.write(dst)
PY

echo "De-identifying $in_abs -> $out_abs as '$pseudonym' (date shift $date_inc days, private tags $([ $keep_private -eq 1 ] && echo kept || echo removed))"
(
    cd "$work"   # DAT reads its default lookup table / filter from the working directory
    "$java_bin" -jar "$dat_dir/DAT.jar" \
        -in "$in_abs" -out "$out_abs" \
        -da "$work/anonymizer.script" \
        -n "$threads"
) > "$work/dat.log" 2>&1 || { cat "$work/dat.log" >&2; die "DicomAnonymizerTool failed"; }

n_in=$(find "$in_abs" -type f | wc -l)
n_out=$(find "$out_abs" -type f 2>/dev/null | wc -l)
umask 077
cat > "$key_file" <<EOF
# astril-nf de-identification key -- KEEP PRIVATE, never share with the de-identified data.
input=$in_abs
output=$out_abs
pseudonym=$pseudonym
date_shift_days=$date_inc
private_tags_kept=$keep_private
date=$(date -Iseconds)
EOF
echo "Done: $n_out of $n_in input files written. Key (keep private): $key_file"
[ "$n_out" -eq "$n_in" ] || echo "NOTE: $(( n_in - n_out )) input file(s) produced no output (non-DICOM, or rejected by the anonymizer). See the DAT log above if this is unexpected." >&2
echo "Next: python scripts/check_deidentified_dicom.py $out_abs --originals $in_abs"
