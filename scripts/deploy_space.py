"""Deploy the ClearCase backend (+ app) to a Hugging Face Space and set its secrets from the local .env.

Usage:
  HF_TOKEN=hf_xxx APP_PASSWORD=choose-one python scripts/deploy_space.py [space-name]

Creates <your-hf-user>/<space-name> (Docker SDK, default name "clearcase"), uploads the code (never .env, keys,
the database or case documents), sets the secrets, and creates a PRIVATE dataset <user>/<space-name>-state used to
keep the database across restarts. Prints the Space URL to use as CLEARCASE_API_BASE for GitHub Pages.
"""
import os
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
SECRET_KEYS = ["CLIO_CLIENT_ID", "CLIO_CLIENT_SECRET", "CLIO_ACCESS_TOKEN", "CLIO_REFRESH_TOKEN", "CLIO_REGION_BASE_URL",
               "CLIO_MATTER_QUERY", "GROQ_API_KEY", "MISTRAL_API_KEY", "GEMINI_API_KEY", "FIRM_NAME", "RESEND_API_KEY", "NOTIFY_EMAIL_FROM"]

SPACE_README = """---
title: ClearCase
emoji: ⚖️
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

ClearCase backend: reads one Clio matter (read-only), builds a cited case digest, Case X-Ray and signed provider links.
"""


def main() -> None:
    token = os.environ.get("HF_TOKEN") or sys.exit("Set HF_TOKEN (a Hugging Face token with write access).")
    password = os.environ.get("APP_PASSWORD") or sys.exit("Set APP_PASSWORD (the attorney password for the hosted app).")
    name = sys.argv[1] if len(sys.argv) > 1 else "clearcase"
    api = HfApi(token=token)
    user = api.whoami()["name"]
    space, dataset = f"{user}/{name}", f"{user}/{name}-state"

    api.create_repo(space, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    api.create_repo(dataset, repo_type="dataset", private=True, exist_ok=True)

    env = dotenv_values(ROOT / ".env")
    secrets = {k: env.get(k) for k in SECRET_KEYS if env.get(k)}
    key_file = ROOT / "secrets" / "firm_ed25519.pem"
    if key_file.exists():  # same firm key as local, so already-issued signatures keep verifying
        secrets["FIRM_SIGNING_KEY_PEM"] = key_file.read_text().replace("\n", "\\n")
    secrets.update({"APP_PASSWORD": password, "HF_TOKEN": token, "PERSIST_DATASET": dataset})
    for k, v in secrets.items():
        api.add_space_secret(space, k, v)
    print(f"Set {len(secrets)} secrets: {', '.join(sorted(secrets))}")

    api.upload_folder(repo_id=space, repo_type="space", folder_path=str(ROOT), commit_message="Deploy ClearCase",
                      allow_patterns=["Dockerfile", ".dockerignore", "backend/**", "scripts/**", "frontend/**"],
                      ignore_patterns=["**/node_modules/**", "frontend/dist/**", "backend/data/**", "**/__pycache__/**",
                                       "*.db", "*.db-*", ".env", "secrets/**", "**/*.pdf"])
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "README.md").write_text(SPACE_README, encoding="utf-8")
        api.upload_file(path_or_fileobj=str(Path(d) / "README.md"), path_in_repo="README.md", repo_id=space, repo_type="space")

    url = f"https://{space.replace('/', '-').replace('_', '-').lower()}.hf.space"
    print(f"Space: https://huggingface.co/spaces/{space}")
    print(f"Backend URL (set as GitHub variable CLEARCASE_API_BASE): {url}")
    print(f"State dataset (private): https://huggingface.co/datasets/{dataset}")


if __name__ == "__main__":
    main()
