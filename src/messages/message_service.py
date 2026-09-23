from __future__ import annotations

from pathlib import Path


def save_message(output_dir: Path, report_label: str, message_text: str) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"Utilization_Message_{report_label}.txt"
    path.write_text(message_text, encoding="utf-8")
    return path
