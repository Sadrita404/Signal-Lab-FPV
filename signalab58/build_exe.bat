@echo off
rem Builds dist\Signallab58\Signallab58.exe. Run from the folder that holds analogfpv, interflab, presets, patches.
cd /d "%~dp0"
py -3.13 -m pip install --upgrade pyinstaller tkinterdnd2 || goto :fail
py -3.13 -m PyInstaller --noconfirm --clean --windowed --name Signallab58 --icon sl58.ico ^
  --add-data "presets;presets" --add-data "patches;patches" ^
  --collect-all tkinterdnd2 --hidden-import scipy.signal --hidden-import scipy.ndimage ^
  signallab58_app.py || goto :fail
rem ffmpeg and ffprobe go next to the exe, so it runs on PCs without ffmpeg installed
powershell -NoProfile -Command "foreach($n in 'ffmpeg','ffprobe'){ $c = Get-Command $n -ErrorAction SilentlyContinue; if($c){ Copy-Item (Get-Item $c.Source).FullName 'dist\Signallab58\' -Force; Write-Host \"copied $n\" } else { Write-Host \"$n not found: copy $n.exe into dist\Signallab58 yourself\" } }"
echo.
echo Done: dist\Signallab58\Signallab58.exe  (share the whole dist\Signallab58 folder, zipped)
pause
exit /b 0
:fail
echo Build failed - see the messages above.
pause
exit /b 1
