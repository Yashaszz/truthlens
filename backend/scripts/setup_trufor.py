"""Optional: install TruFor (GRIP-UNINA, CVPR 2023) for learned forgery detection + localisation.
Downloads the official inference code (test_docker/src) and weights. Licence: non-profit / informational use only.
Usage: backend\\.venv\\Scripts\\python backend\\scripts\\setup_trufor.py"""
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

CODE = Path(__file__).resolve().parents[1] / "third_party" / "trufor"
WDIR = Path(os.getenv("LOCALAPPDATA", Path.home() / ".cache")) / "truthlens" / "models" / "trufor"
URL = "https://www.grip.unina.it/download/prog/TruFor/TruFor_weights.zip"

if not CODE.exists():
    tmp = Path(tempfile.mkdtemp())
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                    "https://github.com/grip-unina/TruFor.git", str(tmp / "TruFor")], check=True)
    subprocess.run(["git", "-C", str(tmp / "TruFor"), "sparse-checkout", "set", "test_docker/src"], check=True)
    shutil.copytree(tmp / "TruFor" / "test_docker" / "src", CODE)
    shutil.copy(tmp / "TruFor" / "test_docker" / "LICENSE.txt", CODE / "LICENSE.txt")
    shutil.rmtree(tmp, ignore_errors=True)
    print("code ->", CODE)
if not (WDIR / "weights" / "trufor.pth.tar").exists():
    WDIR.mkdir(parents=True, exist_ok=True)
    z = WDIR / "TruFor_weights.zip"
    print("downloading weights (~260 MB)…")
    urllib.request.urlretrieve(URL, z)
    with zipfile.ZipFile(z) as f:
        f.extractall(WDIR)
    z.unlink()
print("weights ->", WDIR / "weights" / "trufor.pth.tar")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yacs", "timm", "tqdm"], check=True)
print("TruFor ready. Restart the API to use it.")
