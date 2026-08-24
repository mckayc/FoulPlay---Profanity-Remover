# PyInstaller spec for FoulPlay.
#
# Deliberately does NOT bundle torch/faster-whisper/demucs/whisperx -- those
# install on demand into a per-user managed runtime (core/runtime.py,
# core/dependencies.py), which is what keeps this bundle small. The
# packaging venv used to run PyInstaller must not have those packages
# installed, or they could get swept in by accident.
#
# Build with (from the repo root):
#   .venv\Scripts\pyinstaller.exe packaging\foulplay.spec --distpath dist --workpath build --noconfirm

from pathlib import Path

block_cipher = None

repo_root = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(repo_root / "main.py")],
    pathex=[str(repo_root)],
    binaries=[],
    datas=[
        (str(repo_root / "data" / "default_wordlist.json"), "data"),
        (str(repo_root / "data" / "icon.ico"), "data"),
        (str(repo_root / "packaging" / "runtime_template"), "runtime_template"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "torchaudio", "faster_whisper", "demucs", "whisperx", "ctranslate2"],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FoulPlay",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(repo_root / "packaging" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="FoulPlay",
)
