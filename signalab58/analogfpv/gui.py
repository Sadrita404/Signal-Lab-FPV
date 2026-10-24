"""analogfpv window (tkinter): every processing step can be switched on/off and tuned, with a preview.

The settings widgets are generated from params.PARAMS, grouped into the signal chain's steps (STEPS).
A setting that no step claims shows up under "Other", so new parameters never get lost.
The interflab patch editor sits in its own tab and can feed the interflab step directly. Its sources set
to Parameter show up as dots under the step list: drag a dot onto a setting to drive it over time
(replace the value, or add to it). Links are kept in the mod_links setting, so presets and the CLI use them.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

import cv2
import numpy as np

try:                                    # optional: drag and drop of files (py -m pip install tkinterdnd2)
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False

from . import APP_LOGO, APP_NAME
from . import params as P
from .modulation import TARGETS, dump_links, parse_links
from .pipeline import Pipeline, process_video
from .video_io import probe, read_frames

PRESET_DIR = Path(__file__).resolve().parent.parent / "presets"
PREVIEW_W, PREVIEW_H = 560, 420
VIDEO_TYPES = [("video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("all files", "*.*")]
DOT_COLORS = ("#e4572e", "#1f9e9e", "#e8a317", "#7b5ea7", "#43a047", "#d81b60", "#3f88c5", "#8d6e63")
C = dict(bg="#f4f5f7", text="#1f2430", muted="#6b7280", accent="#2f6fde", accent_dark="#2457b3",
         sel="#dce7fb", drop="#ffe9a8", border="#d3d7de", screen="#15171c")

# (step name, on/off setting or None = always on, setting-key prefixes/keys, short description) in signal order
STEPS = [
    ("Input", None, ("fit_mode",), "How the video is fitted to the 4:3 analog picture."),
    ("Camera / VTX encoder", None, ("luma_bw_mhz", "i_bw_mhz", "q_bw_mhz", "black_setup_ire", "composite_clip_ire",
                                    "sync_level_ire", "burst_amp_ire", "hsync_len", "burst_cycles", "filter_taps"),
     "Turns the picture into an NTSC composite signal."),
    ("FM radio link", "fm_enable", ("fm_swing_mhz", "fm_white_glitch", "fm_fit_ratio", "fm_oversample"),
     "Sends the signal over the 5.8 GHz FM link. Off = skip all radio effects below."),
    ("Multipath (reflections)", "mp_enable", ("mp_",), "Echoes off ground, walls and trees: hue flicker and bands."),
    ("Static dips", "dip_enable", ("dip_",), "Short dips: hue shift builds up, then a few lines of static."),
    ("Narrowband interferer", "intf_enable", ("intf_",), "A single interfering carrier near your channel."),
    ("Radio noise", "noise_enable", ("link_cnr_db", "cnr_keyframes", "noise_ref_bw_mhz"), "Snow from a weak signal."),
    ("Random fading", "fade_enable", ("fade_",), "Signal strength wobbling as you fly (needs noise)."),
    ("Receiver", None, ("rx_if_bw_mhz", "if_filter_taps"), "The goggles' radio filter."),
    ("interflab interference", "if2_enable", ("if2_",), "Your interflab patch, added before the decoder. Sources set to "
     "Parameter show up as dots here: drag one onto any setting to change it over time."),
    ("Goggle input clipping", "rx_clip_enable", ("rx_clip_",), "Signal pushed past the input range is cut flat."),
    ("Sync recovery", "sync_enable", ("hsync_lock_lines", "hsync_drift", "sync_slice_ire", "vsync_"),
     "Finding the sync pulses: missed pulses make lines slide sideways, a missed vertical sync rolls the picture."),
    ("Color lock", "burst_lock", ("burst_lock_lines", "pll_"), "The color reference locked to the burst."),
    ("Color gain + killer", "color_killer", ("acc_", "killer_level"), "Automatic color gain; gray when lock is lost."),
    ("Decoder", None, ("comb_amount", "dec_chroma_bw_mhz", "sharpness", "chroma_bp_", "sharpness_corner_mhz",
                       "hue_offset_deg", "deinterlace"), "Separating brightness and color, picture controls."),
    ("Synthetic hue bands", "hb_enable", ("hb_",), "Old painted-on hue bands (not physical)."),
    ("Output", None, ("upscale", "crf", "seed"), "Export size, quality and random seed."),
]
HIDDEN = {"mod_links"}               # edited by dragging dots, not as a text box


def _step_keys():
    claimed, out = set(HIDDEN), []
    for name, toggle, keys, desc in STEPS:
        mine = [p.key for p in P.PARAMS if p.key != toggle and p.key not in claimed
                and any(p.key == k or (k.endswith("_") and p.key.startswith(k)) for k in keys)]
        claimed.update(mine)
        if toggle:
            claimed.add(toggle)
        out.append((name, toggle, mine, desc))
    rest = [p.key for p in P.PARAMS if p.key not in claimed]
    if rest:
        out.append(("Other", None, rest, "Settings not sorted into a step yet."))
    return out


def _style(root: tk.Tk):
    st = ttk.Style(root)
    if "clam" in st.theme_names():
        st.theme_use("clam")
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        tkfont.nametofont(name).configure(size=10)
    bold = tkfont.nametofont("TkDefaultFont").copy()
    bold.configure(weight="bold")
    link = tkfont.nametofont("TkDefaultFont").copy()
    link.configure(underline=True)
    root.configure(background=C["bg"])
    st.configure(".", background=C["bg"], foreground=C["text"])
    st.configure("TLabelframe", background=C["bg"], bordercolor=C["border"], relief="solid", borderwidth=1)
    st.configure("TLabelframe.Label", background=C["bg"], foreground=C["text"], font=bold)
    st.configure("TButton", padding=(10, 4))
    st.configure("Accent.TButton", background=C["accent"], foreground="white", font=bold, padding=(16, 6))
    st.map("Accent.TButton", background=[("disabled", "#a9b4c6"), ("active", C["accent_dark"])],
           foreground=[("disabled", "#eef1f6")])
    st.configure("Muted.TLabel", foreground=C["muted"])
    st.configure("Link.TLabel", foreground=C["accent"], font=link)
    st.configure("Drop.TLabel", background=C["drop"])
    st.configure("TEntry", fieldbackground="white", padding=3)
    st.configure("TCombobox", fieldbackground="white", padding=3)
    st.map("TCombobox", fieldbackground=[("readonly", "white")])
    st.configure("Horizontal.TProgressbar", background=C["accent"], troughcolor="#e1e5ec", bordercolor=C["border"])
    st.configure("TNotebook", background=C["bg"], borderwidth=0)
    big = tkfont.nametofont("TkDefaultFont").copy()
    big.configure(size=12, weight="bold")
    st.configure("TNotebook.Tab", padding=(14, 4), background="#dfe3e9", foreground=C["muted"])
    st.map("TNotebook.Tab",                                   # the open tab is the big, bright one
           padding=[("selected", (22, 9))], font=[("selected", big)],
           background=[("selected", "white"), ("active", "#eceff3")],
           foreground=[("selected", C["accent"])], expand=[("selected", (2, 3, 2, 0))])
    root.option_add("*Listbox.background", "white")
    root.option_add("*Menu.tearOff", 0)


class Tooltip:
    """Small help box that appears next to the mouse after hovering a widget for a moment."""

    def __init__(self, widget, text: str, delay_ms: int = 450):
        self.w, self.text, self.delay, self.job, self.tip = widget, text, delay_ms, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._hide()
        self.job = self.w.after(self.delay, self._show)

    def _show(self):
        x, y = self.w.winfo_pointerx() + 14, self.w.winfo_pointery() + 16
        self.tip = tk.Toplevel(self.w)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", wraplength=340, background="#ffffe0",
                 relief="solid", borderwidth=1, padx=6, pady=4).pack()

    def _hide(self, _e=None):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


class ScrollFrame(ttk.Frame):
    """A frame with a vertical scrollbar; put widgets in .inner. Scrolls with the mouse wheel while hovered."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, background=C["bg"], highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        self.bind_all("<Button-4>", self._wheel, add="+")
        self.bind_all("<Button-5>", self._wheel, add="+")

    def _wheel(self, e):
        w = self.winfo_containing(e.x_root, e.y_root)
        while w is not None and w is not self:
            w = w.master
        if w is None or self.inner.winfo_height() <= self.canvas.winfo_height():
            return
        step = -1 if getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(step * 2, "units")

    def top(self):
        self.canvas.yview_moveto(0)


def _tip_text(p) -> str:
    rng = f"\nRange {p.min:g} to {p.max:g} {p.unit}".rstrip() if p.min is not None else ""
    more = "\nDrag a parameter dot here to change it over time." if p.key in TARGETS else ""
    return f"{p.label}\n{p.help}{rng}\nDefault: {p.default}{more}"


def _photo(rgb: np.ndarray) -> tk.PhotoImage:
    img = cv2.resize(rgb, (PREVIEW_W, PREVIEW_H), interpolation=cv2.INTER_AREA)[:, :, ::-1]
    return tk.PhotoImage(data=base64.b64encode(cv2.imencode(".png", img)[1].tobytes()).decode())


def _icon() -> tk.PhotoImage:
    """The SL58 logo as a window icon, drawn here so no image file has to ship."""
    img = np.zeros((64, 64, 3), np.uint8)
    img[:] = (222, 111, 47)                                   # accent blue (BGR)
    for text, y in (("SL", 30), ("58", 58)):
        (w, _h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 0.95, 2)
        cv2.putText(img, text, ((64 - w) // 2, y), cv2.FONT_HERSHEY_DUPLEX, 0.95, (255, 255, 255), 2, cv2.LINE_AA)
    return tk.PhotoImage(data=base64.b64encode(cv2.imencode(".png", img)[1].tobytes()).decode())


def _open_folder(path: Path, select: Path | None = None):
    """Open a folder in the file manager (on Windows with the file selected, when given)."""
    if sys.platform.startswith("win"):
        if select is not None and select.exists():
            subprocess.Popen(["explorer", "/select,", str(select)])
        else:
            os.startfile(str(path))                          # noqa: S606 (Windows only)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


class AnalogFPVApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self.values = P.defaults()
        self.links: list[dict] = []
        self.steps = _step_keys()
        self.sel = 1
        self._busy = None            # running worker thread
        self._cancel = False
        self._job = {}
        self._photo = None
        self._auto_out = ""          # output name we filled in ourselves (replaced when the input changes)
        self._saved: Path | None = None
        self._row_of = {}            # setting-row widget -> (setting key, its label): drop targets
        self._drop_lab = None
        self._drag = None
        self._sig = None
        self._tmp_patch = Path(tempfile.gettempdir()) / "analogfpv_gui_patch.json"
        self.use_tab = tk.BooleanVar(value=True)
        self._build()
        self._overlay = None
        self._overlay_ok = sys.platform.startswith("win")   # see-through windows need Windows
        self._step_of = {k: i for i, (_n, _t, keys, _d) in enumerate(self.steps) for k in keys}
        if _HAS_DND:
            self.after_idle(self._enable_drop)
        self._show_step(self.sel)
        self._refresh_dots()

    # ------------------------------------------------------------------ layout
    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 6))
        tk.Label(head, text=APP_LOGO, font=("TkDefaultFont", 12, "bold"), foreground="white", background=C["accent"],
                 padx=8, pady=2).pack(side="left")
        tk.Label(head, text=APP_NAME, font=("TkDefaultFont", 14, "bold"), foreground=C["text"],
                 background=C["bg"], padx=8).pack(side="left")
        ttk.Label(head, text="analog FPV signal lab", style="Muted.TLabel").pack(side="left")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        conv = ttk.Frame(nb, padding=8)
        nb.add(conv, text="Converter")
        try:
            from interflab.gui import InterflabPanel
            self.ifl = InterflabPanel(nb, on_change=self._patch_changed)
            nb.add(self.ifl, text="interflab patch")
        except ImportError:
            self.ifl = None

        # ---- files and render
        ff = ttk.LabelFrame(conv, text="Video", padding=(10, 6))
        ff.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.inp, self.out = tk.StringVar(), tk.StringVar()
        self.info = tk.StringVar(value="Choose the video you want to convert.")
        ttk.Label(ff, text="Input").grid(row=0, column=0, sticky="w")
        e_in = ttk.Entry(ff, textvariable=self.inp)
        e_in.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        e_in.bind("<Return>", lambda e: self._input_changed())
        e_in.bind("<FocusOut>", lambda e: self._input_changed())
        ttk.Button(ff, text="Browse...", command=self.pick_input).grid(row=0, column=2, sticky="ew")
        ttk.Label(ff, textvariable=self.info, style="Muted.TLabel").grid(row=0, column=3, sticky="w", padx=10)
        ttk.Label(ff, text="Save as").grid(row=1, column=0, sticky="w")
        ttk.Entry(ff, textvariable=self.out).grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        ttk.Button(ff, text="Browse...", command=self.pick_output).grid(row=1, column=2, sticky="ew")
        ttk.Button(ff, text="Open folder", command=self.open_out_folder).grid(row=1, column=3, sticky="w", padx=10)

        rf = ttk.Frame(ff)
        rf.grid(row=2, column=1, sticky="w", padx=6, pady=(4, 0))
        ttk.Label(ff, text="Range").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.start, self.dur = tk.StringVar(value="0"), tk.StringVar(value="")
        ttk.Label(rf, text="start at").pack(side="left")
        ttk.Entry(rf, textvariable=self.start, width=7).pack(side="left", padx=4)
        ttk.Label(rf, text="s,  length").pack(side="left")
        ttk.Entry(rf, textvariable=self.dur, width=7).pack(side="left", padx=4)
        ttk.Label(rf, text="s  (empty = to the end)", style="Muted.TLabel").pack(side="left")
        self.render_btn = ttk.Button(ff, text="Render video", style="Accent.TButton", command=self.do_render)
        self.render_btn.grid(row=0, column=4, rowspan=2, sticky="nsew", padx=(10, 0))
        ttk.Button(ff, text="Cancel", command=self.cancel).grid(row=2, column=4, sticky="ew", padx=(10, 0), pady=(4, 0))
        self.prog = ttk.Progressbar(ff, maximum=1000)
        self.prog.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 2))
        self.saved_lab = ttk.Label(ff, text="", style="Link.TLabel", cursor="hand2")
        self.saved_lab.grid(row=4, column=0, columnspan=4, sticky="w")
        self.saved_lab.bind("<Button-1>", lambda e: self._saved and _open_folder(self._saved.parent, self._saved))
        Tooltip(self.saved_lab, "Click to open the folder.")
        ff.columnconfigure(1, weight=1)

        # ---- presets
        bar = ttk.Frame(conv)
        bar.grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(bar, text="Preset").pack(side="left")
        self.preset = ttk.Combobox(bar, state="readonly", width=22, postcommand=self._list_presets)
        self.preset.pack(side="left", padx=6)
        self.preset.bind("<<ComboboxSelected>>", lambda e: self._load_path(PRESET_DIR / f"{self.preset.get()}.json"))
        ttk.Button(bar, text="Open...", command=self.load_preset).pack(side="left", padx=2)
        ttk.Button(bar, text="Save as...", command=self.save_preset).pack(side="left", padx=2)
        ttk.Button(bar, text="Defaults", command=self.reset).pack(side="left", padx=2)
        self.show_adv = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show advanced settings", variable=self.show_adv,
                        command=lambda: self._show_step(self.sel)).pack(side="left", padx=16)

        # ---- left: steps with on/off boxes, then the parameter dots
        left = ttk.Frame(conv)
        left.grid(row=2, column=0, sticky="nsw", padx=(0, 8))
        sf = ttk.LabelFrame(left, text="Processing steps", padding=4)
        sf.pack(fill="x")
        self.step_vars, self.step_rows = {}, []
        for i, (name, toggle, _keys, desc) in enumerate(self.steps):
            row = tk.Frame(sf, background=C["bg"])
            row.pack(fill="x")
            if toggle:
                v = tk.BooleanVar(value=bool(self.values[toggle]))
                self.step_vars[toggle] = v
                cb = tk.Checkbutton(row, variable=v, background=C["bg"], activebackground=C["bg"], highlightthickness=0,
                                    borderwidth=0, command=lambda k=toggle, v=v: self._set(k, v.get()))
            else:
                cb = tk.Label(row, text="", width=2, background=C["bg"])
            cb.pack(side="left")
            lab = tk.Label(row, text=name, anchor="w", width=24, background=C["bg"], foreground=C["text"],
                           padx=4, pady=3, cursor="hand2")
            lab.pack(side="left", fill="x", expand=True)
            if toggle == "if2_enable":                     # the parameter dots sit next to interflab
                self.dot_row = tk.Frame(row, background=C["bg"])
                self.dot_row.pack(side="left", padx=(0, 4))
            for w in (row, lab):
                w.bind("<Button-1>", lambda e, i=i: self._show_step(i))
            Tooltip(lab, desc + ("\nTick the box to switch this step on or off." if toggle else "\nAlways on."))
            self.step_rows.append((row, cb, lab))

        # ---- middle: settings of the selected step
        self.set_box = ttk.LabelFrame(conv, text="", padding=(8, 4))
        self.set_box.grid(row=2, column=1, sticky="nsew", padx=(0, 8))
        self.set_scroll = ScrollFrame(self.set_box)
        self.set_scroll.pack(fill="both", expand=True)
        self.set_frame = self.set_scroll.inner

        # ---- right: preview (controls packed first so the picture can never push them away)
        pf = ttk.LabelFrame(conv, text="Preview", padding=6)
        pf.grid(row=2, column=2, sticky="nsew")
        row = ttk.Frame(pf)
        row.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Label(row, text="at").pack(side="left")
        self.t_prev = tk.DoubleVar(value=0.0)
        self.t_scale = ttk.Scale(row, from_=0, to=10, orient="horizontal", variable=self.t_prev, length=260)
        self.t_scale.pack(side="left", fill="x", expand=True, padx=4)
        t_lab = ttk.Label(row, text="0.0 s", width=7)
        t_lab.pack(side="left")
        self.t_prev.trace_add("write", lambda *a: t_lab.config(text=f"{self.t_prev.get():.1f} s"))
        self.show_orig = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="original", variable=self.show_orig).pack(side="left", padx=8)
        ttk.Button(row, text="Preview", style="Accent.TButton", command=self.do_preview).pack(side="left")
        self._blank = tk.PhotoImage(width=PREVIEW_W, height=PREVIEW_H)
        self.preview = tk.Label(pf, image=self._blank, text="Choose an input video, then press Preview.",
                                compound="center", foreground="#9aa3b2", background=C["screen"],
                                width=PREVIEW_W, height=PREVIEW_H)
        self.preview.pack(anchor="n")

        self.status = tk.StringVar(value="Hover over a setting for help. Drop a video, preset or patch anywhere."
                                   if _HAS_DND else "Hover over a setting for help. (For drag and drop: "
                                   "py -3.13 -m pip install tkinterdnd2)")
        ttk.Label(conv, textvariable=self.status, style="Muted.TLabel", anchor="w").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        conv.columnconfigure(1, weight=1)
        conv.rowconfigure(2, weight=1)

    # ------------------------------------------------------------------ steps and settings widgets
    def _refresh_steps(self):
        hit = {ln["param"] for ln in self.links}
        for j, ((row, cb, lab), (name, _t, keys, _d)) in enumerate(zip(self.step_rows, self.steps)):
            bg = C["sel"] if j == self.sel else C["bg"]
            for w in (row, cb, lab):
                w.config(background=bg)
            if lab.master is self.dot_row.master:
                for w in [self.dot_row] + self.dot_row.winfo_children():
                    w.config(background=bg)
            if isinstance(cb, tk.Checkbutton):
                cb.config(activebackground=bg)
            lab.config(text=name + ("  ●" if hit & set(keys) else ""))

    def _show_step(self, i):
        self.focus_set()                                   # commit a half-typed value first
        self.sel = i
        self._refresh_steps()
        for w in self.set_frame.winfo_children():
            w.destroy()
        self._row_of = {}
        self._drop_lab = None
        name, toggle, keys, desc = self.steps[i]
        self.set_box.config(text=name)
        ttk.Label(self.set_frame, text=desc, wraplength=420, style="Muted.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        r = 1
        shown = [k for k in keys if self.show_adv.get() or not P.BY_KEY[k].advanced
                 or any(ln["param"] == k for ln in self.links)]
        for k in shown:
            r = self._widget(P.BY_KEY[k], r)
        hidden = len(keys) - len(shown)
        if hidden:
            ttk.Label(self.set_frame, text=f"{hidden} advanced setting(s) hidden", style="Muted.TLabel").grid(
                row=r, column=0, columnspan=4, sticky="w", pady=(8, 0))
        if toggle == "if2_enable" and self.ifl is not None:
            ttk.Checkbutton(self.set_frame, text="Use the patch from the interflab tab (instead of the file above)",
                            variable=self.use_tab, command=self._refresh_dots).grid(
                row=r + 1, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.set_frame.columnconfigure(1, weight=1, minsize=140)
        self.set_scroll.top()

    def _widget(self, p, r):
        lab = ttk.Label(self.set_frame, text=p.label)
        lab.grid(row=r, column=0, sticky="w", padx=(0, 8), pady=2)
        val = self.values[p.key]
        extra = []
        if p.kind == "bool":
            v = tk.BooleanVar(value=bool(val))
            w = ttk.Checkbutton(self.set_frame, variable=v, command=lambda: self._set(p.key, v.get()))
            w.grid(row=r, column=1, sticky="w")
        elif p.kind == "choice":
            v = tk.StringVar(value=val)
            w = ttk.Combobox(self.set_frame, textvariable=v, values=p.choices, state="readonly", width=12)
            w.bind("<<ComboboxSelected>>", lambda e: self._set(p.key, v.get()))
            w.grid(row=r, column=1, sticky="w")
        elif p.kind == "text":
            v = tk.StringVar(value=val)
            w = ttk.Entry(self.set_frame, textvariable=v, width=34)
            for ev in ("<Return>", "<FocusOut>"):
                w.bind(ev, lambda e: self._set(p.key, v.get()))
            w.grid(row=r, column=1, columnspan=3, sticky="ew")
        else:
            v = tk.DoubleVar(value=val)
            ent = ttk.Entry(self.set_frame, width=7)
            ent.insert(0, f"{val:g}")

            def from_scale(s, p=p, ent=ent):
                step = p.step or 0.01
                x = p.min + round((float(s) - p.min) / step) * step         # snap to the setting's step
                x = int(round(x)) if p.kind == "int" else round(x, 6)
                if x != self.values[p.key]:
                    ent.delete(0, "end")
                    ent.insert(0, f"{x:g}")
                    self._set(p.key, x)

            def from_entry(e, p=p, ent=ent, v=v):
                try:
                    x = P.coerce(p, float(ent.get()) if p.kind == "float" else int(float(ent.get())))
                except ValueError as err:
                    self.status.set(str(err))
                    return
                self._set(p.key, x)
                v.set(x)

            w = ttk.Scale(self.set_frame, from_=p.min, to=p.max, orient="horizontal", length=160, variable=v,
                          command=from_scale)
            w.grid(row=r, column=1, sticky="ew")
            ent.grid(row=r, column=2, padx=4)
            ent.bind("<Return>", from_entry)
            ent.bind("<FocusOut>", from_entry)
            unit = ttk.Label(self.set_frame, text=p.unit, style="Muted.TLabel")
            unit.grid(row=r, column=3, sticky="w")
            extra = [ent, unit]
        mine = [ln for ln in self.links if ln["param"] == p.key]
        chips = ttk.Frame(self.set_frame)
        if mine:                                            # the dots driving this setting, on a line below it
            chips.grid(row=r + 1, column=1, columnspan=3, sticky="w", pady=(0, 4))
        for ln in mine:
            chip = tk.Label(chips, text=f"● {ln['src']}  {ln['mode']} ×{ln['amount']:g}", cursor="hand2",
                            foreground=self._dot_color(ln["src"]), background=C["bg"], padx=2)
            chip.pack(side="left")
            chip.bind("<Button-1>", lambda e, ln=ln: self._link_menu(e, ln))
            chip.bind("<Button-3>", lambda e, ln=ln: self._link_menu(e, ln))
            Tooltip(chip, "Driven by this parameter dot. Click to change replace/add, the amount, or remove it.")
            extra.append(chip)
        for x in [lab, w, chips] + extra:
            self._row_of[x] = (p.key, lab)
        for x in [lab, w] + extra[:1]:
            x.bind("<Enter>", lambda e, h=p.help: self.status.set(h), add="+")
            Tooltip(x, _tip_text(p))
        return r + (2 if mine else 1)

    def _set(self, key, value):
        self.values[key] = value
        if key in self.step_vars:
            self.step_vars[key].set(bool(value))
        if key == "if2_patch":
            self._refresh_dots()

    # ------------------------------------------------------------------ parameter dots
    def _sources(self) -> list[dict]:
        """Sources of the patch the converter will use (interflab tab or the if2_patch file)."""
        if self.ifl is not None and self.use_tab.get():
            return self.ifl.patch.sources
        try:
            from interflab import Patch
            from .interflab_stage import find_patch
            return Patch.load(str(find_patch(self.values["if2_patch"]))).sources
        except Exception:                                    # missing or broken file: no dots
            return []

    def _dots(self) -> list[str]:
        return [s["name"] for s in self._sources() if not s["to_mix"]]

    def _dot_color(self, name: str) -> str:
        names = [s["name"] for s in self._sources()]
        return DOT_COLORS[names.index(name) % len(DOT_COLORS)] if name in names else "#9aa3b2"

    def _patch_changed(self, patch):
        sig = [(s["name"], s["to_mix"]) for s in patch.sources]
        if sig == self._sig:
            return
        if self._sig is not None and len(sig) == len(self._sig):          # a source was renamed: keep its links
            renamed = False
            for (old, _a), (new, _b) in zip(self._sig, sig):
                if old != new:
                    for ln in self.links:
                        if ln["src"] == old:
                            ln["src"], renamed = new, True
            if renamed:
                self._links_changed(redraw_settings=True)
        self._sig = sig
        if self.use_tab.get() and hasattr(self, "dot_row"):
            self._refresh_dots()

    def _refresh_dots(self):
        for w in self.dot_row.winfo_children():
            w.destroy()
        bg = self.dot_row.cget("background")
        for name in self._dots():
            dot = tk.Canvas(self.dot_row, width=16, height=16, highlightthickness=0, background=bg, cursor="fleur")
            dot.create_oval(2, 2, 14, 14, fill=self._dot_color(name), outline="")
            dot.pack(side="left", padx=1)
            dot.bind("<ButtonPress-1>", lambda e, n=name: self._drag_start(e, n))
            dot.bind("<B1-Motion>", self._drag_move)
            dot.bind("<ButtonRelease-1>", self._drag_end)
            dot.bind("<Enter>", lambda e, n=name, d=dot: self._show_cables(n, d), add="+")
            dot.bind("<Leave>", lambda e: self._hide_cables(), add="+")
            drives = [f"{P.BY_KEY[ln['param']].label} ({ln['mode']} \u00d7{ln['amount']:g})"
                      for ln in self.links if ln["src"] == name]
            Tooltip(dot, f"{name}\nDrag onto a setting to drive it with this source. One dot can drive many settings."
                    + ("\nDrives: " + ", ".join(drives) if drives else ""))

    # ------------------------------------------------------------------ cables shown while hovering a dot
    def _cable_ends(self, name):
        """Screen points each of this dot's links goes to: the setting's label, or its step's name if not open."""
        ends = []
        for ln in self.links:
            if ln["src"] != name:
                continue
            lab = next((l for w, (k, l) in self._row_of.items() if k == ln["param"]), None)
            if lab is not None and lab.winfo_ismapped():
                ends.append((lab.winfo_rootx() - 2, lab.winfo_rooty() + lab.winfo_height() // 2, lab))
            elif ln["param"] in self._step_of:
                row, _cb, slab = self.step_rows[self._step_of[ln["param"]]]
                ends.append((row.winfo_rootx(), row.winfo_rooty() + row.winfo_height() // 2, slab))
        return ends

    def _show_cables(self, name, dot):
        if self._drag is not None:
            return
        ends = self._cable_ends(name)
        if not ends:
            return
        color = self._dot_color(name)
        x0, y0 = dot.winfo_rootx() + 8, dot.winfo_rooty() + 8
        if not self._overlay_ok:                              # no see-through window: just light up the ends
            self._lit = [lab for *_xy, lab in ends]
            for lab in self._lit:
                (lab.config(style="Drop.TLabel") if isinstance(lab, ttk.Label) else lab.config(background=C["drop"]))
            return
        top = self.winfo_toplevel()
        ox, oy, w, h = top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height()
        if self._overlay is None:
            self._overlay = tk.Toplevel(top)
            self._overlay.wm_overrideredirect(True)
            self._overlay.transient(top)
            key = "#ff00fe"
            try:                                              # key color = fully see-through and click-through
                self._overlay.attributes("-transparentcolor", key)
                self._overlay.attributes("-alpha", 0.6)
            except tk.TclError:
                self._overlay.destroy()
                self._overlay, self._overlay_ok = None, False
                return self._show_cables(name, dot)
            self._cv = tk.Canvas(self._overlay, background=key, highlightthickness=0, borderwidth=0)
            self._cv.pack(fill="both", expand=True)
        self._overlay.wm_geometry(f"{w}x{h}+{ox}+{oy}")
        cv = self._cv
        cv.delete("all")
        for x1, y1, _lab in ends:
            ax, ay, bx, by = x0 - ox, y0 - oy, x1 - ox, y1 - oy
            sag = 30 + 0.25 * np.hypot(bx - ax, by - ay)              # hangs down like a patch cable
            t = np.linspace(0.0, 1.0, 40)[:, None]
            p0, p1, p2, p3 = (np.array(v, float) for v in ((ax, ay), (ax, ay + sag), (bx, by + sag), (bx, by)))
            pts = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3
            pts = pts[np.hypot(pts[:, 0] - ax, pts[:, 1] - ay) > 11]   # keep the dot itself clear of the cable,
            if len(pts) < 2:                                            # so the pointer stays on the dot
                continue
            cv.create_line(*pts.ravel(), smooth=True, width=5, fill=color, capstyle="round", joinstyle="round")
            cv.create_oval(bx - 5, by - 5, bx + 5, by + 5, fill=color, outline="")
        self._overlay.deiconify()
        self._overlay.lift()

    def _hide_cables(self):
        if self._overlay is not None:
            self._overlay.withdraw()
        for lab in getattr(self, "_lit", []):
            try:
                (lab.config(style="TLabel") if isinstance(lab, ttk.Label) else
                 lab.config(background=lab.master.cget("background")))
            except tk.TclError:
                pass
        self._lit = []

    # ------------------------------------------------------------------ drag and drop of files from outside
    def _enable_drop(self):
        top = self.winfo_toplevel()
        top.drop_target_register(DND_FILES)
        top.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, e):
        for path in self.tk.splitlist(e.data):
            pth = Path(path)
            if pth.suffix.lower() == ".json":
                try:
                    d = json.loads(pth.read_text())
                except (OSError, ValueError) as err:
                    self.status.set(f"could not read {pth.name}: {err}")
                    continue
                if "sources" in d and self.ifl is not None:            # an interflab patch
                    from interflab import Patch
                    self.ifl.load_patch(Patch.from_dict(d), str(pth))
                    self.use_tab.set(True)
                    self._refresh_dots()
                    self.status.set(f"loaded patch {pth.name} into the interflab tab")
                else:
                    self._load_path(pth)
            elif pth.is_file():
                self.inp.set(str(pth))
                self._input_changed()
                self.status.set(f"input: {pth.name}")
        return e.action

    def _drag_start(self, e, name):
        self._hide_cables()
        self._drag = tk.Toplevel(self)
        self._drag.wm_overrideredirect(True)
        try:
            self._drag.attributes("-topmost", True)
        except tk.TclError:
            pass
        c = tk.Canvas(self._drag, width=18, height=18, highlightthickness=0, background=C["bg"])
        c.create_oval(2, 2, 16, 16, fill=self._dot_color(name), outline="")
        c.pack()
        self._drag_name = name
        self._drag_move(e)

    def _target_at(self, x, y):
        w = self.winfo_containing(x, y)
        while w is not None:
            if w in self._row_of:
                return self._row_of[w]
            w = w.master
        return None

    def _highlight(self, lab):
        if self._drop_lab is not None and self._drop_lab is not lab:
            try:
                self._drop_lab.config(style="TLabel")
            except tk.TclError:
                pass
        self._drop_lab = lab
        if lab is not None:
            lab.config(style="Drop.TLabel")

    def _drag_move(self, e):
        if self._drag is None:
            return
        self._drag.wm_geometry(f"+{e.x_root + 10}+{e.y_root + 10}")   # beside the pointer, so it isn't the drop target
        hit = self._target_at(e.x_root, e.y_root)
        self._highlight(hit[1] if hit and hit[0] in TARGETS else None)

    def _drag_end(self, e):
        if self._drag is None:
            return
        self._drag.destroy()
        self._drag = None
        self._highlight(None)
        hit = self._target_at(e.x_root, e.y_root)
        if hit is None:
            self.status.set("Drop the dot on one of the settings in the middle.")
            return
        key = hit[0]
        if key not in TARGETS:
            self.status.set(f"{P.BY_KEY[key].label} can't change during a video.")
            return
        name = self._drag_name
        m = tk.Menu(self)
        m.add_command(label=f"{name} → {P.BY_KEY[key].label}", state="disabled")
        m.add_separator()
        m.add_command(label="Replace the value", command=lambda: self._add_link(name, key, "replace"))
        m.add_command(label="Add to the value", command=lambda: self._add_link(name, key, "add"))
        m.tk_popup(e.x_root, e.y_root)

    def _add_link(self, name, key, mode):
        self.links.append(dict(src=name, param=key, mode=mode, amount=1.0))
        how = "becomes the source's value" if mode == "replace" else "gets the source's value added"
        self.status.set(f"{P.BY_KEY[key].label} {how} (times the amount). Click the dot next to it to change that.")
        self._links_changed(redraw_settings=True)

    def _link_menu(self, e, ln):
        m = tk.Menu(self)
        m.add_command(label=f"{ln['src']} → {P.BY_KEY[ln['param']].label}", state="disabled")
        m.add_separator()
        for mode, text in (("replace", "Replace the value"), ("add", "Add to the value")):
            m.add_command(label=("✓ " if ln["mode"] == mode else "    ") + text,
                          command=lambda mode=mode: self._edit_link(ln, mode=mode))
        m.add_command(label=f"    Amount (now ×{ln['amount']:g})...", command=lambda: self._ask_amount(ln))
        m.add_separator()
        m.add_command(label="    Remove", command=lambda: self._remove_link(ln))
        m.tk_popup(e.x_root, e.y_root)

    def _ask_amount(self, ln):
        par = P.BY_KEY[ln["param"]]
        x = simpledialog.askfloat("Amount", f"Multiply {ln['src']} by this before it reaches\n"
                                            f"{par.label} ({par.unit or 'no unit'}):",
                                  initialvalue=ln["amount"], parent=self)
        if x is not None:
            self._edit_link(ln, amount=float(x))

    def _edit_link(self, ln, **kw):
        ln.update(kw)
        self._links_changed(redraw_settings=True)

    def _remove_link(self, ln):
        self.links = [x for x in self.links if x is not ln]
        self._links_changed(redraw_settings=True)

    def _links_changed(self, redraw_settings=False):
        self.values["mod_links"] = dump_links(self.links)
        self._refresh_dots()
        if redraw_settings:
            self._show_step(self.sel)

    # ------------------------------------------------------------------ presets
    def _list_presets(self):
        self.preset.config(values=sorted(p.stem for p in PRESET_DIR.glob("*.json") if not p.stem.endswith(".patch")))

    def _load_values(self, values):
        self.values = P.validate(values)
        self.links = parse_links(self.values["mod_links"])
        for k, v in self.step_vars.items():
            v.set(bool(self.values[k]))
        if self.ifl is not None and (self.values["if2_enable"] or self.links):      # show the preset's patch in the tab
            try:
                from interflab import Patch
                from .interflab_stage import find_patch
                path = find_patch(self.values["if2_patch"])
                self.ifl.load_patch(Patch.load(str(path)), str(path))
            except (OSError, ValueError, KeyError) as e:
                self.status.set(f"could not load the preset's interflab patch: {e}")
        self._show_step(self.sel)
        self._refresh_dots()

    def _load_path(self, path):
        try:
            self._load_values(P.load_preset(path))
            self.preset.set(Path(path).stem)
            self.status.set(f"loaded preset {Path(path).stem}")
        except (OSError, ValueError, KeyError) as e:
            messagebox.showerror("analogfpv", str(e))

    def load_preset(self):
        path = filedialog.askopenfilename(initialdir=PRESET_DIR, filetypes=[("preset", "*.json")])
        if path:
            self._load_path(path)

    def save_preset(self):
        path = filedialog.asksaveasfilename(initialdir=PRESET_DIR, defaultextension=".json", filetypes=[("preset", "*.json")])
        if not path:
            return
        self.focus_set()
        vals = dict(self.values, mod_links=dump_links(self.links))
        if self.ifl is not None and self.use_tab.get() and (vals["if2_enable"] or self.links):
            patch_path = Path(path).with_suffix(".patch.json")              # the tab's patch goes next to the preset
            self.ifl.patch.save(str(patch_path))
            vals["if2_patch"] = str(patch_path)
        try:
            P.save_preset(vals, path)
        except (ValueError, KeyError) as e:
            messagebox.showerror("analogfpv", str(e))
            return
        self.preset.set(Path(path).stem)
        self.status.set(f"saved preset {Path(path).name}")

    def reset(self):
        self.preset.set("")
        self._load_values(P.defaults())

    # ------------------------------------------------------------------ files
    def pick_input(self):
        path = filedialog.askopenfilename(filetypes=VIDEO_TYPES)
        if path:
            self.inp.set(path)
            self._input_changed()

    def _input_changed(self):
        path = self.inp.get().strip().strip('"')
        self.inp.set(path)
        if not path or not Path(path).is_file():
            self.info.set("File not found." if path else "Choose the video you want to convert.")
            return
        if not self.out.get() or self.out.get() == self._auto_out:
            self._auto_out = str(Path(path).with_name(Path(path).stem + "_analog.mp4"))
            self.out.set(self._auto_out)
        try:
            info = probe(path)
            self.info.set(f"{info['width']}x{info['height']},  {info['duration']:.1f} s"
                          + ("" if info["audio_codec"] else ",  no audio"))
            self.t_scale.config(to=max(info["duration"] - 0.2, 0.1))
        except Exception as e:                               # ffprobe missing etc.: preview still works from 0
            self.info.set(f"could not read the video: {e}")

    def pick_output(self):
        cur = Path(self.out.get() or self.inp.get() or "out.mp4")
        path = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("mp4", "*.mp4")],
                                            initialdir=str(cur.parent), initialfile=cur.name if self.out.get() else "")
        if path:
            self.out.set(path)

    def open_out_folder(self):
        out = Path(self.out.get() or self.inp.get() or ".").expanduser()
        if out.parent.is_dir():
            _open_folder(out.parent, out)
        else:
            self.status.set(f"folder does not exist yet: {out.parent}")

    def _params(self):
        self.focus_set()
        vals = dict(self.values, mod_links=dump_links(self.links))
        if self.ifl is not None and self.use_tab.get() and (vals["if2_enable"] or self.links):
            self._tmp_patch.write_text(json.dumps(self.ifl.patch.to_dict()))
            vals["if2_patch"] = str(self._tmp_patch)
        return P.validate(vals)

    # ------------------------------------------------------------------ work in the background
    def _run(self, fn, done):
        if self._busy and self._busy.is_alive():
            self.status.set("busy - wait or press Cancel")
            return False
        self._cancel = False
        self._job = {}

        def work():
            try:
                self._job["result"] = fn()
            except Exception as e:                             # reported in the window, never kills it
                self._job["error"] = e
        self._busy = threading.Thread(target=work, daemon=True)
        self._busy.start()
        self.after(100, lambda: self._poll(done, self._busy, self._job))
        return True

    def _poll(self, done, thread, job):
        if "progress" in job:
            d, t = job["progress"]
            self.prog["value"] = 1000 * min(d / max(t, 1), 1.0)
            self.status.set(f"rendering: {min(100 * d / max(t, 1), 100):.0f}%  ({d}/{t} fields)")
        if thread.is_alive():
            self.after(150, lambda: self._poll(done, thread, job))
            return
        self._busy = None                                      # free for the next job only once this one is reported
        self.render_btn.state(["!disabled"])
        if "error" in job:
            self.status.set(f"error: {job['error']}")
        else:
            done(job.get("result"))

    def do_preview(self):
        src = self.inp.get()
        if not Path(src).is_file():
            self.status.set("Choose an input video first.")
            return
        try:
            p = self._params()
        except (ValueError, KeyError) as e:
            self.status.set(str(e))
            return
        t, orig = float(self.t_prev.get()), self.show_orig.get()

        def fn():
            t0 = max(t - 0.1, 0.0)                             # a few fields first so the chain settles
            pipe, out = Pipeline(p, t0=t0), None
            for f in read_frames(src, p, start=t0, max_frames=8):
                out = f if orig else pipe.process_frame(f)
            return out

        def done(img):
            if img is None:
                self.status.set("no frames at that time")
                return
            self._photo = _photo(img)
            self.preview.config(image=self._photo, text="")
            self.status.set(f"preview at {t:.1f} s ready")
        if self._run(fn, done):
            self.status.set("rendering preview...")

    def do_render(self):
        src, dst = self.inp.get(), self.out.get()
        if not Path(src).is_file() or not dst:
            self.status.set("Choose an input video and where to save it first.")
            return
        if self._busy and self._busy.is_alive():
            self.status.set("busy - wait or press Cancel")
            return
        if Path(dst).exists() and not messagebox.askyesno("analogfpv", f"{Path(dst).name} already exists. Replace it?"):
            return
        try:
            p = self._params()
            start = float(self.start.get() or 0)
            dur = float(self.dur.get()) if self.dur.get().strip() else None
        except (ValueError, KeyError) as e:
            self.status.set(str(e))
            return
        self.prog["value"] = 0

        def fn():
            return process_video(src, dst, p, start=start, duration=dur,
                                 progress=lambda d, t: self._job.__setitem__("progress", (d, t)),
                                 cancel=lambda: self._cancel)

        def done(stats):
            self.prog["value"] = 1000
            what = "Cancelled" if stats and stats["cancelled"] else "Done"
            self.status.set(f"{what}: {stats['seconds']:.1f} s of video" if stats else what)
            self._saved = Path(dst).resolve()
            self.saved_lab.config(text=f"Saved to {self._saved}  (click to open the folder)")
        if self._run(fn, done):
            self.render_btn.state(["disabled"])

    def cancel(self):
        self._cancel = True


def main():
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    _style(root)
    root.title(APP_NAME)
    root.iconphoto(True, _icon())
    root.geometry("1460x900")
    root.minsize(1150, 720)
    AnalogFPVApp(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
