import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from interflab.examples import EXAMPLES
from interflab.plot import render_png
from interflab import Engine
for k, f in EXAMPLES.items():
    p = f(); assert Engine(p).render(5000).shape == (5000,), k
img = render_png(EXAMPLES["slow_push"](), os.path.join(tempfile.gettempdir(), "t.png"), fields=3)
assert img.shape == (720, 1000, 3)
print("interflab step2 selftest OK")
