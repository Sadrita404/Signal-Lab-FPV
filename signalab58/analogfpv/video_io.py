"""Video decode/encode through FFmpeg pipes (no temp files)."""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Iterator

import numpy as np

from .ntsc import RASTER_H, RASTER_W

# In the windowed .exe there is no console, so stop ffmpeg from flashing one open for every call.
_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


def probe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
        capture_output=True, text=True, check=True, **_NO_WINDOW).stdout
    info = json.loads(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    duration = float(info["format"].get("duration") or v.get("duration") or 0.0)
    return {"width": int(v["width"]), "height": int(v["height"]), "duration": duration,
            "audio_codec": a["codec_name"] if a else None}


def fit_filter(mode: str) -> str:
    w, h = RASTER_W, RASTER_H
    if mode == "stretch":
        return f"scale={w}:{h},setsar=1"
    if mode == "crop":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"


def read_frames(path: str, p: dict, start: float = 0.0, duration: float | None = None,
                max_frames: int | None = None) -> Iterator[np.ndarray]:
    """Yield 480x640 RGB uint8 frames at 59.94/s (one per video field)."""
    cmd = ["ffmpeg", "-v", "error"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", path]
    if duration:
        cmd += ["-t", str(duration)]
    cmd += ["-vf", f"fps=60000/1001,{fit_filter(p['fit_mode'])}",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, **_NO_WINDOW)
    size = RASTER_W * RASTER_H * 3
    n = 0
    try:
        while max_frames is None or n < max_frames:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(RASTER_H, RASTER_W, 3)
            n += 1
    finally:
        proc.kill()
        proc.wait()


class VideoWriter:
    """Pipe RGB frames (59.94 fps) into an H.264 mp4, copying the source audio if there is any."""

    def __init__(self, path: str, p: dict, audio_src: str | None = None,
                 audio_codec: str | None = None, start: float = 0.0, duration: float | None = None):
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{RASTER_W}x{RASTER_H}", "-r", "60000/1001", "-i", "-"]
        has_audio = bool(audio_src and audio_codec)
        if has_audio:
            if start:
                cmd += ["-ss", str(start)]
            if duration:
                cmd += ["-t", str(duration)]
            cmd += ["-i", audio_src]
        cmd += ["-map", "0:v"]
        if has_audio:
            cmd += ["-map", "1:a:0", "-c:a", "copy" if audio_codec == "aac" else "aac", "-shortest"]
        u = p["upscale"]
        if u > 1:
            cmd += ["-vf", f"scale=iw*{u}:ih*{u}:flags=lanczos"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(p["crf"]),
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", path]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, **_NO_WINDOW)

    def write(self, frame: np.ndarray) -> None:
        self.proc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        finally:
            self.proc.wait()
