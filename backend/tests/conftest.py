import os
import sys
import tempfile
from pathlib import Path

os.environ["BIT_DATA_DIR"] = tempfile.mkdtemp()
os.environ["BIT_API_TOKEN"] = "test-token"
os.environ["ANTHROPIC_API_KEY"] = "sk-test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
