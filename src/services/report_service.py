from __future__ import annotations

from pathlib import Path


def save_report(output_dir: Path, report_label: str, report_text: str) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"Utilization_Report_{report_label}.txt"
    path.write_text(report_text, encoding="utf-8")
    return path
