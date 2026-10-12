"""Build the Streamlit-only China macro artifact from a validated local run."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from china_macro.artifact import build_artifacts  # noqa: E402

if __name__ == "__main__":
    result = build_artifacts()
    print(f"China macro: {result['snapshot']['status']} / {result['run_id']}")
