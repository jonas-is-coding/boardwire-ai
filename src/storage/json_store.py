from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonStore:
    @staticmethod
    def load(path: Path, default: Any) -> Any:
        if not path.exists():
            return default

        with path.open("r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return default

    @staticmethod
    def save(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
