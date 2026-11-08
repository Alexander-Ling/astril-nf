"""DICOM header rules shared by deidentify_and_deface.py and check_deidentified_dicom.py.

CTP's default profile is a DENYLIST with "remove unspecified elements" off: anything it doesn't
list, or lists but leaves disabled, passes through untouched. Real PACS exports carry identifiers
in such places, e.g. Visage's OriginalAttributesSequence (the pre-correction AccessionNumber etc.,
stamped with real AttributeModificationDateTime values) and ClinicalTrialProtocolID/SiteName
holding the MRN/accession. So, after CTP:

  scrub()      keeps only an ALLOWLIST of what astril, dcm2niix and mask_face use, recursively
  harvest()    collects the patient's real identifiers from the ORIGINAL headers
  find_leaks() searches every remaining header value for any of them

Nothing here prints values: reports name the tag path only, never its content.
"""
import copy
import re

from pydicom.multival import MultiValue

# Shifted by CTP (one per-patient offset); the only dates allowed to remain.
SHIFTED_DATES = {"StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate"}

# Top level: whole groups 0018 (acquisition), 0020 (geometry/UIDs/numbers), 0028 (pixel module),
# 7FE0 (pixels), minus the denylisted elements and VRs below; plus these elements from elsewhere.
KEEP_GROUPS = {0x0018, 0x0020, 0x0028, 0x7FE0}
KEEP_ELEMENTS = SHIFTED_DATES | {
    "SpecificCharacterSet", "ImageType", "SOPClassUID", "SOPInstanceUID",
    "StudyTime", "SeriesTime", "AcquisitionTime", "ContentTime",
    "Modality", "Manufacturer", "ManufacturerModelName", "StudyDescription", "SeriesDescription",
    "AcquisitionContrast", "PixelPresentation", "VolumetricProperties", "VolumeBasedCalculationTechnique",
    "ComplexImageComponent", "DerivationCodeSequence",
    "PatientName", "PatientID", "PatientSex", "PatientAge", "PatientSize", "PatientWeight",
    "PatientIdentityRemoved", "DeidentificationMethod", "DeidentificationMethodCodeSequence",
}
KEEP_FILE_META = {"FileMetaInformationVersion", "MediaStorageSOPClassUID", "MediaStorageSOPInstanceUID",
                  "TransferSyntaxUID", "ImplementationClassUID", "ImplementationVersionName"}
# Identifying elements inside the kept groups.
DROP_ELEMENTS = {
    "DeviceSerialNumber", "DeviceUID", "PlateID", "GeneratorID", "CassetteID", "GantryID", "DetectorID",
    "ContributingEquipmentSequence", "AcquisitionProtocolDescription", "AcquisitionDeviceProcessingDescription",
    # anywhere, including nested items:
    "AccessionNumber", "PatientBirthDate", "OtherPatientIDs", "OtherPatientIDsSequence", "OtherPatientNames",
    "IssuerOfPatientID", "InstitutionName", "InstitutionAddress", "InstitutionalDepartmentName", "StationName",
    "OriginalAttributesSequence", "ModifiedAttributesSequence", "NonconformingModifiedAttributesSequence",
    "RequestAttributesSequence", "ReferencedPatientSequence", "ReferencedStudySequence",
    "RequestedProcedureID", "ScheduledProcedureStepID", "PerformedProcedureStepID", "StudyID",
    "PlacerOrderNumberImagingServiceRequest", "FillerOrderNumberImagingServiceRequest", "AdmissionID",
}
# Value representations dropped wherever they occur (except the kept names/dates at top level):
# dates, person names, long free text and unknown/private-like content.
DROP_VRS = {"DA", "DT", "PN", "LT", "ST", "UT", "UN"}
# Not scanned for leaks: binary and numeric VRs (an MRN can't hide in them, and digit runs in
# decimals would give false matches).
BINARY_VRS = {"OB", "OW", "OF", "OD", "OL", "OV", "FL", "FD", "SL", "SS", "SV", "UL", "US", "UV", "AT", "DS", "IS"}


def _keyword(elem):
    return elem.keyword or f"({elem.tag.group:04X},{elem.tag.element:04X})"


def scrub(ds, keep_private=False):
    """Remove everything outside the allowlist, recursively, in place. Returns removed tag paths.

    keep_private keeps top-level private tags (deidentify_dicom_ctp.sh -k): some vendors keep
    acquisition details dcm2niix needs there, but they can hold PHI too.
    """
    removed = []
    for elem in list(ds.file_meta) if hasattr(ds, "file_meta") else []:
        if elem.keyword not in KEEP_FILE_META and elem.keyword != "FileMetaInformationGroupLength":
            del ds.file_meta[elem.tag]
            removed.append(f"file meta {_keyword(elem)}")
    _scrub(ds, "", True, removed, keep_private)
    if ds.get("PatientAge"):   # HIPAA: ages over 89 are identifying; report them as 90
        m = re.fullmatch(r"(\d{3})Y", str(ds.PatientAge))
        if not m or int(m.group(1)) > 89:
            ds.PatientAge = "090Y" if m else ""
    ds.PatientIdentityRemoved = "YES"
    return removed


def _scrub(ds, prefix, top, removed, keep_private=False):
    for elem in list(ds):
        kw = elem.keyword
        if top and keep_private and elem.tag.is_private:
            continue
        if top:
            keep = (kw in KEEP_ELEMENTS or elem.tag.group in KEEP_GROUPS) and kw not in DROP_ELEMENTS \
                   and (elem.VR not in DROP_VRS or kw in SHIFTED_DATES or kw == "PatientName")
        else:
            keep = not elem.tag.is_private and kw not in DROP_ELEMENTS and elem.VR not in DROP_VRS
        if not keep:
            del ds[elem.tag]
            removed.append(prefix + _keyword(elem))
        elif elem.VR == "SQ":
            for i, item in enumerate(elem.value):
                _scrub(item, f"{prefix}{_keyword(elem)}[{i}] > ", False, removed)


def _texts(ds, prefix=""):
    """(tag path, text) for every scannable value, recursively, file meta included."""
    elems = list(ds.file_meta) if prefix == "" and hasattr(ds, "file_meta") else []
    for elem in elems + list(ds):
        path = prefix + _keyword(elem)
        if elem.VR == "SQ":
            for i, item in enumerate(elem.value or []):
                yield from _texts(item, f"{path}[{i}] > ")
        elif elem.VR not in BINARY_VRS and elem.value not in (None, b"", ""):
            v = elem.value
            if isinstance(v, bytes):
                v = v.decode("latin-1", "replace")
            yield path, "\\".join(map(str, v)) if isinstance(v, (list, tuple, MultiValue)) else str(v)


ID_KEYWORDS = {"PatientID", "OtherPatientIDs", "AccessionNumber", "StudyID", "RequestedProcedureID",
               "ScheduledProcedureStepID", "PerformedProcedureStepID", "AdmissionID",
               "PlacerOrderNumberImagingServiceRequest", "FillerOrderNumberImagingServiceRequest",
               "ClinicalTrialProtocolID", "ClinicalTrialSiteID", "ClinicalTrialSiteName", "ClinicalTrialSubjectID",
               "ClinicalTrialSubjectReadingID", "ClinicalTrialTimePointID"}
UID_KEYWORDS = {"StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID", "FrameOfReferenceUID"}
NAME_STOPWORDS = {"MD", "PHD", "DR", "JR", "SR", "II", "III", "IV", "MR", "MRS", "MS", "DO", "RN", "RT"}


class Identifiers:
    """The patient's real identifiers, collected from the original (pre-de-identification) headers."""

    def __init__(self):
        self.ids, self.names, self.dates, self.uids = set(), set(), set(), set()

    def harvest(self, ds):
        for elem in ds:
            kw, v = elem.keyword, elem.value
            if elem.VR == "SQ":
                for item in v or []:
                    self.harvest(item)
                continue
            if v in (None, "", b""):
                continue
            values = [str(x) for x in v] if isinstance(v, (list, tuple, MultiValue)) else [str(v)]
            for s in values:
                s = s.strip()
                if kw in ID_KEYWORDS and len(s) >= 4 and any(c.isdigit() for c in s):
                    self.ids.add(s)
                elif elem.VR == "PN":
                    self.names.update(w for w in re.split(r"[\^\s,.=]+", s.upper())
                                      if len(w) >= 3 and w not in NAME_STOPWORDS)
                elif elem.VR in ("DA", "DT") and re.match(r"\d{8}", s):
                    self.dates.add(s[:8])
                elif kw in UID_KEYWORDS:
                    self.uids.add(s)

    def add_id(self, text):
        if len(text) >= 4 and any(c.isdigit() for c in text):
            self.ids.add(text)

    def _patterns(self):
        pats = []
        if self.ids:
            alt = "|".join(re.escape(s) for s in sorted(self.ids, key=len, reverse=True))
            pats.append(("an original ID (MRN/accession/study ID)", re.compile(rf"(?<![A-Za-z0-9])(?:{alt})(?![A-Za-z0-9])", re.I)))
        if self.names:
            alt = "|".join(re.escape(s) for s in sorted(self.names, key=len, reverse=True))
            pats.append(("an original person-name component", re.compile(rf"(?<![A-Za-z])(?:{alt})(?![A-Za-z])", re.I)))
        if self.dates:
            forms = set()
            for d in self.dates:
                y, m, dd = d[:4], d[4:6], d[6:8]
                forms |= {d, f"{y}-{m}-{dd}", f"{y}.{m}.{dd}", f"{m}/{dd}/{y}", f"{y}/{m}/{dd}"}
            alt = "|".join(re.escape(s) for s in sorted(forms))
            # No right-hand boundary: DT values and timestamp-style UIDs continue with the time.
            pats.append(("an original (unshifted) date", re.compile(rf"(?<!\d)(?:{alt})")))
        return pats

    def find_leaks(self, ds, patterns=None):
        """[(tag path, what it matched)] -- never the value itself."""
        patterns = patterns if patterns is not None else self._patterns()
        leaks = []
        for path, text in _texts(ds):
            if text in self.uids:
                leaks.append((path, "an original (unhashed) UID"))
                continue
            for what, rx in patterns:
                if rx.search(text):
                    leaks.append((path, what))
                    break
        return leaks

    def find_leaks_in_text(self, text, patterns=None):
        patterns = patterns if patterns is not None else self._patterns()
        return [what for what, rx in patterns if rx.search(text)]


def structural_problems(ds):
    """Tag paths that the allowlist would remove: what the checker flags, without needing originals.
    Top-level private tags aren't included (the checker lists them separately)."""
    return [p for p in scrub(copy.deepcopy(ds), keep_private=True) if not p.startswith("file meta")]
