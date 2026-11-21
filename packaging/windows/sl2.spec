# PyInstaller recipe for the Windows app:  pyinstaller packaging/windows/sl2.spec --noconfirm
# -> dist/SL2/SL2.exe (+ its _internal folder). Python, numpy and scipy are inside; nothing else to install.
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))

a = Analysis(
    [os.path.join(SPECPATH, 'launch.py')],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, 'sl2', 'genres'), os.path.join('sl2', 'genres')),
           (os.path.join(ROOT, 'sl2', 'ui'), os.path.join('sl2', 'ui'))],
    hiddenimports=['sl2.render', 'sl2.synth', 'sl2.server', 'sl2.store', 'sl2.edit', 'sl2.cli',
                   'scipy.signal', 'scipy.ndimage', 'scipy.fft'],
    excludes=['tkinter', 'matplotlib', 'pytest', 'IPython', 'PIL', 'pandas'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SL2', console=True,
          icon=os.path.join(SPECPATH, 'sl2.ico'), version=None)
coll = COLLECT(exe, a.binaries, a.datas, name='SL2')
