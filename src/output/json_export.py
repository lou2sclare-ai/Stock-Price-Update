from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path


def write(rows: list[dict], qa: dict, path: str):
    payload={"generated_at":datetime.now(timezone.utc).isoformat(),"qa":qa,"rows":rows}
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
