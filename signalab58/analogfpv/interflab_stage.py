"""interflab patches as interference inside the signal chain.

Video-level mode: the patch output (1 patch unit = `if2_scale_ire` IRE) is added to the composite
signal coming out of the receiver, right before the goggles' decoder. The decoder then treats it like
any other signal: whatever lands on the color burst moves the burst lock and rotates the hue of those
lines, and whatever lands near 3.58 MHz in the picture is demodulated as color. So the bands come from
the decoder itself, not from a hue effect.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import ntsc

PATCH_DIR = Path(__file__).resolve().parent.parent / "patches"


def find_patch(path_or_name: str) -> Path:
    """A JSON path, or the name of a patch in the bundled patches/ folder (for example tone_burst)."""
    path = Path(path_or_name)
    if not path.exists():
        path = PATCH_DIR / f"{path_or_name}.json"
    if not path.exists():
        raise FileNotFoundError(f"interflab patch {path_or_name!r} not found (give a .json path or a name from {PATCH_DIR})")
    return path


def _engine(p: dict, state: dict):
    eng = state.get("if2_engine")
    if eng is None or state.get("if2_path") != p["if2_patch"]:
        from interflab import Engine, Patch
        patch = Patch.load(str(find_patch(p["if2_patch"])))
        if patch.spl != ntsc.SPL or abs(patch.fs - ntsc.FS) > 1.0:
            raise ValueError(f"patch was made for fs={patch.fs:.0f} Hz, spl={patch.spl}; analogfpv needs "
                             f"fs={ntsc.FS:.0f} Hz, spl={ntsc.SPL}")
        eng = state["if2_engine"] = Engine(patch)
        state["if2_path"] = p["if2_patch"]
    return eng


def interflab_video_stage(sig: np.ndarray, ctx: ntsc.FieldCtx, p: dict, state: dict) -> np.ndarray:
    """Channel stage: add one field of the patch to the demodulated composite (IRE)."""
    eng = _engine(p, state)
    if eng.pos != ctx.offset:                       # fields out of order: jump (oscillator phases restart)
        eng.seek(ctx.offset)
    mix = eng.render(sig.size)
    return (sig + np.float32(p["if2_scale_ire"]) * mix.reshape(sig.shape)).astype(np.float32)
