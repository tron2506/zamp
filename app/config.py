import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
SAMPLES_DIR = DATA_DIR / "samples"
DB_PATH = DATA_DIR / "onboarding.db"

LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "").strip()
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "45"))
LLM_ENABLED = bool(LLM_API_KEY and LLM_BASE_URL and LLM_MODEL)

# Small pause between stages so the live view is watchable in a demo. Set to 0 for batch use.
STAGE_DELAY_MS = int(os.getenv("STAGE_DELAY_MS", "450"))

# The app is open (no login). Cap runs per visitor per hour to bound LLM spend. 0 = unlimited.
RUNS_PER_HOUR_PER_IP = int(os.getenv("RUNS_PER_HOUR_PER_IP", "60"))

for d in (DATA_DIR, UPLOAD_DIR, SAMPLES_DIR):
    d.mkdir(parents=True, exist_ok=True)
