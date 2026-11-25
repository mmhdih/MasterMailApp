"""Write version_info.txt (Windows file properties for the exe) from mastermail.__version__."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mastermail import APP_NAME, POWERED_BY, __version__  # noqa: E402

parts = (__version__.split(".") + ["0", "0", "0", "0"])[:4]
nums = ", ".join(str(int(p)) for p in parts)
TEMPLATE = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'HajMehdi'),
      StringStruct('FileDescription', '{APP_NAME} — crawl, split and mass-mail sellers'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', '{APP_NAME}'),
      StringStruct('LegalCopyright', 'MIT License — {POWERED_BY}'),
      StringStruct('OriginalFilename', '{APP_NAME}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
(ROOT / "version_info.txt").write_text(TEMPLATE, encoding="utf-8")
print("version_info.txt", __version__)
