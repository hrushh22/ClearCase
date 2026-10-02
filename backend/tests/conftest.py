import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SIGNING_KEY_PATH"] = f"{_tmp}/test_key.pem"
for k in ("GEMINI_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY"):
    os.environ[k] = ""
