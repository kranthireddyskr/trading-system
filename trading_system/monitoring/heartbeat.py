from __future__ import annotations

import json
import time
from pathlib import Path


class Heartbeat:
    def __init__(self, output_path: Path) -> None:
        self.output_path = Path(output_path)
        self.started_at = time.time()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:
        return f"Heartbeat(output_path={str(self.output_path)!r})"

    def write(self, status: str, payload: dict) -> None:
        body = {
            "status": status,
            "uptime": round(time.time() - self.started_at, 2),
            "payload": payload,
        }
        self.output_path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")

