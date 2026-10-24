"""Entry point for the Signallab58 .exe (see build_exe.bat). Opens the window."""
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):          # ffmpeg.exe / ffprobe.exe placed next to Signallab58.exe are used first
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")

from analogfpv.gui import main

main()
