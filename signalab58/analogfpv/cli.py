"""Command line front end. Every flag is generated from the parameter schema."""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from . import params as P
from .pipeline import process_video


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="signallab58", description="Signallab58: simulate analog FPV video from a digital video.")
    ap.add_argument("input", nargs="?")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--preset", help="preset name (presets/NAME.json) or path to a preset file")
    ap.add_argument("--save-preset", metavar="FILE", help="write the resulting settings to a preset file and exit")
    ap.add_argument("--list-params", action="store_true", help="show all settings and exit")
    ap.add_argument("--start", type=float, default=0.0, help="start time in seconds")
    ap.add_argument("--duration", type=float, default=None, help="seconds to process")
    for p in P.PARAMS:
        kw = {"default": None, "help": f"[{p.group}] {p.help} (default {p.default})".replace("%", "%%")}
        flag = "--" + p.key.replace("_", "-")
        if p.kind == "bool":
            ap.add_argument(flag, action=argparse.BooleanOptionalAction, **kw)
            continue
        if p.kind == "choice":
            kw["choices"] = p.choices
        elif p.kind in ("int", "float"):
            kw["type"] = int if p.kind == "int" else float
        elif p.kind == "text":
            kw["type"] = str
        ap.add_argument(flag, **kw)
    return ap


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["gui"]:                                   # py -m analogfpv gui
        from .gui import main as gui_main
        gui_main()
        return 0
    ap = build_parser()
    a = ap.parse_args(argv)

    if a.list_params:
        for g in P.GROUPS:
            print(f"\n[{g}]")
            for p in (q for q in P.PARAMS if q.group == g):
                rng = f" range {p.min}..{p.max}" if p.min is not None else (f" one of {p.choices}" if p.choices else "")
                tag = "  (advanced)" if p.advanced else ""
                print(f"  --{p.key.replace('_', '-'):<22} default {p.default}{rng} {p.unit}{tag}\n      {p.help}")
        return 0

    values = P.load_preset(a.preset) if a.preset else P.defaults()
    for p in P.PARAMS:
        v = getattr(a, p.key)
        if v is not None:
            values[p.key] = v
    values = P.validate(values)

    if a.save_preset:
        P.save_preset(values, a.save_preset)
        print(f"saved {a.save_preset}")
        return 0
    if not (a.input and a.output):
        ap.error("input and output files are required")

    if not Path(a.input).is_file():
        ap.error(f"input file not found: {a.input}")
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        ap.error("FFmpeg/ffprobe not found on PATH (Windows: winget install ffmpeg, then reopen the terminal)")

    t0 = time.time()

    def progress(done, total):
        pct = min(100.0 * done / total, 100.0)
        rate = done / max(time.time() - t0, 1e-6)
        sys.stderr.write(f"\r{pct:5.1f}%  {done}/{total} fields  {rate:4.1f} fields/s")
        sys.stderr.flush()

    stats = process_video(a.input, a.output, values, start=a.start, duration=a.duration, progress=progress)
    sys.stderr.write(f"\nDone: {stats['seconds']:.1f} s of video in {time.time() - t0:.1f} s -> {a.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
