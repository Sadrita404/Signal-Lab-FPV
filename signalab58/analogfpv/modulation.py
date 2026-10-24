"""interflab sources as parameter controls ("Parameter" output), so settings can change over time.

A source whose output is set to Parameter (to_mix False) is not added to the signal. Instead its value,
taken once per field, drives analogfpv settings through links stored in the `mod_links` setting:

    [{"src": "lfo", "param": "link_cnr_db", "mode": "add", "amount": 1.0}, ...]

mode "replace": setting = source value * amount.  mode "add": setting = setting + source value * amount.
One source can drive any number of settings. Results are clamped to each setting's range.
The control patch runs at the line rate (one sample per line), so phase_y still means "per line".
"""
from __future__ import annotations

import json

import numpy as np

from . import ntsc
from .params import BY_KEY, PARAMS

MODES = ("replace", "add")
# settings that are only read when the chain is built, or that must stay fixed during a render
FIXED = {"fm_oversample", "filter_taps", "if_filter_taps", "mp_paths", "upscale", "crf", "seed"}
TARGETS = tuple(p.key for p in PARAMS if p.kind in ("float", "int") and p.key not in FIXED)


def parse_links(text: str) -> list[dict]:
    """The mod_links setting -> list of links (raises ValueError on a bad entry)."""
    if not str(text).strip():
        return []
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"mod_links is not valid JSON: {e}") from None
    out = []
    for ln in raw:
        if ln.get("param") not in TARGETS:
            raise ValueError(f"mod_links: {ln.get('param')!r} cannot be driven by a source")
        if ln.get("mode", "add") not in MODES:
            raise ValueError(f"mod_links: mode must be one of {MODES}")
        out.append(dict(src=str(ln["src"]), param=ln["param"], mode=ln.get("mode", "add"),
                        amount=float(ln.get("amount", 1.0))))
    return out


def dump_links(links: list[dict]) -> str:
    return json.dumps(links) if links else ""


class Modulator:
    """mod = Modulator(p, start_line); p_field = mod.apply(p, n_lines) once per field, in order."""

    def __init__(self, p: dict, start_line: int = 0):
        self.links = parse_links(p["mod_links"])
        self.engine = None
        if not self.links:
            return
        from interflab import Engine, Patch
        from .interflab_stage import find_patch
        patch = Patch.load(str(find_patch(p["if2_patch"])))
        names = [s["name"] for s in patch.sources]
        missing = sorted({ln["src"] for ln in self.links} - set(names))
        if missing:
            raise ValueError(f"mod_links: the patch has no source named {', '.join(missing)}")
        self.index = {n: names.index(n) for n in set(names)}
        patch.fs, patch.spl = ntsc.FS / ntsc.SPL, 1
        self.engine = Engine(patch)
        while self.engine.pos < start_line:          # run up to the start (seek would restart the phases)
            self.engine.render(min(start_line - self.engine.pos, 1 << 16))

    def apply(self, p: dict, n_lines: int) -> dict:
        if self.engine is None:
            return p
        _mix, outs = self.engine.render(n_lines, return_sources=True)
        q = dict(p)
        for ln in sorted(self.links, key=lambda ln: ln["mode"] != "replace"):     # replace first, then adds
            v = float(np.mean(outs[self.index[ln["src"]]])) * ln["amount"]
            q[ln["param"]] = v if ln["mode"] == "replace" else q[ln["param"]] + v
        for k in {ln["param"] for ln in self.links}:
            par = BY_KEY[k]
            x = float(np.clip(q[k], par.min, par.max))
            q[k] = int(round(x)) if par.kind == "int" else x
        return q
