"""Pictures of a patch: one-field raster, per-line level over time, spectrum and a line trace (cv2 only)."""
import numpy as np
import cv2

from .engine import Engine

BG = (28, 28, 28)
FG = (225, 225, 225)


def analyze(patch, fields: int = 40, lines: int = 262):
    """Render `fields` blocks of `lines` lines. Returns (first block, per-line RMS map lines x fields)."""
    eng, spl = Engine(patch), patch.spl
    rms, first = np.zeros((lines, fields)), None
    for f in range(fields):
        x = eng.render(lines * spl)
        if f == 0:
            first = x.copy()
        rms[:, f] = np.sqrt((x.reshape(lines, spl) ** 2).mean(axis=1))
    return first, rms


def _text(img, s, org, scale=0.42, col=FG):
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, col, 1, cv2.LINE_AA)


def _trace(img, rect, ys, lo, hi, col, title):
    x0, y0, w, h = rect
    cv2.rectangle(img, (x0, y0), (x0 + w, y0 + h), (90, 90, 90), 1)
    ys = np.clip((np.asarray(ys, float) - lo) / max(hi - lo, 1e-12), 0, 1)
    xs = np.linspace(x0, x0 + w, len(ys))
    pts = np.stack([xs, y0 + h - ys * h], axis=1).astype(np.int32)
    cv2.polylines(img, [pts], False, col, 1, cv2.LINE_AA)
    _text(img, title, (x0 + 4, y0 + 14))


def render_png(patch, path: str, fields: int = 40, lines: int = 262) -> np.ndarray:
    img = render_image(patch, fields, lines)
    cv2.imwrite(path, img)
    return img


def render_image(patch, fields: int = 40, lines: int = 262) -> np.ndarray:
    """The same picture as render_png, returned as a BGR array instead of written to a file."""
    first, rms = analyze(patch, fields, lines)
    spl, fs = patch.spl, patch.fs
    W, H = 1000, 720
    img = np.full((H, W, 3), BG, np.uint8)
    names = ", ".join(s["name"] for s in patch.sources)
    _text(img, f"{len(patch.sources)} sources ({names}), {len(patch.cables)} cables", (10, 18))

    # one field as an image: rows = lines, columns = samples along the line
    v = first.reshape(lines, spl)
    s = max(float(np.abs(v).max()), 1e-12)
    r1 = cv2.applyColorMap((v / s * 127 + 128).astype(np.uint8), cv2.COLORMAP_JET)
    img[40:40 + lines, 10:465] = cv2.resize(r1, (455, lines), interpolation=cv2.INTER_AREA)
    _text(img, "one field: lines (down) x samples (across)", (12, 36))

    # signal level of every line, field after field: bursts show as blocks
    m = (rms / max(float(rms.max()), 1e-12) * 255).astype(np.uint8)
    cmap = getattr(cv2, "COLORMAP_INFERNO", cv2.COLORMAP_HOT)
    img[40:40 + lines, 480:980] = cv2.resize(cv2.applyColorMap(m, cmap), (500, lines), interpolation=cv2.INTER_NEAREST)
    _text(img, f"line level over {fields} fields (peak {rms.max():.3g})", (482, 36))

    # spectrum of the first 131072 samples
    n = min(131072, first.size)
    seg = first[:n] * np.hanning(n)
    db = 20 * np.log10(np.abs(np.fft.rfft(seg)) / (n / 4) + 1e-9)
    cols = np.array_split(db, 980)
    top = float(db.max()) + 3
    _trace(img, (10, 330, 980, 180), [c.max() for c in cols], top - 90, top, (120, 220, 120), "spectrum (dB, 0 dB = amplitude 1)")
    for mhz in range(0, int(fs / 2e6) + 1):
        x = 10 + int(980 * mhz * 1e6 / (fs / 2))
        cv2.line(img, (x, 510), (x, 516), FG, 1)
        _text(img, f"{mhz}", (x - 4, 529), 0.35)
    _text(img, "MHz", (962, 529), 0.35)

    # first two lines of the signal
    loud = int(np.argmax(np.sqrt((first.reshape(lines, spl) ** 2).mean(axis=1))))
    loud = min(loud, lines - 2)
    tr = first[loud * spl:(loud + 2) * spl]
    lo, hi = float(tr.min()), float(tr.max())
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    _trace(img, (10, 550, 980, 150), tr, lo, hi, (120, 180, 255), f"two lines from the loudest spot, line {loud} (min {lo:.3g}, max {hi:.3g})")
    return img
