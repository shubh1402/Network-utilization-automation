import os
import sys
import tempfile
from pathlib import Path

# Isolate every test run: outputs go to a temp folder and demo data is used.
os.environ["OUTPUT_DIR"] = tempfile.mkdtemp(prefix="nua-tests-")
os.environ["DATA_SOURCE"] = "demo"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
