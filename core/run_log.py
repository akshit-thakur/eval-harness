"""Write eval output to logs/ and stdout."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


class RunLog:
    def __init__(self, script: str) -> None:
        output_dir = Path(os.getenv("EVAL_LOG_DIR", str(LOG_DIR)))
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        run_id = f"{stamp}_{uuid.uuid4().hex[:10]}"
        self.path = output_dir / f"{run_id}_{script}.log"
        self.json_path = output_dir / f"{run_id}_{script}.jsonl"
        self._file = self.path.open("x", encoding="utf-8")
        self._json = self.json_path.open("x", encoding="utf-8")
        self.summary: list[dict[str, Any]] = []
        self.line(f"eval-harness run started at {stamp} script={script}")

    def line(self, text: str = "") -> None:
        print(text, flush=True)
        self._file.write(text + "\n")
        self._file.flush()

    def section(self, title: str) -> None:
        self.line("")
        self.line(f"{'=' * 72}")
        self.line(title)
        self.line(f"{'=' * 72}")

    def field(self, key: str, value: str) -> None:
        self.line(f"{key}: {value}")

    def block(self, label: str, value: Any) -> None:
        self.line(f"{label}:")
        self.line(dumps(value))

    def close(self) -> None:
        self._file.close()
        self._json.close()

    def record(self, value: dict[str, Any]) -> None:
        self.summary.append(value)
        self._json.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
        self._json.flush()
