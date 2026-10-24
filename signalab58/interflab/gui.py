"""interflab patch editor (tkinter).

InterflabPanel is a plain ttk.Frame holding one Patch, so a later analogfpv GUI can embed it as a tab
and listen to `on_change(patch)`. The source sliders are built from SOURCE_SCHEMA.
"""
import base64
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2

from .examples import EXAMPLES
from .patch import CABLE_MODES, MAX_SOURCES, MOD_TARGETS, SOURCE_SCHEMA, Patch
from .plot import render_image
from .wave import WAVES

PATCH_DIR = Path(__file__).resolve().parent.parent / "patches"
SCOPE_W = 760


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


class InterflabPanel(ttk.Frame):
    def __init__(self, master, patch: Patch | None = None, on_change=None):
        super().__init__(master, padding=6)
        self.patch = patch or EXAMPLES["tone_burst"]()
        self.path: str | None = None
        self.on_change = on_change
        self.sel = 0
        self._loading = False
        self._scope_job = None
        self._worker = None
        self._result = None
        self._again = False
        self._photo = None
        self._build()
        self._reload()

    # ------------------------------------------------------------------ layout
    def _build(self):
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        for text, cmd in (("New", self.new), ("Open...", self.open), ("Save", self.save), ("Save as...", self.save_as)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2)
        ttk.Label(bar, text="   Example:").pack(side="left")
        self.example = ttk.Combobox(bar, values=list(EXAMPLES), state="readonly", width=16)
        self.example.pack(side="left", padx=2)
        self.example.bind("<<ComboboxSelected>>", lambda e: self.load_patch(EXAMPLES[self.example.get()](), None))
        ttk.Label(bar, text="   Scope fields:").pack(side="left")
        self.fields = tk.IntVar(value=20)
        ttk.Spinbox(bar, from_=2, to=120, textvariable=self.fields, width=5,
                    command=self.changed).pack(side="left", padx=2)
        self.file_label = ttk.Label(bar, text="")
        self.file_label.pack(side="right")

        # sources
        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        lf = ttk.LabelFrame(left, text="Sources", padding=4)
        lf.pack(fill="both", expand=True)
        self.src_list = tk.Listbox(lf, height=MAX_SOURCES, width=34, exportselection=False)
        self.src_list.pack(fill="both", expand=True)
        self.src_list.bind("<<ListboxSelect>>", self._on_list_select)
        row = ttk.Frame(lf)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="Add", command=self.add_source).pack(side="left")
        ttk.Button(row, text="Copy", command=self.copy_source).pack(side="left", padx=2)
        ttk.Button(row, text="Remove", command=self.remove_source).pack(side="left")

        # cables
        cf = ttk.LabelFrame(left, text="Cables (source output -> another source's setting)", padding=4)
        cf.pack(fill="both", expand=True, pady=(6, 0))
        self.cab_tree = ttk.Treeview(cf, columns=("from", "to", "param", "mode", "depth"), show="headings", height=6)
        for c, w in (("from", 90), ("to", 90), ("param", 70), ("mode", 50), ("depth", 70)):
            self.cab_tree.heading(c, text=c)
            self.cab_tree.column(c, width=w, anchor="w")
        self.cab_tree.pack(fill="both", expand=True)
        self.cab_tree.bind("<<TreeviewSelect>>", self._on_cable_select)
        ed = ttk.Frame(cf)
        ed.pack(fill="x", pady=(4, 0))
        self.c_src = ttk.Combobox(ed, state="readonly", width=12)
        self.c_dst = ttk.Combobox(ed, state="readonly", width=12)
        self.c_param = ttk.Combobox(ed, values=MOD_TARGETS, state="readonly", width=8)
        self.c_mode = ttk.Combobox(ed, values=CABLE_MODES, state="readonly", width=6)
        self.c_depth = ttk.Entry(ed, width=10)
        for i, (lab, w) in enumerate((("from", self.c_src), ("to", self.c_dst), ("param", self.c_param),
                                      ("mode", self.c_mode), ("depth", self.c_depth))):
            ttk.Label(ed, text=lab).grid(row=0, column=i, sticky="w")
            w.grid(row=1, column=i, padx=1)
        self.c_param.set(MOD_TARGETS[0])
        self.c_mode.set(CABLE_MODES[0])
        self.c_depth.insert(0, "1.0")
        row = ttk.Frame(cf)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="Add cable", command=self.add_cable).pack(side="left")
        ttk.Button(row, text="Update", command=self.update_cable).pack(side="left", padx=2)
        ttk.Button(row, text="Remove", command=self.remove_cable).pack(side="left")

        # source editor
        sf = ttk.LabelFrame(self, text="Selected source", padding=4)
        sf.grid(row=1, column=1, sticky="nsew", padx=(0, 6))
        self.v_name = tk.StringVar()
        self.v_wave = tk.StringVar()
        self.v_enabled = tk.BooleanVar()
        self.v_mix = tk.StringVar()
        self.v_fade = tk.StringVar()
        self.v_salt = tk.StringVar()
        r = 0
        ttk.Label(sf, text="Name").grid(row=r, column=0, sticky="w")
        ttk.Entry(sf, textvariable=self.v_name, width=18).grid(row=r, column=1, sticky="ew")
        self.v_name.trace_add("write", lambda *a: self._set("name", self.v_name.get(), relist=True))
        r += 1
        ttk.Label(sf, text="Wave").grid(row=r, column=0, sticky="w")
        cb = ttk.Combobox(sf, textvariable=self.v_wave, values=WAVES, state="readonly", width=10)
        cb.grid(row=r, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._set("wave", self.v_wave.get(), relist=True))
        r += 1
        ttk.Checkbutton(sf, text="On", variable=self.v_enabled,
                        command=lambda: self._set("enabled", self.v_enabled.get(), relist=True)).grid(row=r, column=0, sticky="w")
        of = ttk.Frame(sf)
        of.grid(row=r, column=1, columnspan=3, sticky="w")
        ttk.Label(of, text="   Output:").pack(side="left")
        for text, tip in (("Interfere", "Added to the video signal as interference."),
                          ("Parameter", "Not added to the signal. Drives other sources through cables, and shows up as a "
                                        "dot in the converter that you can drag onto any setting to change it over time.")):
            rb = ttk.Radiobutton(of, text=text, value=text, variable=self.v_mix,
                                 command=lambda: self._set("to_mix", self.v_mix.get() == "Interfere", relist=True))
            rb.pack(side="left", padx=(8, 0))
            Tooltip(rb, tip)
        r += 1
        self.rows = {}
        for key, _d, lo, hi, step, unit, mod, help_ in SOURCE_SCHEMA:
            lab = ttk.Label(sf, text=key)
            lab.grid(row=r, column=0, sticky="w")
            var = tk.DoubleVar()
            sc = tk.Scale(sf, from_=lo, to=hi, resolution=step, orient="horizontal", showvalue=0,
                          length=260, variable=var, command=lambda v, k=key: self._on_scale(k, v))
            sc.grid(row=r, column=1, sticky="ew")
            ent = ttk.Entry(sf, width=13)
            ent.grid(row=r, column=2, padx=2)
            ent.bind("<Return>", lambda e, k=key: self._on_entry(k))
            ent.bind("<FocusOut>", lambda e, k=key: self._on_entry(k))
            ttk.Label(sf, text=unit).grid(row=r, column=3, sticky="w")
            for w in (lab, sc, ent):
                w.bind("<Enter>", lambda e, h=help_: self.status.set(h), add="+")
                Tooltip(w, f"{key}\n{help_}\nRange {lo:g} to {hi:g} {unit}".rstrip() + ("\nCan be driven by a cable." if mod else ""))
            self.rows[key] = (lab, var, ent, step, lo, hi)
            r += 1
        ttk.Label(sf, text="fade").grid(row=r, column=0, sticky="w")
        fe = ttk.Entry(sf, textvariable=self.v_fade)
        fe.grid(row=r, column=1, columnspan=2, sticky="ew")
        fe.bind("<Return>", lambda e: self._set("fade", self.v_fade.get()))
        fe.bind("<FocusOut>", lambda e: self._set("fade", self.v_fade.get()))
        fe.bind("<Enter>", lambda e: self.status.set("Level over time as seconds:level points, e.g. 0:0, 2:1 (empty = always 1)."))
        Tooltip(fe, "fade\nLevel over time as seconds:level points, e.g. 0:0, 2:1 (empty = always 1).")
        r += 1
        ttk.Label(sf, text="seed_salt").grid(row=r, column=0, sticky="w")
        se = ttk.Spinbox(sf, from_=0, to=9999, textvariable=self.v_salt, width=8,
                         command=lambda: self._set_int("seed_salt", self.v_salt.get()))
        se.grid(row=r, column=1, sticky="w")
        se.bind("<Return>", lambda e: self._set_int("seed_salt", self.v_salt.get()))
        se.bind("<Enter>", lambda e: self.status.set("Changes the random pattern of random and gate waves."))
        Tooltip(se, "seed_salt\nChanges the random pattern of random and gate waves.")
        sf.columnconfigure(1, weight=1)

        # scope
        pf = ttk.LabelFrame(self, text="Scope", padding=4)
        pf.grid(row=1, column=2, sticky="nsew")
        self.scope = ttk.Label(pf, text="rendering...", anchor="center")
        self.scope.pack(fill="both", expand=True)

        self.status = tk.StringVar(value="Hover over a setting for help.")
        ttk.Label(self, textvariable=self.status, anchor="w").grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.columnconfigure(2, weight=1)
        self.rowconfigure(1, weight=1)

    # ------------------------------------------------------------------ patch <-> widgets
    def load_patch(self, patch: Patch, path: str | None):
        self.patch, self.path, self.sel = patch, path, 0
        self._reload()

    def _reload(self):
        self.file_label.config(text=Path(self.path).name if self.path else "(unsaved)")
        self._refresh_sources()
        self._refresh_cables()
        self._show_source()
        self.changed()

    def _src_label(self, i, s):
        tags = ("" if s["enabled"] else " [off]") + (" [interfere]" if s["to_mix"] else " [parameter]")
        return f"{i + 1}. {s['name']} ({s['wave']}){tags}"

    def _refresh_sources(self):
        self.src_list.delete(0, "end")
        for i, s in enumerate(self.patch.sources):
            self.src_list.insert("end", self._src_label(i, s))
        self.src_list.selection_clear(0, "end")
        self.src_list.selection_set(self.sel)
        names = [f"{i + 1}. {s['name']}" for i, s in enumerate(self.patch.sources)]
        self.c_src.config(values=names)
        self.c_dst.config(values=names)

    def _refresh_cables(self):
        self.cab_tree.delete(*self.cab_tree.get_children())
        S = self.patch.sources
        for j, c in enumerate(self.patch.cables):
            self.cab_tree.insert("", "end", iid=str(j), values=(
                f"{c['src'] + 1}. {S[c['src']]['name']}", f"{c['dst'] + 1}. {S[c['dst']]['name']}",
                c["param"], c.get("mode", "add"), f"{c['depth']:g}"))
        self._mark_patched()

    def _mark_patched(self):
        hit = {c["param"] for c in self.patch.cables if c["dst"] == self.sel}
        for key, (lab, *_rest) in self.rows.items():
            lab.config(text=f"{key} *" if key in hit else key)

    def _show_source(self):
        s = self.patch.sources[self.sel]
        self._loading = True
        self.v_name.set(s["name"])
        self.v_wave.set(s["wave"])
        self.v_enabled.set(bool(s["enabled"]))
        self.v_mix.set("Interfere" if s["to_mix"] else "Parameter")
        self.v_fade.set(s.get("fade", ""))
        self.v_salt.set(str(s.get("seed_salt", 0)))
        for key, (_lab, var, ent, *_r) in self.rows.items():
            var.set(s[key])
            ent.delete(0, "end")
            ent.insert(0, f"{s[key]:.10g}")
        self._loading = False
        self._mark_patched()

    def _set(self, key, value, relist=False):
        if self._loading:
            return
        s = self.patch.sources[self.sel]
        if s.get(key) == value:
            return
        s[key] = value
        if relist:
            self.src_list.delete(self.sel)
            self.src_list.insert(self.sel, self._src_label(self.sel, s))
            self.src_list.selection_set(self.sel)
            if key == "name":
                self._refresh_cables()
                names = [f"{i + 1}. {x['name']}" for i, x in enumerate(self.patch.sources)]
                self.c_src.config(values=names)
                self.c_dst.config(values=names)
        self.changed()

    def _set_int(self, key, text):
        try:
            self._set(key, int(text))
        except ValueError:
            self.status.set(f"{key}: not a whole number")

    def _on_scale(self, key, v):
        if self._loading:
            return
        _lab, _var, ent, step, *_r = self.rows[key]
        v = float(v)
        if abs(v - self.patch.sources[self.sel][key]) <= step / 2:    # echo of a typed value: keep it exact
            return
        ent.delete(0, "end")
        ent.insert(0, f"{v:.10g}")
        self._set(key, v)

    def _on_entry(self, key):
        _lab, var, ent, _step, lo, hi = self.rows[key]
        try:
            v = min(max(float(ent.get()), lo), hi)
        except ValueError:
            self.status.set(f"{key}: not a number")
            return
        self._set(key, v)
        self._loading = True
        var.set(v)
        self._loading = False

    def _on_list_select(self, _e=None):
        cur = self.src_list.curselection()
        if cur:
            self.focus_set()                       # commit a half-typed entry to the old source first
            self.sel = cur[0]
            self._show_source()

    # ------------------------------------------------------------------ sources
    def add_source(self, **kw):
        if len(self.patch.sources) >= MAX_SOURCES:
            messagebox.showinfo("interflab", f"A patch can have at most {MAX_SOURCES} sources.")
            return
        self.sel = self.patch.add_source(**kw)
        self._refresh_sources()
        self._refresh_cables()
        self._show_source()
        self.changed()

    def copy_source(self):
        s = dict(self.patch.sources[self.sel])
        s["name"] = s["name"] + " copy"
        self.add_source(**s)

    def remove_source(self):
        if len(self.patch.sources) <= 1:
            return
        i = self.sel
        del self.patch.sources[i]
        cables = []
        for c in self.patch.cables:
            if i in (c["src"], c["dst"]):
                continue
            c["src"] -= c["src"] > i
            c["dst"] -= c["dst"] > i
            cables.append(c)
        self.patch.cables = cables
        self.sel = min(i, len(self.patch.sources) - 1)
        self._refresh_sources()
        self._refresh_cables()
        self._show_source()
        self.changed()

    # ------------------------------------------------------------------ cables
    def _cable_from_editor(self):
        try:
            return dict(src=int(self.c_src.get().split(".")[0]) - 1, dst=int(self.c_dst.get().split(".")[0]) - 1,
                        param=self.c_param.get(), depth=float(self.c_depth.get()), mode=self.c_mode.get())
        except ValueError:
            messagebox.showerror("interflab", "Pick a 'from' and 'to' source and type a number for depth.")
            return None

    def _try_cables(self, cables):
        old = self.patch.cables
        self.patch.cables = cables
        try:
            self.patch.validate()
        except ValueError as e:
            self.patch.cables = old
            messagebox.showerror("interflab", str(e))
            return
        self._refresh_cables()
        self.changed()

    def _selected_cable(self):
        cur = self.cab_tree.selection()
        return int(cur[0]) if cur else None

    def add_cable(self):
        c = self._cable_from_editor()
        if c:
            self._try_cables(self.patch.cables + [c])

    def update_cable(self):
        j, c = self._selected_cable(), self._cable_from_editor()
        if j is not None and c:
            cables = list(self.patch.cables)
            cables[j] = c
            self._try_cables(cables)

    def remove_cable(self):
        j = self._selected_cable()
        if j is not None:
            self._try_cables([c for k, c in enumerate(self.patch.cables) if k != j])

    def _on_cable_select(self, _e=None):
        j = self._selected_cable()
        if j is None:
            return
        c, S = self.patch.cables[j], self.patch.sources
        self.c_src.set(f"{c['src'] + 1}. {S[c['src']]['name']}")
        self.c_dst.set(f"{c['dst'] + 1}. {S[c['dst']]['name']}")
        self.c_param.set(c["param"])
        self.c_mode.set(c.get("mode", "add"))
        self.c_depth.delete(0, "end")
        self.c_depth.insert(0, f"{c['depth']:g}")

    # ------------------------------------------------------------------ files
    def new(self):
        p = Patch()
        p.add_source(name="tone")
        self.load_patch(p, None)

    def open(self):
        path = filedialog.askopenfilename(initialdir=PATCH_DIR, filetypes=[("interflab patch", "*.json"), ("all", "*.*")])
        if path:
            try:
                self.load_patch(Patch.load(path), path)
            except (OSError, ValueError, KeyError) as e:
                messagebox.showerror("interflab", f"Could not open {path}:\n{e}")

    def save(self):
        if not self.path:
            return self.save_as()
        self.patch.save(self.path)
        self.status.set(f"saved {self.path}")

    def save_as(self):
        path = filedialog.asksaveasfilename(initialdir=PATCH_DIR, defaultextension=".json",
                                            filetypes=[("interflab patch", "*.json")])
        if path:
            self.path = path
            self.file_label.config(text=Path(path).name)
            self.save()

    # ------------------------------------------------------------------ scope
    def changed(self):
        if self.on_change:
            self.on_change(self.patch)
        if self._scope_job:
            self.after_cancel(self._scope_job)
        self._scope_job = self.after(350, self._start_scope)

    def _start_scope(self):
        self._scope_job = None
        if self._worker and self._worker.is_alive():
            self._again = True
            return
        try:
            snap = Patch.from_dict(self.patch.to_dict())
            fields = max(2, int(self.fields.get()))
        except (ValueError, tk.TclError) as e:
            self.status.set(f"patch problem: {e}")
            return
        self._result = None
        self._worker = threading.Thread(target=self._render, args=(snap, fields), daemon=True)
        self._worker.start()
        self.after(100, self._poll)

    def _render(self, patch, fields):
        try:
            img = render_image(patch, fields)
            h = int(img.shape[0] * SCOPE_W / img.shape[1])
            img = cv2.resize(img, (SCOPE_W, h), interpolation=cv2.INTER_AREA)
            self._result = ("ok", base64.b64encode(cv2.imencode(".png", img)[1].tobytes()).decode())
        except Exception as e:                      # shown in the status line, never kills the window
            self._result = ("err", str(e))

    def _poll(self):
        if self._worker.is_alive():
            self.after(100, self._poll)
            return
        kind, data = self._result
        if kind == "ok":
            self._photo = tk.PhotoImage(data=data)
            self.scope.config(image=self._photo, text="")
        else:
            self.status.set(f"scope: {data}")
        if self._again:
            self._again = False
            self._start_scope()


def main(path: str | None = None):
    root = tk.Tk()
    root.title("interflab")
    panel = InterflabPanel(root)
    panel.pack(fill="both", expand=True)
    if path:
        panel.load_patch(Patch.load(path), path)
    root.mainloop()


if __name__ == "__main__":
    main()
