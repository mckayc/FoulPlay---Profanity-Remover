"""Build-time script: prepares the runtime template bundled inside the
installer -- a Windows embeddable Python + pip, with `import site`
re-enabled so pip-installed packages become importable. No heavy ML
packages are included here; those install on demand into each user's own
copy of this template (see core/runtime.py, core/dependencies.py).

Run once (or whenever the pinned Python version changes) before building
the PyInstaller bundle:
    python packaging/build_runtime_template.py
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

PYTHON_VERSION = "3.12.10"  # keep in sync with the dev venv's Python version
EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

PACKAGING_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = PACKAGING_DIR / "runtime_template"
ML_WORKER_SRC = PACKAGING_DIR.parent / "core" / "ml_worker.py"


def _download(url: str, dest: Path) -> None:
    print(f"Downloading {url} ...")
    urllib.request.urlretrieve(url, dest)


def build() -> None:
    if TEMPLATE_DIR.exists():
        print(f"Removing existing template at {TEMPLATE_DIR}")
        shutil.rmtree(TEMPLATE_DIR)
    TEMPLATE_DIR.mkdir(parents=True)

    zip_path = TEMPLATE_DIR / "_embed.zip"
    _download(EMBED_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(TEMPLATE_DIR)
    zip_path.unlink()

    pth_files = list(TEMPLATE_DIR.glob("python*._pth"))
    if not pth_files:
        raise RuntimeError(f"No ._pth file found in {TEMPLATE_DIR}")
    pth_file = pth_files[0]
    contents = pth_file.read_text(encoding="utf-8")
    contents = contents.replace("#import site", "import site")
    pth_file.write_text(contents, encoding="utf-8")

    get_pip_path = TEMPLATE_DIR / "get-pip.py"
    _download(GET_PIP_URL, get_pip_path)

    python_exe = TEMPLATE_DIR / "python.exe"
    print("Bootstrapping pip...")
    subprocess.run([str(python_exe), str(get_pip_path), "--no-warn-script-location"], check=True)
    get_pip_path.unlink()

    print(f"Copying {ML_WORKER_SRC.name} into template...")
    shutil.copy2(ML_WORKER_SRC, TEMPLATE_DIR / "ml_worker.py")

    print(f"Runtime template ready at {TEMPLATE_DIR}")


if __name__ == "__main__":
    build()
