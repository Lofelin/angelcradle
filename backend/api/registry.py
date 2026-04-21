"""
婴儿注册表：持久化存储和查询已孕育的婴儿。

出生证明保存在 babies/{baby_id}/birth.json，与摇篮状态同目录。

[INPUT]: 无外部依赖
[OUTPUT]: save, load, list_all 函数
[POS]: api/ 的出生数据持久化层，被 api/conceive.py 和 cradle/ 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

import json
from pathlib import Path
from typing import Optional

ARCHIVE_DIR = Path(__file__).parent.parent / "archive"


def save(baby_dict: dict) -> None:
    """保存婴儿出生数据到 babies/{id}/birth.json。"""
    d = ARCHIVE_DIR / baby_dict["id"]
    d.mkdir(parents=True, exist_ok=True)
    path = d / "birth.json"
    path.write_text(json.dumps(baby_dict, ensure_ascii=False, indent=2), encoding="utf-8")


def load(baby_id: str) -> Optional[dict]:
    """按编号加载婴儿出生数据。"""
    path = ARCHIVE_DIR / baby_id / "birth.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_all() -> list[dict]:
    """列出所有婴儿（不含 gestation_log，减少数据量）。"""
    if not ARCHIVE_DIR.is_dir():
        return []
    babies = []
    for d in sorted(ARCHIVE_DIR.iterdir()):
        path = d / "birth.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            summary = {k: v for k, v in data.items() if k != "gestation_log"}
            babies.append(summary)
    return babies
