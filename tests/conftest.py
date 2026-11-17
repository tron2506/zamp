import os
import sys
import tempfile
from pathlib import Path

# Isolated data dir + no stage delay + LLM off, before the app is imported.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="onboarding-test-")
os.environ["STAGE_DELAY_MS"] = "0"
os.environ["LLM_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
