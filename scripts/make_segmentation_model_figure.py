"""Render the astril GBM_seg_v2 segmentation model schematics (same style as make_workflow_figure.py).

Writes images/astril_segmentation_model.{pdf,svg,png} (detailed: cascade, network, 2.5D windows)
and images/astril_segmentation_model_simple.{pdf,svg,png} (overview in the layout of the original
poster figure). All geometry is in millimetres.

    python scripts/make_segmentation_model_figure.py [--exam_dir DIR]

--exam_dir: optional preprocessed exam folder (*_T1c/_T1n/_T2f/_T2w_brain-norm.nii.gz). If given,
an axial slice of each sequence is drawn in the input tiles (from native_space/ at full resolution
when present); otherwise the tiles are text-only. If the folder also holds a segmentation
(*_GBM-seg.nii.gz preferred), the slice goes through the lesion and
images/astril_t1post_segmentation_overlay.png shows that segmentation on the same T1-post slice.
"""
import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import to_rgb
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle

W = 180.0                         # figure width, mm (double-column)
H_DETAILED, H_SIMPLE = 160.0, 100.0

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "pdf.fonttype": 42,      # editable text in Illustrator
    "svg.fonttype": "none",
    "image.composite_image": False,  # embed each MRI at native resolution in PDF/SVG
})

INK = "#1f1f1f"
INK2 = "#575757"
RULE = "#8a8a8a"
DASH = (0, (3, 1.5))

C_A = "#e87ba4"      # Stage 1 / Model A (gate)
C_B = "#eda100"      # Stage 2 / Model B (same colour as "3 Segment" in the workflow figure)
C_NET = "#2a78d6"    # network internals
C_ATT = "#eb6834"    # skip attention
# Output labels 1-4
LABELS = [
    (0, "background", "#ffffff"),
    (1, "necrosis / non-enhancing tumor", "#6250d6"),
    (2, "edema / SNFH", "#1baf7a"),
    (3, "enhancing tumor / tissue", "#eb6834"),
    (4, "resection cavity", "#2a78d6"),
]
SEQUENCES = [("T1c", "T1-post", "required", "_T1c_brain-norm.nii.gz"),
             ("T1n", "T1-pre", "optional", "_T1n_brain-norm.nii.gz"),
             ("T2f", "T2-FLAIR", "optional", "_T2f_brain-norm.nii.gz"),
             ("T2w", "T2", "optional", "_T2w_brain-norm.nii.gz")]


def tint(color, a=0.14):
    r, g, b = to_rgb(color)
    return (1 - a + a * r, 1 - a + a * g, 1 - a + a * b)


ax = None


def new_canvas(h):
    """Start a W x h mm figure; the drawing helpers below draw on it."""
    global ax
    fig = plt.figure(figsize=(W / 25.4, h / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, h)
    ax.axis("off")
    return fig


def box(x, y, w, h, fc="white", ec=INK, lw=0.6, ls="-", r=1.2, z=2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc=fc, ec=ec, lw=lw, ls=ls, zorder=z))


def text(x, y, s, size=5.5, color=INK, weight="normal", ha="center", va="center",
         style="normal", family=None, z=5, **kw):
    ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, ha=ha, va=va,
            fontstyle=style, family=family, zorder=z, linespacing=1.15, **kw)


def arrow(p0, p1, color=INK, lw=0.6, ls="-", head=5, z=4, connectionstyle="arc3"):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=head, color=color,
                                 lw=lw, ls=ls, shrinkA=0, shrinkB=0, zorder=z,
                                 connectionstyle=connectionstyle))


def panel_label(x, y, s, title):
    text(x, y, s, size=9, weight="bold", ha="left")
    text(x + 6, y, title, size=6.5, weight="bold", ha="left")


def _load_labels(path):
    import nibabel as nib
    img = nib.load(str(path))
    return np.rint(np.asarray(img.dataobj)).astype(np.int16), img.affine


def _sample_labels(seg, affine, world, smooth=True):
    """Label map on a world-coordinate grid; smooth = per-label linear interpolation + argmax."""
    import nibabel as nib
    from scipy.ndimage import map_coordinates
    vox = nib.affines.apply_affine(np.linalg.inv(affine), world).transpose(2, 0, 1)
    if not smooth:
        return map_coordinates(seg, vox, order=0, cval=0)
    levels = np.arange(max(int(seg.max()), len(LABELS) - 1) + 1)
    weights = [map_coordinates((seg == lvl).astype(np.float32), vox, order=1, cval=float(lvl == 0))
               for lvl in levels]
    return levels[np.argmax(np.stack(weights), axis=0)]


def load_native_thumbnails(exam_dir, lesion_world, seg_path=None, focus_label=None, extra_segs=None):
    """
    Full-resolution thumbnails from <exam_dir>/native_space/*_<seq>_native_brain.nii.gz.
    The native scans share world coordinates, so one plane -- a T2w slice (T2w has the finest
    in-plane grid) -- is resampled from every sequence. The slice is the one nearest the lesion,
    or, with focus_label, the T2w slice with the most of that label. Returns None if the native
    images are missing. With seg_path, the label map is resampled onto the same plane as
    thumbs["seg"]; each extra_segs {name: path} entry becomes thumbs["seg:<name>"].
    """
    import nibabel as nib
    from scipy.ndimage import map_coordinates
    native = Path(exam_dir) / "native_space"
    paths = {key: sorted(native.glob(f"*_{key}_native_brain.nii.gz")) for key, *_ in SEQUENCES}
    if not all(paths.values()):
        return None
    ref = nib.load(str(paths["T2w"][0]))
    ni, nj, nk = ref.shape[:3]
    jj, ii = np.mgrid[0:nj, 0:ni]

    def plane_world(k):
        return nib.affines.apply_affine(ref.affine, np.stack([ii, jj, np.full_like(ii, k)], -1))

    seg = _load_labels(seg_path) if seg_path is not None else None
    if seg is not None and focus_label is not None:
        counts = [int((_sample_labels(*seg, plane_world(k), smooth=False) == focus_label).sum())
                  for k in range(nk)]
        if max(counts) == 0:
            raise SystemExit(f"Label {focus_label} does not appear in {seg_path}")
        k = int(np.argmax(counts))
    else:
        k = int(round(nib.affines.apply_affine(np.linalg.inv(ref.affine), lesion_world)[2]))
    world = plane_world(k)
    planes = {}
    for key, *_ in SEQUENCES:
        img = nib.load(str(paths[key][0]))
        vox = nib.affines.apply_affine(np.linalg.inv(img.affine), world)
        planes[key] = map_coordinates(np.asarray(img.dataobj, dtype=np.float32),
                                      vox.transpose(2, 0, 1), order=1, cval=0.0)  # rows = j
    if seg is not None:
        planes["seg"] = _sample_labels(*seg, world)
    for name, path in (extra_segs or {}).items():
        planes[f"seg:{name}"] = _sample_labels(*_load_labels(path), world)
    if nib.aff2axcodes(ref.affine)[0] == "L":   # show patient right on the image right
        planes = {key: p[:, ::-1] for key, p in planes.items()}
    if nib.aff2axcodes(ref.affine)[1] == "P":
        planes = {key: p[::-1, :] for key, p in planes.items()}
    rows, cols = np.nonzero(planes["T2w"] != 0)
    pixdim = float(ref.header.get_zooms()[0])
    margin = int(round(2.0 / pixdim))
    cr, cc = (rows.min() + rows.max()) // 2, (cols.min() + cols.max()) // 2
    half = max(rows.max() - rows.min(), cols.max() - cols.min()) // 2 + margin
    thumbs = {}
    for key, p in planes.items():
        sl = p[max(cr - half, 0):cr + half, max(cc - half, 0):cc + half]
        if key.startswith("seg"):
            thumbs[key] = sl
            continue
        lo, hi = np.percentile(sl[sl != 0], [1, 99]) if np.any(sl != 0) else (0, 1)
        thumbs[key] = np.clip((sl - lo) / max(hi - lo, 1e-6), 0, 1)
    return thumbs


def load_thumbnails(exam_dir, focus_label=None, extra_segs=None):
    """
    One axial slice per sequence, cropped to the brain. The slice is the one with the most
    lesion (or the most of focus_label) if the folder holds a segmentation (*_GBM-seg /
    *tumor-segmentation), else the one with the most brain. extra_segs {name: path} are
    resampled onto the same slice (native-space path only).
    """
    import nibabel as nib
    exam_dir = Path(exam_dir)

    def load(path):
        return np.asarray(nib.as_closest_canonical(nib.load(str(path))).dataobj, dtype=np.float32)

    vols = {}
    for key, _, _, pattern in SEQUENCES:
        hits = sorted(exam_dir.glob(f"*{pattern}"))
        if hits:
            vols[key] = load(hits[0])
    if "T1c" not in vols:
        raise SystemExit(f"No *_T1c_brain-norm.nii.gz in {exam_dir}")
    # normalized images need not have an exactly-zero background, so prefer the brain mask
    mask_hits = sorted(exam_dir.glob("*_brainmask.nii.gz"))
    brain = load(mask_hits[0]) > 0.5 if mask_hits else vols["T1c"] != 0
    seg_hits = sorted(exam_dir.glob("*_GBM-seg.nii.gz")) + sorted(exam_dir.glob("*tumor-segmentation*.nii.gz"))
    seg = load(seg_hits[0]) if seg_hits else None
    if seg is not None and seg.shape == brain.shape and np.any(seg > 0):
        focus = (np.rint(seg) == focus_label) if focus_label is not None else seg > 0
        if not np.any(focus):
            raise SystemExit(f"Label {focus_label} does not appear in {seg_hits[0]}")
        z = int(np.argmax(focus.sum(axis=(0, 1))))
    else:
        z = int(np.argmax(brain.sum(axis=(0, 1))))
        focus = brain
    ref_img = nib.as_closest_canonical(nib.load(str(sorted(exam_dir.glob(f"*{SEQUENCES[0][3]}"))[0])))
    fx, fy = np.nonzero(focus[:, :, z])
    focus_world = nib.affines.apply_affine(ref_img.affine, [fx.mean(), fy.mean(), z])
    # whole-lesion Dice (3-D) of each comparison segmentation against the exam's own
    dice = {}
    for name, path in (extra_segs or {}).items():
        other = load(path) > 0
        if seg is not None and other.shape == seg.shape:
            dice[f"dice:{name}"] = 2 * np.sum(other & (seg > 0)) / (np.sum(other) + np.sum(seg > 0))
    native = load_native_thumbnails(exam_dir, focus_world, seg_hits[0] if seg is not None else None,
                                    focus_label=focus_label, extra_segs=extra_segs)
    if native is not None:
        return {**native, **dice}
    xs, ys = np.nonzero(brain[:, :, z])
    cx, cy = (xs.min() + xs.max()) // 2, (ys.min() + ys.max()) // 2
    half = max(xs.max() - xs.min(), ys.max() - ys.min()) // 2 + 2
    thumbs = {}
    for key, vol in vols.items():
        sl = vol[max(cx - half, 0):cx + half, max(cy - half, 0):cy + half, z]
        lo, hi = np.percentile(sl[sl != 0], [1, 99]) if np.any(sl != 0) else (0, 1)
        thumbs[key] = np.clip((sl - lo) / max(hi - lo, 1e-6), 0, 1).T  # rows = A-P
    if seg is not None and seg.shape == brain.shape:
        thumbs["seg"] = np.rint(seg[max(cx - half, 0):cx + half, max(cy - half, 0):cy + half, z]).astype(int).T
    return {**thumbs, **dice}


def overlay_rgb(thumbs, seg_key="seg", alpha=0.5):
    """T1-post figure slice with the segmentation labels blended on top (origin="lower" rows)."""
    gray = np.repeat(thumbs["T1c"][..., None], 3, axis=-1)
    rgb = gray.copy()
    for lvl, _, color in LABELS[1:]:
        hit = thumbs[seg_key] == lvl
        rgb[hit] = (1 - alpha) * gray[hit] + alpha * np.asarray(to_rgb(color))
    return rgb


def save_t1post_overlay(thumbs, path, seg_key="seg"):
    """The overlay as its own PNG, at native pixel size."""
    from PIL import Image
    # thumbnails are stored for origin="lower" display: flip so anterior is at the top
    Image.fromarray(np.rint(overlay_rgb(thumbs, seg_key)[::-1] * 255).astype(np.uint8)).save(path)


def draw_detailed(thumbs):
    # ============================================================ panel a: two-stage cascade
    panel_label(2, 156, "a", "GBM_seg_v2: two-stage, three-plane consensus")

    # --- inputs
    tile_w, tile_h, pitch, top = 26.0, 10.5, 12.6, 149.0
    text(17, 151.6, "Normalized, skull-stripped inputs", size=5.2, weight="bold")
    for i, (key, name, req, _) in enumerate(SEQUENCES):
        y = top - tile_h - i * pitch
        box(4, y, tile_w, tile_h, fc="white", ec=INK if req == "required" else RULE,
            lw=0.8 if req == "required" else 0.5, ls="-" if req == "required" else DASH)
        tx = 6.0
        if thumbs and key in thumbs:
            ax.imshow(thumbs[key], cmap="gray", origin="lower", zorder=3, interpolation="none",
                      extent=(4.8, 4.8 + tile_h - 1.6, y + 0.8, y + tile_h - 0.8))
            tx = 4.8 + tile_h - 1.6 + 1.6
        text(tx, y + tile_h * 0.64, name, size=5.4, weight="bold", ha="left")
        text(tx, y + tile_h * 0.30, req, size=4.6, color=INK if req == "required" else INK2,
             ha="left", style="normal" if req == "required" else "italic")
    y_mask = top - tile_h - 4 * pitch
    box(4, y_mask, tile_w, tile_h, fc=tint(INK, 0.06), ec=INK, lw=0.6)
    text(17, y_mask + tile_h * 0.64, "Brain mask", size=5.4, weight="bold")
    text(17, y_mask + tile_h * 0.30, "required", size=4.6)

    # all inputs feed both stages: bracket from every tile
    tile_yc = [top - tile_h / 2 - i * pitch for i in range(5)]
    for yc in tile_yc:
        ax.plot([4 + tile_w, 33.0], [yc, yc], color=INK, lw=0.6, zorder=3)
    ax.plot([33.0, 33.0], [tile_yc[-1], tile_yc[0]], color=INK, lw=0.8, zorder=3)

    # --- stage bands
    bx0, bx1 = 36.0, 178.0
    rows = [  # (y0, y1, colour, title)
        (119.0, 151.0, C_A, "Stage 1   Model A: abnormality gate (2 classes)"),
        (84.0, 116.0, C_B, "Stage 2   Model B: tissue segmentation (5 classes)"),
    ]
    for y0, y1, col, title in rows:
        box(bx0, y0, bx1 - bx0, y1 - y0, fc=tint(col, 0.12), ec=col, lw=0.9)
        ax.add_patch(Rectangle((bx0 + 0.45, y1 - 1.6), bx1 - bx0 - 0.9, 1.15, fc=col, ec="none",
                               zorder=3))
        text(bx0 + 2.5, y1 - 4.2, title, size=5.8, weight="bold", ha="left")

    chip_x0, chip_w, chip_h = 40.0, 25.0, 5.4
    merge_x0, merge_w = 74.0, 26.0
    for (y0, y1, col, _), merge_text in zip(rows, ["Average\nprobability",
                                                   "Average logit\n→ argmax"]):
        yc_mid = (y0 + y1) / 2 - 2.2
        for j, plane in enumerate(["Axial", "Coronal", "Sagittal"]):
            yc = yc_mid + (1 - j) * 7.2
            box(chip_x0, yc - chip_h / 2, chip_w, chip_h, fc="white", ec=col, lw=0.7, r=0.9)
            text(chip_x0 + chip_w / 2, yc, f"{plane} 2.5D CNN", size=5.0)
            arrow((chip_x0 + chip_w, yc), (merge_x0, yc_mid + (1 - j) * 2.6), lw=0.5, head=4)
        box(merge_x0, yc_mid - 6.0, merge_w, 12.0, fc=col, ec=col, lw=0.6)
        text(merge_x0 + merge_w / 2, yc_mid, merge_text, size=5.4, weight="bold", color="white")
        # inputs -> plane CNNs
        arrow((33.0, yc_mid), (chip_x0 - 0.4, yc_mid), lw=0.8, head=5)

    # Stage 1 tail: gate construction + labels
    ya = (rows[0][0] + rows[0][1]) / 2 - 2.2
    gx0, gw = 106.0, 34.0
    box(gx0, ya - 8.0, gw, 16.0, fc="white", ec=C_A, lw=0.7)
    for k, line in enumerate(["P(abnormal) > 0.30", "dilate 5 voxels", "∩ brain mask"]):
        text(gx0 + gw / 2, ya + 4.6 - k * 4.6, line, size=5.0)
    arrow((merge_x0 + merge_w, ya), (gx0, ya), lw=0.8, head=5)
    text(146, ya + 6.0, "Spatial gate", size=5.2, weight="bold", ha="left")
    text(146, ya + 1.6, "0  background", size=4.8, ha="left")
    text(146, ya - 2.0, "1  abnormal (any lesion)", size=4.8, ha="left")
    arrow((gx0 + gw, ya), (145.0, ya), lw=0.8, head=5)
    text(146, ya - 6.6, "Not a model input:\nrestricts where Model B runs", size=4.4, color=INK2,
         ha="left", style="italic")

    # Stage 2 tail: gate restriction + final labels
    yb = (rows[1][0] + rows[1][1]) / 2 - 2.2
    box(gx0, yb - 8.0, gw, 16.0, fc="white", ec=C_B, lw=0.7)
    text(gx0 + gw / 2, yb + 3.2, "Restrict to gate", size=5.2, weight="bold")
    text(gx0 + gw / 2, yb - 2.4, "outside gate → background", size=4.8)
    arrow((merge_x0 + merge_w, yb), (gx0, yb), lw=0.8, head=5)
    arrow((gx0 + gw / 2, ya - 8.0), (gx0 + gw / 2, yb + 8.0), color=C_A, lw=0.9, ls=DASH, head=5)
    text(gx0 + gw / 2 + 1.2, rows[0][0] + 2.4, "gate", size=4.8, color=INK2, ha="left",
         style="italic")
    arrow((gx0 + gw, yb), (145.0, yb), lw=0.8, head=5)
    for k, (lvl, name, col) in enumerate(LABELS):
        yy = yb + 8.4 - k * 4.2
        ax.add_patch(Rectangle((146.0, yy - 1.3), 2.6, 2.6, fc=col, ec=INK, lw=0.35, zorder=4))
        text(149.6, yy, f"{lvl}  {name}", size=4.6, ha="left")

    text(4, 79.6,
         "Each plane's CNN reads the same four sequences. Missing optional sequences are "
         "zero-filled and flagged by modality-presence channels\n(models were trained with random "
         "sequence dropout). Training data: BraTS 2024 BraTS-GLI (adult glioma, post-treatment).",
         size=4.8, color=INK2, ha="left", va="center")

    # ============================================================ panel b: network
    panel_label(2, 72, "b", "Per-plane network: ResidualContextUNeXt25D (~19.9 M parameters)")
    L = {1: 58.0, 2: 46.0, 3: 34.0, 4: 22.0, 5: 10.0}   # level -> y centre
    bw, bh = 15.0, 7.0
    enc_x = {i: 32.0 + 4.0 * (i - 1) for i in range(1, 5)}
    xc = enc_x[4] + bw + 7.0                     # U centre line
    dec_x = {i: 2 * xc - (enc_x[i] + bw) for i in range(1, 5)}
    ch = {1: 32, 2: 64, 3: 128, 4: 256}
    res = {1: "256²", 2: "128²", 3: "64²", 4: "32²"}

    # input + slab context stem
    box(4, 63.5, 24, 4.6, fc="white", ec=INK, lw=0.5, r=0.8)
    text(16, 65.8, "7 slices × 4 seq + 4 presence", size=4.6)
    box(4, 26.0, 24, 35.5, fc=tint(C_NET, 0.12), ec=C_NET, lw=0.7)
    text(16, 58.4, "Slab context stem", size=5.2, weight="bold")
    for k, line in enumerate(["Conv3D 3×3×3 across", "ordered 7-slice slab",
                              "", "center-slice features", "+ learned depth-", "attention pooling",
                              "+ presence-flag", "projection", "", "1×1 fuse → 32 ch"]):
        text(16, 53.6 - k * 2.6, line, size=4.6)
    arrow((16, 63.5), (16, 61.5), lw=0.6, head=4)
    arrow((28, L[1]), (enc_x[1], L[1]), lw=0.7, head=4.5)

    def level_block(x, y, label, fc, ec):
        box(x, y - bh / 2, bw, bh, fc=fc, ec=ec, lw=0.6, r=0.8)
        text(x + bw / 2, y, label, size=4.8)

    for i in range(1, 5):
        level_block(enc_x[i], L[i], f"{ch[i]} ch · {res[i]}", "white", C_NET)
        level_block(dec_x[i], L[i], f"{ch[i]} ch · {res[i]}", tint(C_NET, 0.18), C_NET)
        # skip connection with residual attention gate
        x0, x1 = enc_x[i] + bw, dec_x[i]
        gx = (x0 + x1) / 2
        ax.plot([x0, gx - 1.6], [L[i], L[i]], color=RULE, lw=0.6, zorder=3)
        arrow((gx + 1.6, L[i]), (x1, L[i]), color=RULE, lw=0.6, head=4)
        ax.add_patch(Circle((gx, L[i]), 1.6, fc=tint(C_ATT, 0.25), ec=C_ATT, lw=0.6, zorder=4))
        text(gx, L[i] - 0.05, "×", size=5.2, color=C_ATT, weight="bold")
    # down / up paths
    for i in range(1, 4):
        arrow((enc_x[i] + 3.0, L[i] - bh / 2), (enc_x[i + 1] + 3.0, L[i + 1] + bh / 2), lw=0.6, head=4)
        arrow((dec_x[i + 1] + bw - 3.0, L[i + 1] + bh / 2), (dec_x[i] + bw - 3.0, L[i] - bh / 2),
              lw=0.6, head=4)
    bx = xc - bw / 2 - 2.0
    box(bx, L[5] - bh / 2, bw + 4.0, bh, fc=tint(C_NET, 0.35), ec=C_NET, lw=0.7, r=0.8)
    text(xc, L[5] + 1.2, "512 ch · 16²", size=4.8)
    text(xc, L[5] - 1.8, "dilation 1, 2", size=4.2, color=INK2)
    arrow((enc_x[4] + 3.0, L[4] - bh / 2), (bx + 2.0, L[5] + bh / 2), lw=0.6, head=4)
    arrow((bx + bw + 2.0, L[5] + bh / 2), (dec_x[4] + bw - 3.0, L[4] - bh / 2), lw=0.6, head=4)
    text(enc_x[2] - 1.0, (L[2] + L[3]) / 2, "stride-2\nconv", size=4.2, color=INK2, ha="right")
    text(dec_x[2] + bw + 1.0, (L[2] + L[3]) / 2, "bilinear ↑\n+ 3×3 conv", size=4.2,
         color=INK2, ha="left")

    # heads
    hx = dec_x[1] + bw + 6.0
    box(hx, L[1] - 4.0, 20.0, 8.0, fc=C_B, ec=C_B, lw=0.6, r=0.8)
    text(hx + 10.0, L[1] + 1.4, "1×1 conv head", size=4.8, weight="bold", color="white")
    text(hx + 10.0, L[1] - 1.8, "3 slices × classes", size=4.6, color="white")
    arrow((dec_x[1] + bw, L[1]), (hx, L[1]), lw=0.7, head=4.5)
    for i, lab in ((2, "aux head, ½ res"), (3, "aux head, ¼ res")):
        box(hx, L[i] - 2.6, 20.0, 5.2, fc="white", ec=C_B, lw=0.6, ls=DASH, r=0.8)
        text(hx + 10.0, L[i], lab, size=4.6)
        arrow((dec_x[i] + bw, L[i]), (hx, L[i]), color=RULE, lw=0.6, ls=DASH, head=4)
    text(hx + 10.0, L[3] - 5.2, "deep supervision,\ntraining only", size=4.2, color=INK2,
         style="italic")

    # legend
    ly = 2.6
    box(4, ly - 1.6, 5.0, 3.2, fc="white", ec=C_NET, lw=0.6, r=0.5)
    text(10.2, ly, "2 pre-activation residual blocks (GroupNorm, SiLU, 3×3 conv); "
                   "encoder white, decoder shaded", size=4.6, ha="left")
    ax.add_patch(Circle((95.5, ly), 1.4, fc=tint(C_ATT, 0.25), ec=C_ATT, lw=0.6, zorder=4))
    text(95.5, ly - 0.05, "×", size=4.8, color=C_ATT, weight="bold")
    text(97.8, ly, "residual skip attention:\nrescales skip 0.5–1.5×, never erases it",
         size=4.4, ha="left")

    # ============================================================ panel c: 2.5D windowing
    cx0 = 134.0
    panel_label(cx0 - 2, 72, "c", "2.5D windows")
    n, pitch_c, cw = 9, 3.5, 3.0
    sx0 = cx0 + 2.0
    centre = 4

    def slice_row(y, highlight, col, label, alpha=0.75):
        text(cx0 - 0.5, y, label, size=4.4, ha="left")
        for k in range(n):
            on = k in highlight
            ax.add_patch(Rectangle((sx0 + 10.0 + k * pitch_c, y - 1.6), cw, 3.2,
                                   fc=tint(col, alpha) if on else "white",
                                   ec=col if on else RULE, lw=0.4, zorder=3))

    def cell_x(k):
        return sx0 + 10.0 + k * pitch_c + cw / 2

    yin = 63.0
    slice_row(yin, set(range(centre - 3, centre + 4)), C_NET, "input", alpha=0.35)
    text(cell_x(centre), yin + 3.4, "7 input slices", size=4.4, color=INK2)
    yout = 57.0
    slice_row(yout, {centre - 1, centre, centre + 1}, C_B, "output")
    text(cell_x(centre), yout - 3.4, "3 predicted slices per window", size=4.4, color=INK2)

    text(cx0 - 0.5, 48.0, "average (default)", size=5.0, weight="bold", ha="left")
    for r, c in enumerate((centre - 1, centre, centre + 1)):
        slice_row(44.0 - r * 4.2, {c - 1, c, c + 1}, C_B, ["window z−1", "window z",
                                                           "window z+1"][r])
    ax.add_patch(Rectangle((cell_x(centre) - cw / 2 - 0.6, 44.0 - 2 * 4.2 - 2.2), cw + 1.2,
                           2 * 4.2 + 4.4, fc="none", ec=INK, lw=0.7, zorder=5))
    text(cell_x(centre), 30.2, "slice z = mean of 3", size=4.4)
    text(cx0 - 0.5, 26.4, "every slice is a window center;\noverlapping outputs averaged",
         size=4.2, color=INK2, ha="left", va="top")

    text(cx0 - 0.5, 17.0, "tile (fast)", size=5.0, weight="bold", ha="left")
    text(cx0 - 0.5, 13.0, "windows", size=4.4, ha="left")
    for k in range(n):
        ax.add_patch(Rectangle((sx0 + 10.0 + k * pitch_c, 11.4), cw, 3.2,
                               fc=tint(C_B, [0.75, 0.3, 0.75][k // 3]), ec=C_B, lw=0.4, zorder=3))
    text(cx0 - 0.5, 8.4, "spaced 3 apart, no overlap:\n~3× fewer forward passes",
         size=4.2, color=INK2, ha="left", va="top")


# Original-figure modality colours (T1-pre blue, T1-post yellow, FLAIR red, T2 green)
MOD_COLORS = {"T1n": "#2a78d6", "T1c": "#d4b000", "T2f": "#d63a3a", "T2w": "#1baf7a"}
C_B_SIMPLE = "#eb6834"   # Stage 2 consensus, orange as in the original figure


def draw_simple(thumbs):
    text(4, 95.5, "GBM Segmentation Model Architecture", size=8.5, weight="bold", ha="left")
    # parameter count: 6 x ResidualContextUNeXt25D (19,903,127 for 2 classes; 19,905,170 for 5)
    box(112.0, 92.4, 64.0, 6.2, fc=tint(C_B_SIMPLE, 0.14), ec=C_B_SIMPLE, lw=0.6, r=1.0)
    text(144.0, 95.5, "6 CNNs × ~19.9 M parameters = ~119 M total", size=6.2, weight="bold",
         color=INK)

    # --- inputs column, in the original order
    text(17, 89.5, "Inputs", size=6.5, weight="bold")
    order = ["T1n", "T1c", "T2f", "T2w"]
    names = {k: name for k, name, _, _ in SEQUENCES}
    required = {k: req == "required" for k, _, req, _ in SEQUENCES}
    th, tp = 19.0, 21.0
    for i, key in enumerate(order):
        y = 86.5 - th - i * tp
        col = MOD_COLORS[key]
        has_img = bool(thumbs and key in thumbs)
        box(4, y, 26, th, fc="black" if has_img else "white", ec=col, lw=1.2, r=0.8)
        text(6.6, y + th / 2, names[key], size=5.6, weight="bold", color=col, rotation=90)
        if has_img:
            ax.imshow(thumbs[key], cmap="gray", origin="lower", zorder=3, interpolation="none",
                      extent=(9.5, 9.5 + th - 2.0, y + 1.0, y + th - 1.0))
        else:
            text(18.5, y + th / 2, "required" if required[key] else "optional", size=5.0,
                 color=INK if required[key] else INK2,
                 style="normal" if required[key] else "italic")
        if not required[key]:
            box(22.4, y + th - 3.9, 7.0, 2.9, fc="white", ec=col, lw=0.6, r=0.8, z=6)
            text(25.9, y + th - 2.45, "Optional", size=4.4, weight="bold", color=INK, z=7)

    rng = np.random.default_rng(7)   # fixed seed: the textures are identical on every render

    def heat_texture(color, cells=8):
        """A shaded pixel-map in one hue: smooth random field, light tint to darker shade."""
        y, x = np.mgrid[0:cells, 0:cells] / (cells - 1)
        field = rng.normal(0, 0.18, (cells, cells))
        for _ in range(3):
            cy, cx, sd = rng.uniform(0, 1), rng.uniform(0, 1), rng.uniform(0.2, 0.45)
            field += np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sd ** 2))
        field = (field - field.min()) / (field.max() - field.min())
        light, dark = np.asarray(tint(color, 0.35)), np.asarray(to_rgb(color)) * 0.72
        return light + field[..., None] * (dark - light)

    def stack(x, yc, label, size=9.0, step=1.2):
        """A 2.5D slab: one slice per sequence, back to front, plane name on the front slice."""
        for k, key in enumerate(reversed(order)):
            off = (3 - k) * step
            x0, y0 = x + off, yc - size / 2 - off + 1.8
            ax.imshow(heat_texture(MOD_COLORS[key]), interpolation="none", zorder=3 + 2 * k,
                      extent=(x0, x0 + size, y0, y0 + size))
            ax.add_patch(Rectangle((x0, y0), size, size, fc="none", ec="white", lw=0.6,
                                   zorder=4 + 2 * k))
        text(x + size / 2, yc + 1.8, label, size=4.2, weight="bold", color="white", z=12)
        return x + size + 3 * step

    planes = [("Coronal", 72.0), ("Axial", 50.0), ("Sagittal", 28.0)]
    yc_box = 50.0

    def stage(x_stack, x_box, w_box, col, header, box_text):
        x_end = x_stack + 9.0 + 3 * 1.2
        text((x_stack + x_box + w_box) / 2, 89.5, header, size=6.5, weight="bold", color=col)
        text((x_stack + x_box + w_box) / 2, 85.6, "3 × 2.5D CNN (one per plane)", size=4.8,
             color=INK2)
        for j, (plane, yc) in enumerate(planes):
            stack(x_stack, yc, plane)
            arrow((x_end + 0.8, yc), (x_box - 0.5, yc_box + (1 - j) * 3.0), lw=1.0, head=6)
        box(x_box, yc_box - 7.0, w_box, 14.0, fc=col, ec=col, lw=0.8, r=1.5)
        text(x_box + w_box / 2, yc_box, box_text, size=5.6, weight="bold", color="white")

    # Stage 1: Model A gate
    s1_box = (55.0, 22.0)
    stage(35.0, *s1_box, C_A, "Stage 1", "Consensus\nStage 1\n(gate)")
    lx = s1_box[0] - 1.0
    arrow((s1_box[0] + s1_box[1] / 2, yc_box - 7.0), (s1_box[0] + s1_box[1] / 2, 38.0), color=C_A,
          lw=1.0, head=6)
    for k, line in enumerate(["0 = normal brain", "1 = abnormal brain"]):
        text(lx, 34.5 - k * 4.2, "•  " + line, size=5.4, weight="bold", color=C_A, ha="left")
    text(lx, 25.0, "average probability > 0.30,\ndilated 5 voxels\n→ gated region",
         size=4.5, color=INK2, style="italic", ha="left", va="top")

    # gate -> Stage 2 CNNs (restricts where they run; not an input channel)
    gx0, s2_x = s1_box[0] + s1_box[1] + 0.5, 85.0
    for _, yc in planes:
        arrow((gx0, yc_box), (s2_x - 0.8, yc), color=C_A, lw=1.0, ls=DASH, head=6)
    text(gx0 + 3.0, 66.5, "gated\nregion", size=4.6, color=C_A, style="italic", weight="bold",
         ha="right")

    # Stage 2: Model B
    s2_box = (104.0, 24.0)
    stage(s2_x, *s2_box, C_B_SIMPLE, "Stage 2", "Consensus\nTumor\nSegmentation")
    text(s2_box[0] + s2_box[1] / 2, yc_box - 9.5, "average logit → argmax", size=4.5, color=INK2,
         style="italic")

    # --- outputs column: T1-post overlays (all inputs vs. partial inputs) + label legend
    ox0, ox1 = 133.0, 178.0
    oc = (ox0 + ox1) / 2
    text(oc, 89.5, "Example output (T1-post)", size=6.5, weight="bold", color=C_B_SIMPLE)
    size = 31.0
    compare = [k for k in (thumbs or {}) if k.startswith("seg:")]
    panels = [("seg", "All four inputs", 52.0),
              (compare[0] if compare else None,
               "T1-post + FLAIR only" if not compare or compare[0] == "seg:t1c_t2f_only"
               else compare[0][4:], 13.5)]
    for key, caption, y0 in panels:
        x0 = oc - size / 2
        box(x0 - 0.6, y0 - 0.6, size + 1.2, size + 1.2, fc="black", ec=C_B_SIMPLE, lw=1.0, r=0.8)
        if thumbs and key in thumbs:
            ax.imshow(overlay_rgb(thumbs, key), origin="lower", interpolation="none", zorder=3,
                      extent=(x0, x0 + size, y0, y0 + size))
        dice = (thumbs or {}).get(key.replace("seg:", "dice:")) if key and key != "seg" else None
        if dice is not None:
            caption += f"  (Dice {dice:.2f})"
        text(oc, y0 + size + 2.6, caption, size=5.2, weight="bold")
        arrow((s2_box[0] + s2_box[1] + 0.5, yc_box), (x0 - 1.4, y0 + size / 2), color=C_B_SIMPLE,
              lw=1.0, head=6)
    for k, (lvl, name, col) in enumerate(LABELS[1:]):
        name = {1: "necrosis", 2: "edema", 3: "enhancing tumor", 4: "resection cavity"}[lvl]
        lx, ly = ox0 + (k % 2) * 23.0, 9.0 - (k // 2) * 3.6
        ax.add_patch(Rectangle((lx, ly - 1.1), 2.2, 2.2, fc=col, ec=INK, lw=0.35, zorder=4))
        text(lx + 3.0, ly, f"{lvl} {name}", size=4.8, ha="left")

    text(36.0, 3.0, "T1-post is required; missing optional sequences are zero-filled. Stage 2 runs "
                    "only inside the Stage 1 gated region.", size=4.5, color=INK2, ha="left")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exam_dir", help="Preprocessed exam folder for input thumbnails (optional).")
    parser.add_argument("--focus_label", type=int,
                        help="Show the slice with the most of this label (e.g. 1 = necrosis).")
    parser.add_argument("--compare_seg", action="append", default=[], metavar="NAME=PATH",
                        help="Another segmentation of the same exam; also written as an overlay on "
                             "the same slice (astril_t1post_segmentation_overlay_NAME.png). Repeatable.")
    args = parser.parse_args()
    extra_segs = dict(item.split("=", 1) for item in args.compare_seg)
    thumbs = (load_thumbnails(args.exam_dir, focus_label=args.focus_label, extra_segs=extra_segs)
              if args.exam_dir else None)

    out = Path(__file__).resolve().parents[1] / "images"
    out.mkdir(exist_ok=True)
    for name, h, draw in (("astril_segmentation_model", H_DETAILED, draw_detailed),
                          ("astril_segmentation_model_simple", H_SIMPLE, draw_simple)):
        fig = new_canvas(h)
        draw(thumbs)
        for ext in ("pdf", "svg"):
            fig.savefig(out / f"{name}.{ext}")
        fig.savefig(out / f"{name}.png", dpi=720)  # >= MRI thumbnail resolution per tile
        plt.close(fig)
    if thumbs and "seg" in thumbs:
        save_t1post_overlay(thumbs, out / "astril_t1post_segmentation_overlay.png")
    for name in extra_segs:
        save_t1post_overlay(thumbs, out / f"astril_t1post_segmentation_overlay_{name}.png",
                            seg_key=f"seg:{name}")
    print(out)


if __name__ == "__main__":
    main()
