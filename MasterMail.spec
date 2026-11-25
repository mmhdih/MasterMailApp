# PyInstaller build: one portable MasterMail.exe
# pyinstaller --noconfirm --clean MasterMail.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)

hidden = (
    collect_submodules("webview")
    + collect_submodules("keyring.backends")
    + ["xlrd", "docx", "anthropic"]
)

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "web"), "web"), (str(ROOT / "assets"), "assets")],
    hiddenimports=hidden,
    excludes=["tkinter", "pandas", "numpy", "matplotlib", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MasterMail",
    console=False,
    icon=str(ROOT / "assets" / "icon.ico"),
    version=str(ROOT / "version_info.txt") if (ROOT / "version_info.txt").exists() else None,
    upx=False,
)
