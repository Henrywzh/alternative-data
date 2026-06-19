from __future__ import annotations

import subprocess
from pathlib import Path


def extract_pdf_text(pdf_path: Path) -> str:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Missing PDF: {pdf_path}")

    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout
