# PyInstaller recipe for the Windows program:  pyinstaller packaging/windows/sl2.spec --noconfirm
# -> dist/SL2/SL2.exe       the program: its own window (Edge WebView2, part of Windows 10 / 11), no console
#    dist/SL2/sl2-cli.exe   the same program for the command line:  sl2-cli make "dark techno, long"
# Python, numpy, scipy and pywebview are inside; nothing else to install.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))

a = Analysis(
    [os.path.join(SPECPATH, 'launch.py')],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, 'sl2', 'genres'), os.path.join('sl2', 'genres')),
           (os.path.join(ROOT, 'sl2', 'ui'), os.path.join('sl2', 'ui'))] + collect_data_files('webview'),
    hiddenimports=['sl2.render', 'sl2.synth', 'sl2.server', 'sl2.store', 'sl2.edit', 'sl2.cli', 'sl2.fx', 'sl2.va', 'sl2.va_bass',
                   'sl2.fastdsp', 'sl2._dsp', 'sl2.desktop', 'sl2.mixcheck',
                   'scipy.signal', 'scipy.ndimage', 'scipy.fft', 'clr'] + collect_submodules('webview'),
    excludes=['tkinter', 'matplotlib', 'pytest', 'IPython', 'PIL', 'pandas'],
    noarchive=False,
)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SL2', console=False,
          icon=os.path.join(SPECPATH, 'sl2.ico'), version=None)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name='sl2-cli', console=True,
          icon=os.path.join(SPECPATH, 'sl2.ico'), version=None)
coll = COLLECT(gui, cli, a.binaries, a.datas, name='SL2')
