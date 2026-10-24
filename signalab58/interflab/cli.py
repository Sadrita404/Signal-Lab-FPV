import argparse
import numpy as np

from .engine import Engine
from .examples import EXAMPLES
from .patch import Patch


def main(argv=None):
    ap = argparse.ArgumentParser(prog="interflab", description="Patchable interference generator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list the example patches")
    e = sub.add_parser("example", help="write an example patch as JSON")
    e.add_argument("name"); e.add_argument("out")
    pl = sub.add_parser("plot", help="picture of a patch (raster, line levels, spectrum, trace)")
    pl.add_argument("patch"); pl.add_argument("out"); pl.add_argument("--fields", type=int, default=40)
    g = sub.add_parser("gui", help="open the patch editor window")
    g.add_argument("patch", nargs="?")
    r = sub.add_parser("render", help="render samples to a .npy file")
    r.add_argument("patch"); r.add_argument("out"); r.add_argument("--seconds", type=float, default=0.05)
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for k, f in EXAMPLES.items():
            print(f"{k}: {f.__doc__.strip().splitlines()[0]}")
    elif a.cmd == "example":
        EXAMPLES[a.name]().save(a.out); print("wrote", a.out)
    elif a.cmd == "plot":
        from .plot import render_png
        render_png(Patch.load(a.patch), a.out, a.fields); print("wrote", a.out)
    elif a.cmd == "gui":
        from .gui import main as gui_main
        gui_main(a.patch)
    elif a.cmd == "render":
        p = Patch.load(a.patch)
        np.save(a.out, Engine(p).render(int(a.seconds * p.fs))); print("wrote", a.out)


if __name__ == "__main__":
    main()
