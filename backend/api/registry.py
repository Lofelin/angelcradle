"""
婴儿注册表：持久化存储和查询已孕育的婴儿。
"""

import json
from pathlib import Path
from typing import Optional

REGISTRY_DIR = Path(__file__).parent.parent / "births"


def save(baby_dict: dict) -> None:
    """保存婴儿数据到文件。"""
    REGISTRY_DIR.mkdir(exist_ok=True)
    path = REGISTRY_DIR / f"{baby_dict['id']}.json"
    path.write_text(json.dumps(baby_dict, ensure_ascii=False, indent=2), encoding="utf-8")


def load(baby_id: str) -> Optional[dict]:
    """按编号加载婴儿数据。"""
    path = REGISTRY_DIR / f"{baby_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_all() -> list[dict]:
    """列出所有婴儿（不含 gestation_log，减少数据量）。"""
    if not REGISTRY_DIR.is_dir():
        return []
    babies = []
    for path in sorted(REGISTRY_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        summary = {k: v for k, v in data.items() if k != "gestation_log"}
        babies.append(summary)
    return babies
