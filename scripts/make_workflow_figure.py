"""Render the astril-nf Cirro workflow schematic (Nature Methods double-column style).

Writes images/astril_nf_cirro_workflow.{pdf,svg,png}. All geometry is in millimetres.

    python scripts/make_workflow_figure.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

CH = 46.0            # height of panel c (bottom of the figure)
W, H = 180.0, 164.0 + CH  # figure size, mm (double-column width)
OFF = 28.0 + CH      # vertical offset of panel a above the bottom

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "pdf.fonttype": 42,      # editable text in Illustrator
    "svg.fonttype": "none",
})

INK = "#1f1f1f"
INK2 = "#575757"
RULE = "#8a8a8a"
PHI_BAND = "#fbeeec"
SAFE_BAND = "#ecf6ef"
PHI_INK = "#a23533"
SAFE_INK = "#1d6b3a"
MONO = "Consolas"
DASH = (0, (3, 1.5))

# Stage colours (validated categorical palette; identity only, text stays in ink)
C_ORG, C_PLAN, C_CONV, C_PRE, C_SEG, C_QUANT = (
    "#2a78d6", "#eb6834", "#6250d6", "#e87ba4", "#eda100", "#1baf7a")


def tint(color, a=0.14):
    r, g, b = to_rgb(color)
    return (1 - a + a * r, 1 - a + a * g, 1 - a + a * b)


fig = plt.figure(figsize=(W / 25.4, H / 25.4))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")


def box(x, y, w, h, fc="white", ec=INK, lw=0.6, ls="-", r=1.2, z=2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc=fc, ec=ec, lw=lw, ls=ls, zorder=z))


def text(x, y, s, size=5.5, color=INK, weight="normal", ha="center", va="center",
         style="normal", family=None, z=5, **kw):
    ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, ha=ha, va=va,
            fontstyle=style, family=family, zorder=z, linespacing=1.15, **kw)


def arrow(p0, p1, color=INK, lw=0.6, ls="-", head=5, z=4):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=head, color=color,
                                 lw=lw, ls=ls, shrinkA=0, shrinkB=0, zorder=z))


def phi_pill(xc, yc, w=11.6, h=3.2):
    box(xc - w / 2, yc - h / 2, w, h, fc=PHI_INK, ec="white", lw=0.5, r=1.0, z=6)
    text(xc, yc, "PHI Caution!", size=4.6, color="white", weight="bold", z=7)


def stop_bars(x, y, half=2.6):
    for dx in (-0.6, 0.6):
        ax.plot([x + dx, x + dx], [y - half, y + half], color=INK, lw=0.9, zorder=4)


# ---------------------------------------------------------------- panel a
text(1.5, 133.5 + OFF, "a", size=8, weight="bold", ha="left")

n, bw, x_left, x_right = 6, 25.0, 10.0, 178.0
pitch = (x_right - x_left - bw) / (n - 1)
xs = [x_left + i * pitch for i in range(n)]
cx = [x + bw / 2 for x in xs]

band_lo, band_hi = 60.5 + OFF, 131.0 + OFF
split = (xs[4] + xs[3] + bw) / 2  # Preprocess takes whole-head NIfTI, so it sits on the PHI side
ax.add_patch(Rectangle((7.0, band_lo), split - 7.0, band_hi - band_lo, fc=PHI_BAND, ec="none", zorder=0))
ax.add_patch(Rectangle((split, band_lo), 179.8 - split, band_hi - band_lo, fc=SAFE_BAND, ec="none", zorder=0))
ax.plot([split, split], [band_lo, band_hi], color=RULE, lw=0.5, ls=(0, (2, 1.5)), zorder=1)
text(8.5, 128.6 + OFF, "Identifiable (PHI): on Cirro, de-identified face-free DICOMs only",
     size=5.5, color=PHI_INK, weight="bold", ha="left")
text(split + 1.5, 128.6 + OFF, "Skull-stripped, face-free: real data permitted",
     size=5.5, color=SAFE_INK, weight="bold", ha="left")

# Row labels
for y, s in [(77.0, "Stage"), (47.0, "User step")]:
    text(3.6, y + OFF, s, size=5.5, color=INK2, rotation=90, weight="bold")

# Entry-point boxes, grouped in an outlined container so they read apart from the stages
cont_x0, cont_x1 = 8.3, 179.7
cont_y0, cont_y1 = 96.0 + OFF, 124.0 + OFF
CIRRO_FILL = C_ORG  # same bright blue as the Organize stage
box(cont_x0, cont_y0, cont_x1 - cont_x0, cont_y1 - cont_y0, fc=CIRRO_FILL, ec=INK, lw=1.0, r=2.0, z=1.5)
text((cont_x0 + cont_x1) / 2, cont_y1 - 3.0, "Cirro pipelines (entry points)", size=7.5, weight="bold",
     color="white")
entries = [
    ("Organize DICOM", "DICOM upload,\nany folder structure"),
    ("Run from patient\nmetadata", "Organize run\n+ form: metadata table"),
    ("Run from\nconversion plan", "Plan run + form: organized\nDICOM, edited plan"),
    ("Run from NIfTI", "NIfTI upload\nor earlier run"),
    ("Run from\npreprocessed images", "upload_preprocessed/\nor earlier run"),
    ("Quantify\nsegmentation masks", "Mask upload\nor earlier run"),
]
ey, eh = 98.0 + OFF, 19.0
for i, (name, inp) in enumerate(entries):
    recommended = i == 4
    box(xs[i], ey, bw, eh, ec=SAFE_INK if recommended else INK, lw=1.2 if recommended else 0.6)
    text(cx[i], ey + eh - 5.2, name, size=6, weight="bold")
    text(cx[i], ey + 4.6, inp, size=4.8, color=INK2)
text(cx[4], ey + eh / 2 - 0.4, "Entry point for real data", size=4.8, color=SAFE_INK, weight="bold")

# Stage boxes
stages = [
    ("0  Organize", C_ORG, ["organized_dicoms/", "dicom_index.csv", "patient_metadata_", "  blank.csv"], ""),
    ("1a  Plan conversion", C_PLAN, ["conversion_plan.csv"], "Series classified;\nNIfTI paths proposed"),
    ("1b  Convert", C_CONV, ["nifti_out/"], "{patient}/{exam}/\n{label}.nii.gz"),
    ("2  Preprocess", C_PRE, ["preprocessed_library/", "upload_preprocessed/", "qc/*.pdf"], "Co-register, HD-BET,\nnormalize"),
    ("3  Segment", C_SEG, ["*_GBM-seg.nii.gz", "segmentation_", "  provenance.json"], "GBM_seg_v2 or\ncustom model"),
    ("3b  Quantify", C_QUANT, ["volumes.tsv"], "Per-class volumes (mm³);\nCirro table viewer"),
]
PHI_STAGES = {0, 1, 2, 3}  # stages whose inputs or outputs carry PHI
sy, sh = 64.0 + OFF, 27.0
for i, (title, col, files, note) in enumerate(stages):
    box(xs[i], sy, bw, sh, fc=tint(col), ec=col, lw=0.8)
    ax.add_patch(Rectangle((xs[i] + 0.4, sy + sh - 2.0), bw - 0.8, 1.2, fc=col, ec="none", zorder=3))
    text(xs[i] + 1.8, sy + sh - 5.2, title, size=6, weight="bold", ha="left")
    fy = sy + sh - 10.2
    for f in files:
        text(xs[i] + 1.8, fy, f, size=4.8, family=MONO, ha="left")
        fy -= 2.9
    if note:
        text(xs[i] + 1.8, sy + 2.2, note, size=4.8, color=INK2, ha="left", va="bottom")
    arrow((cx[i], cont_y0), (cx[i], sy + sh), lw=0.6)
    if i in PHI_STAGES:
        phi_pill(xs[i] + bw - 5.0, sy + sh, w=11.0)

# Automatic chaining between stages
mid_y = sy + sh / 2
for i in range(1, n - 1):
    arrow((xs[i] + bw + 0.3, mid_y), (xs[i + 1] - 0.3, mid_y), lw=1.4, head=6)
stop_bars((xs[0] + bw + xs[1]) / 2, mid_y)

# User steps between columns: (left column, tag, body, kind, PHI)
users = [
    (0, "Required", "Fill patientID and\nday0Date; upload\nas table", "required", True),
    (1, "Optional", "Stop after plan; edit\nselected_for_conversion,\nproposed_nifti_path", "optional", True),
    (4, "Optional", "Stop after segment;\ncorrect masks;\nupload", "optional", False),
]
uy, uh, uw = 38.5 + OFF, 17.0, 26.0
for i, tag, body, kind, phi in users:
    m = (cx[i] + cx[i + 1]) / 2
    ux = m - uw / 2
    if kind == "required":
        box(ux, uy, uw, uh, fc=tint(C_ORG), ec=C_ORG, lw=1.4)
        ax.add_patch(Rectangle((ux + 0.5, uy + uh - 2.1), uw - 1.0, 1.2, fc=C_ORG, ec="none", zorder=3))
        text(m, uy + uh - 4.6, tag, size=6, weight="bold")
        text(m, uy + 7.0, body, size=5.0, weight="bold")
        acol, alw, als = C_ORG, 1.0, "-"
    else:
        box(ux, uy, uw, uh, fc="#f4f4f2", ec=INK2, lw=0.6, ls=DASH)
        text(m, uy + uh - 2.8, tag, size=5.2, weight="bold", color=INK2)
        text(m, uy + 7.0, body, size=4.8)
        acol, alw, als = INK2, 0.6, DASH
    arrow((m - 8.0, sy), (m - 8.0, uy + uh), lw=alw, ls=als, color=acol)
    arrow((m + 8.0, uy + uh), (m + 8.0, sy), lw=alw, ls=als, color=acol)
    if phi:
        phi_pill(m, uy)

# Legend (two lines)
ly1, ly2 = 33.0 + OFF, 28.5 + OFF
arrow((9.0, ly1), (17.0, ly1), lw=1.4, head=6)
text(18.5, ly1, "Automatic chaining to the next stage (until ‘Stop after’)", size=5, ha="left")
arrow((76.0, ly1), (84.0, ly1), lw=0.6)
text(85.5, ly1, "Run input", size=5, ha="left")
arrow((100.0, ly1), (108.0, ly1), lw=0.6, ls=DASH, color=INK2)
text(109.5, ly1, "Optional manual step", size=5, ha="left")
stop_bars(140.0, ly1, half=1.8)
text(143.5, ly1, "Run always stops (Organize)", size=5, ha="left")
phi_pill(15.0, ly2)
text(22.5, ly2, "Inputs or outputs contain PHI unless the DICOMs were de-identified and defaced first",
     size=5, ha="left")
text(118.0, ly2, "Box colours identify stages (same in a and b)", size=5, color=INK2, ha="left")

# ---------------------------------------------------------------- panel b
by, bh = 2.0 + CH, 46.0
top = by + bh
text(1.5, top + 4.5, "b", size=8, weight="bold", ha="left")
text(9.0, top + 4.5, "Recommended route for real patient data", size=6, weight="bold", ha="left")

loc_x0, loc_x1 = 9.0, 104.0
opt_x0, opt_x1 = 113.0, 179.0
box(loc_x0, by, loc_x1 - loc_x0, bh, fc=PHI_BAND, ec=PHI_INK, lw=0.6, r=1.5, z=1)
text(loc_x0 + 2, top - 3.0, "Run locally with the astril CLI (identifiable data stays on site)",
     size=5.2, weight="bold", color=PHI_INK, ha="left")

chip_w, chip_h = 11.0, 3.1


def step_chip(x, y, label, col, dashed=False, label_color=INK):
    if dashed:
        box(x, y - chip_h / 2, chip_w, chip_h, fc="#f4f4f2", ec=INK2, lw=0.5, ls=DASH, r=0.8, z=3)
    else:
        box(x, y - chip_h / 2, chip_w, chip_h, fc=tint(col), ec=col, lw=0.8, r=0.8, z=3)
    text(x + chip_w / 2, y, label, size=4.8, weight="bold", color=label_color)


# (chip label, colour, step text, kind) -- kind: cmd | required | optional
local_steps = [
    ("0", C_ORG, "python -m astril.preprocess organize_dicoms", "cmd"),
    ("0", C_ORG, "python -m astril.preprocess create_patient_metadata --index", "cmd"),
    ("Required", C_ORG, "Fill patientID and day0Date in the metadata table", "required"),
    ("1a", C_PLAN, "python -m astril.preprocess plan_dicom_to_nifti_conversion", "cmd"),
    ("Optional", INK2, "Review/edit the conversion plan", "optional"),
    ("1b", C_CONV, "python -m astril.preprocess convert_dicom_plan", "cmd"),
    ("2", C_PRE, "python -m astril.preprocess_brain_mris", "cmd"),
]
chip_x = loc_x0 + 2.0
cmd_x = chip_x + chip_w + 2.0
pill_x = loc_x1 - 7.6
ry = top - 7.5
for label, col, step, kind in local_steps:
    if kind == "required":
        box(loc_x0 + 1.0, ry - 1.85, loc_x1 - loc_x0 - 2.0, 3.7, fc=tint(C_ORG, 0.22), ec=C_ORG, lw=1.0, r=0.8, z=2)
    step_chip(chip_x, ry, label, col, dashed=kind == "optional")
    if kind == "cmd":
        text(cmd_x, ry, step, size=4.8, family=MONO, ha="left")
    else:
        text(cmd_x, ry, step, size=5.0, weight="bold" if kind == "required" else "normal",
             color=INK if kind == "required" else INK2, ha="left")
    phi_pill(pill_x, ry, w=11.0, h=2.9)
    last_y = ry
    ry -= 5.4

# Fork after preprocessing: Cirro (A) or finish locally (B)
a_y0, a_y1 = 26.0 + CH, top
b_y0, b_y1 = by, 23.0 + CH
a_mid = (a_y0 + a_y1) / 2
fork_x = 108.5
ax.plot([loc_x1, fork_x], [last_y, last_y], color=SAFE_INK, lw=1.0, zorder=4)
ax.plot([fork_x, fork_x], [last_y, a_mid], color=SAFE_INK, lw=1.0, zorder=4)
ax.add_patch(plt.Circle((fork_x, last_y), 0.7, color=SAFE_INK, zorder=5))
arrow((fork_x, a_mid), (opt_x0, a_mid), lw=1.0, color=SAFE_INK, head=6)
arrow((fork_x, last_y), (opt_x0, last_y), lw=1.0, color=SAFE_INK, head=6)
text(fork_x - 1.4, (last_y + a_mid) / 2, "choose one", size=4.6, color=SAFE_INK,
     weight="bold", rotation=90)

for y0, y1 in ((a_y0, a_y1), (b_y0, b_y1)):
    box(opt_x0, y0, opt_x1 - opt_x0, y1 - y0, fc=SAFE_BAND, ec=SAFE_INK, lw=0.6, r=1.5, z=1)
ox = opt_x0 + 2.0
ocmd_x = ox + chip_w + 2.0

# Option A: upload the face-free subset to Cirro
text(ox, a_y1 - 3.0, "Option A: Cirro, Run from preprocessed images",
     size=5.2, weight="bold", color=SAFE_INK, ha="left")
r1 = a_y1 - 8.0
a_chip_w = 16.0  # matches the Segment chip below, so the arrow joins their centres
box(ox, r1 - chip_h / 2, a_chip_w, chip_h, fc=tint(SAFE_INK), ec=SAFE_INK, lw=0.8, r=0.8, z=3)
text(ox + a_chip_w / 2, r1, "Upload", size=4.8, weight="bold", color=SAFE_INK)
text(ox + a_chip_w + 2.0, r1, "Preprocessed Image Directory\n(upload as a Files dataset)",
     size=4.8, color=SAFE_INK, weight="bold", ha="left")


def stage_chip(x, yc, label, col, w):
    box(x, yc - 2.8, w, 5.6, fc=tint(col), ec=col, lw=0.8, r=1.0, z=3)
    text(x + w / 2, yc, label, size=5.2, weight="bold")
    return x, x + w


r2 = a_y0 + 5.5
c1 = stage_chip(ox, r2, "3  Segment", C_SEG, 16.0)
c2 = stage_chip(c1[1] + 5.0, r2, "3b  Quantify", C_QUANT, 16.0)
arrow((c1[1] + 0.4, r2), (c2[0] - 0.4, r2), lw=1.2, head=5)
text(c2[1] + 2.0, r2, "volumes.tsv", size=4.6, family=MONO, color=INK2, ha="left")
arrow((ox + a_chip_w / 2, r1 - chip_h / 2), (ox + a_chip_w / 2, r2 + 2.8), lw=0.8)

# Option B: segment and quantify locally, then upload results
text(ox, b_y1 - 3.0, "Option B: finish locally, then upload results",
     size=5.2, weight="bold", color=SAFE_INK, ha="left")
b_steps = [
    ("Once", INK2, "astril-download-models", "setup"),
    ("3", C_SEG, "python -m astril.segment --model_family GBM_seg_v2", "cmd"),
    ("3b", C_QUANT, "python -m astril.quantify_volumes", "cmd"),
    ("Upload", SAFE_INK, "Preprocessed Images + Segmentations\nto BTC Staging/Jamboree", "upload"),
]
ry = b_y1 - 6.6
for label, col, step, kind in b_steps:
    if kind == "upload":
        step_chip(ox, ry, label, col, label_color=SAFE_INK)
        text(ocmd_x, ry, step, size=4.8, color=SAFE_INK, weight="bold", ha="left")
    else:
        step_chip(ox, ry, label, col, dashed=kind == "setup")
        text(ocmd_x, ry, step, size=4.4, family=MONO, ha="left")
    ry -= 3.6

# ---------------------------------------------------------------- panel c
c_top = CH - 1.0
text(1.5, c_top, "c", size=8, weight="bold", ha="left")
text(9.0, c_top, "Filling in the patient metadata table (patient_metadata_blank.csv)",
     size=6, weight="bold", ha="left")

# Dummy table: (header, width mm, role) -- role: generated | fill | dicom
cols = [
    ("Directory", 32.0, "generated"),
    ("patientID", 15.0, "fill"),
    ("patientName", 18.0, "dicom"),
    ("dicomPatientID", 16.0, "dicom"),
    ("day0Date", 17.0, "fill"),
]
rows = [
    ["Patient_8800123_3f9a1c2b7d", "GBM001", "jane doe", "8800123", "01/15/2024"],
    ["Patient_8800456_a81e04c6f2", "GBM002", "john smith", "8800456", "03/02/2024"],
    ["Patient_8800789_5c0d9e17b4", "", "maria garcia", "8800789", ""],
]
t_x0, rh = 9.0, 4.6
hdr_y = c_top - 13.0          # bottom of the header row
col_x = [t_x0]
for _, w, _ in cols:
    col_x.append(col_x[-1] + w)
t_x1 = col_x[-1]
FILL_BG = tint(C_ORG, 0.30)


def cell(x, y, w, fc, ec=RULE, lw=0.4, ls="-"):
    ax.add_patch(Rectangle((x, y), w, rh, fc=fc, ec=ec, lw=lw, ls=ls, zorder=2))


# Role tags above the header
tag_y = hdr_y + rh + 2.6
text(col_x[0] + 1.0, tag_y, "Generated; do not edit", size=4.8, color=INK2, ha="left")
for j in (1, 4):
    text((col_x[j] + col_x[j + 1]) / 2, tag_y, "You fill in", size=5.0, weight="bold", color=INK)
    ax.plot([col_x[j] + 0.6, col_x[j + 1] - 0.6], [tag_y - 1.5, tag_y - 1.5], color=C_ORG, lw=1.2, zorder=3)
text(col_x[2] + 1.0, tag_y, "From DICOM headers", size=4.8, color=INK2, ha="left")
phi_pill(col_x[4] - 6.2, tag_y, w=11.0, h=2.9)

# Header row
for j, (name, w, role) in enumerate(cols):
    cell(col_x[j], hdr_y, w, FILL_BG if role == "fill" else "#ececea")
    text(col_x[j] + w / 2, hdr_y + rh / 2, name, size=5.0, weight="bold")

# Data rows
for i, row in enumerate(rows):
    y = hdr_y - (i + 1) * rh
    for j, ((_, w, role), val) in enumerate(zip(cols, row)):
        missing = role == "fill" and not val
        if missing:
            cell(col_x[j], y, w, "white", ec=PHI_INK, lw=0.6, ls=DASH)
        else:
            cell(col_x[j], y, w, tint(C_ORG, 0.12) if role == "fill" else "white")
        if val:
            text(col_x[j] + w / 2, y + rh / 2, val, size=4.6,
                 family=MONO if j == 0 else None, weight="bold" if role == "fill" else "normal")
    if not row[1]:
        text(t_x1 + 1.2, y + rh / 2, "← row skipped", size=4.6, color=INK2, style="italic", ha="left")
ax.add_patch(Rectangle((t_x0, hdr_y - len(rows) * rh), t_x1 - t_x0, (len(rows) + 1) * rh,
                       fc="none", ec=INK, lw=0.6, zorder=3))

# Worked example: how day0Date becomes timepoints
wx0, wx1 = 126.0, 179.0
wy0, wy1 = hdr_y - len(rows) * rh, tag_y + 2.0
box(wx0, wy0, wx1 - wx0, wy1 - wy0, fc="white", ec=INK2, lw=0.6, r=1.2, z=1)
text(wx0 + 2.0, wy1 - 2.6, "How day0Date sets timepoints (GBM001)", size=5.2, weight="bold", ha="left")
tl_y = wy0 + 11.5
tl_x0, tl_x1 = wx0 + 4.0, wx1 - 4.0
ax.plot([tl_x0, tl_x1], [tl_y, tl_y], color=INK, lw=0.6, zorder=3)
ticks = [(tl_x0 + 2.0, "01/12/2024\nscan", "d-3", INK),
         (tl_x0 + 15.0, "01/15/2024\nday0Date", "d0", C_ORG),
         (tl_x1 - 3.0, "03/01/2024\nscan", "d46", INK)]
for x, date_lbl, d_lbl, col in ticks:
    ax.plot([x, x], [tl_y - 1.0, tl_y + 1.0], color=col, lw=1.0 if col == INK else 1.6, zorder=4)
    text(x, tl_y + 1.6, date_lbl, size=4.4, color=INK2, va="bottom")
    text(x, tl_y - 1.6, d_lbl, size=5.0, weight="bold", va="top")
# Axis break: the d0 -> d46 gap is not to scale
brk_x = (tl_x0 + 15.0 + tl_x1 - 3.0) / 2
ax.add_patch(Rectangle((brk_x - 0.8, tl_y - 0.5), 1.6, 1.0, fc="white", ec="none", zorder=4))
for dx in (-0.8, 0.8):
    ax.plot([brk_x + dx - 0.5, brk_x + dx + 0.5], [tl_y - 1.0, tl_y + 1.0], color=INK, lw=0.6, zorder=5)
text(wx0 + 2.0, wy0 + 4.6, "GBM001/GBM001_d-3_<exam>/GBM001_d-3_T1c.nii.gz",
     size=4.3, family=MONO, color=INK2, ha="left")
text(wx0 + 2.0, wy0 + 1.9, "GBM001/GBM001_d46_<exam>/GBM001_d46_T1c.nii.gz",
     size=4.3, family=MONO, color=INK2, ha="left")

# Instructions
notes = [
    ("patientID", "Any non-identifying code (e.g. GBM001). It names every output folder and file, "
                  "including uploads, so never use names, MRNs or dates."),
    ("day0Date", "mm/dd/yyyy reference date (e.g. diagnosis or surgery). Timepoints are days from "
                 "day0Date; earlier scans get negative values."),
    ("Directory", "Written by organize_dicoms; leave it unchanged. If editing in Excel, turn off "
                  "automatic data conversion."),
    ("Blank rows", "Rows missing patientID or day0Date are not converted."),
    (None, "The table links real identities to the IDs you assign. For real patients, keep it on site."),
]
ny = wy0 - 3.4
for lead, body in notes:
    if lead:
        text(t_x0, ny, lead, size=5.0, weight="bold", ha="left")
    else:
        phi_pill(t_x0 + 5.5, ny, w=11.0, h=2.9)
    text(t_x0 + 16.0, ny, body, size=5.0, ha="left")
    ny -= 3.3

out = Path(__file__).resolve().parents[1] / "images"
out.mkdir(exist_ok=True)
for ext in ("pdf", "svg"):
    fig.savefig(out / f"astril_nf_cirro_workflow.{ext}")
fig.savefig(out / "astril_nf_cirro_workflow.png", dpi=600)
print(out)
