"""The processing chain. Pure functions + one small stateful class; no printing, no UI.

A GUI (or the CLI) only needs:
    Pipeline(params).process_frame(frame)       - one field in, one frame out
    process_still(image, params)                - quick single-image preview
    render_preview(src, params, start, n)       - short clip preview
    process_video(src, dst, params, progress, cancel)   - full export
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from . import air, link, ntsc  # noqa: F401  (air registers its stages on import)
from .interflab_stage import interflab_video_stage
from .modulation import Modulator
from .params import validate
from .video_io import VideoWriter, probe, read_frames

# A channel stage takes the composite signal of one field and returns a damaged one.
# Later steps (FM link, noise, multipath, interference, diversity) plug in here.
ChannelStage = Callable[[np.ndarray, ntsc.FieldCtx, dict, dict], np.ndarray]


def deinterlace(field: np.ndarray, parity: int, prev: np.ndarray | None, mode: str) -> np.ndarray:
    h, w, c = field.shape
    frame = np.empty((2 * h, w, c), np.float32)
    frame[parity::2] = field
    if mode == "weave" and prev is not None:
        frame[1 - parity::2] = prev
    elif parity == 0:          # data on even rows; odd row j sits between field[j] and field[j+1]
        frame[1::2] = 0.5 * (field + np.concatenate([field[1:], field[-1:]]))
    else:                      # data on odd rows; even row j sits between field[j-1] and field[j]
        frame[0::2] = 0.5 * (np.concatenate([field[:1], field[:-1]]) + field)
    return frame


class Pipeline:
    def __init__(self, params: dict | None = None, t0: float = 0.0):
        """t0: video time (s) of the first field, so time-based effects line up with a render from there."""
        self.p = validate(params)
        self.k0 = int(round(t0 * ntsc.FIELD_RATE))
        self.channel_stages: list[ChannelStage] = []
        if self.p["fm_enable"]:
            self.channel_stages.append(link.fm_link_stage)
        if self.p["if2_enable"]:                  # after the receiver, before the decoder
            self.channel_stages.append(interflab_video_stage)
        self.reset()

    def reset(self) -> None:
        self.index = self.k0                     # field count since video time 0
        self.offset = (self.k0 // 2 * sum(ntsc.LINES) + (self.k0 % 2) * ntsc.LINES[0]) * ntsc.SPL
        self.mod = Modulator(self.p, self.offset // ntsc.SPL)
        self.prev_field: np.ndarray | None = None
        self.state: dict = {"rng": np.random.default_rng(self.p["seed"])}

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """frame: (480, 640, 3) uint8. Uses one field of it; returns a (480, 640, 3) uint8 frame."""
        parity = self.index & 1
        ctx = ntsc.FieldCtx(self.index, parity, ntsc.LINES[parity], self.offset)
        field = frame[parity::2].astype(np.float32) / 255.0

        p = self.mod.apply(self.p, ctx.n_lines)  # settings driven by interflab Parameter sources
        sig = ntsc.encode_field(field, ctx, p)
        for stage in self.channel_stages:
            sig = stage(sig, ctx, p, self.state)
        out_field = ntsc.decode_field(sig, ctx, p, state=self.state)

        out = deinterlace(out_field, parity, self.prev_field, p["deinterlace"])
        self.prev_field = out_field
        self.offset += ctx.n_lines * ntsc.SPL
        self.index += 1
        return (out * 255.0 + 0.5).astype(np.uint8)


def process_still(image: np.ndarray, params: dict | None = None, fields: int = 4) -> np.ndarray:
    """Run one 480x640 RGB uint8 image through the chain (repeated so weave/state settle)."""
    pipe = Pipeline(params)
    out = None
    for _ in range(fields):
        out = pipe.process_frame(image)
    return out


def render_preview(src: str, params: dict | None = None, start: float = 0.0,
                   n_fields: int = 120) -> list[np.ndarray]:
    pipe = Pipeline(params, t0=start)
    return [pipe.process_frame(f) for f in read_frames(src, pipe.p, start=start, max_frames=n_fields)]


def process_video(src: str, dst: str, params: dict | None = None, start: float = 0.0,
                  duration: float | None = None,
                  progress: Callable[[int, int], None] | None = None,
                  cancel: Callable[[], bool] | None = None) -> dict:
    pipe = Pipeline(params, t0=start)
    info = probe(src)
    span = info["duration"] - start
    if duration:
        span = min(span, duration)
    total = max(int(span * ntsc.FIELD_RATE), 1)
    writer = VideoWriter(dst, pipe.p, audio_src=src, audio_codec=info["audio_codec"],
                         start=start, duration=duration)
    done = 0
    try:
        for frame in read_frames(src, pipe.p, start=start, duration=duration):
            if cancel and cancel():
                break
            writer.write(pipe.process_frame(frame))
            done += 1
            if progress and done % 12 == 0:
                progress(done, total)
    finally:
        writer.close()
    if progress:
        progress(done, total)
    return {"fields": done, "seconds": done / ntsc.FIELD_RATE, "cancelled": bool(cancel and cancel())}
