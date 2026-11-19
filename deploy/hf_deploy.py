"""Deploy TruthLens to a Hugging Face Space (Docker, CPU) and point the permanent link's backup at it.
Reads HF_TOKEN from backend/.env.   Usage: backend\\.venv\\Scripts\\python deploy\\hf_deploy.py"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402  (loads backend/.env)
from huggingface_hub import HfApi  # noqa: E402

token = os.getenv("HF_TOKEN")
if not token:
    sys.exit("HF_TOKEN missing: add HF_TOKEN=hf_... to backend/.env")
api = HfApi(token=token)
user = api.whoami()["name"]
repo = f"{user}/truthlens"
api.create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True, private=False)

# Stage only what the Space needs (no keys, no venv, no case data, no benchmark data)
stage = Path(tempfile.mkdtemp(prefix="tl-space-"))
shutil.copy(ROOT / "deploy/hf-space/Dockerfile", stage / "Dockerfile")
shutil.copy(ROOT / "deploy/hf-space/README.md", stage / "README.md")
ign = shutil.ignore_patterns("__pycache__", "*.pyc", ".env", "data", ".venv")
shutil.copytree(ROOT / "backend/app", stage / "backend/app", ignore=ign)
shutil.copy(ROOT / "backend/requirements.txt", stage / "backend/requirements.txt")
subprocess.run(["npx", "vite", "build"], cwd=ROOT / "frontend", check=True, shell=True,
               env={**os.environ, "VITE_API_BASE": ""})
shutil.copytree(ROOT / "frontend/dist", stage / "frontend/dist")
(stage / "samples").mkdir()
for n in ("photo_tampered.jpg", "tts_spliced.wav", "dubbed_clip.mp4", "caption.txt", "tts_speech.wav"):
    if (ROOT / "samples" / n).exists():
        shutil.copy(ROOT / "samples" / n, stage / "samples" / n)

api.upload_folder(folder_path=str(stage), repo_id=repo, repo_type="space", commit_message="Deploy TruthLens")
shutil.rmtree(stage, ignore_errors=True)
sub = re.sub(r"[^a-z0-9-]", "-", user.lower())
url = f"https://{sub}-truthlens.hf.space"
print("SPACE:", f"https://huggingface.co/spaces/{repo}")
print("APP:", url)
