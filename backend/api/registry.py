"""
婴儿注册表：持久化存储和查询已孕育的婴儿。

每个婴儿一个目录 archive/{baby_id}/，容纳该生命所有的历史数据：
  - birth.json          出生证明（身份/表型/基因型/环境/并发症）
  - womb_graph.json     孕育图谱快照（节点 + 边 + 元数据）
  - cradle_graph.json   摇篮成长图谱快照（v3-business-as-graph schema）
  - events.jsonl        事件流日志
  - life_moments.jsonl/milestones.jsonl  成长期生活/里程碑
  - portrait_*.png      画像

[INPUT]: 无外部依赖
[OUTPUT]: save, load, list_all, list_all_page, BIRTH_BABIES_PAGE_SIZE_MAX,
          save_womb_graph, load_womb_graph,
          save_cradle_graph, load_cradle_graph 函数
[POS]: api/ 的出生数据持久化层，被 api/conceive.py 和 cradle/ 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

import json
from pathlib import Path
from typing import Optional

ARCHIVE_DIR = Path(__file__).parent.parent / "archive"


def save(baby_dict: dict) -> None:
    """保存婴儿出生数据到 archive/{id}/birth.json。"""
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


# 分页端点（/babies）的页大小硬上限——防止客户端传大数触发全量 JSON 解析。
BIRTH_BABIES_PAGE_SIZE_MAX = 100


def list_all_page(page: int = 1, page_size: int = 100) -> tuple[list[dict], int]:
    """分页列出所有婴儿（摘要，不含 gestation_log）。

    返回 (page_babies, total)。按 archive 目录名字典序排序。
    仅解析落在当前页窗口内的 birth.json，total 用目录 stat 统计，
    避免 N 可达数千时的 O(N) 全量 JSON 解析。

    page < 1 夹紧到 1；page_size 夹紧到 [1, BIRTH_BABIES_PAGE_SIZE_MAX]。
    超出最后一页返回空 babies，total 仍为实际总数。
    """
    page = max(1, int(page))
    page_size = max(1, min(BIRTH_BABIES_PAGE_SIZE_MAX, int(page_size)))

    if not ARCHIVE_DIR.is_dir():
        return [], 0

    baby_dirs = [
        d for d in sorted(ARCHIVE_DIR.iterdir())
        if (d / "birth.json").is_file()
    ]
    total = len(baby_dirs)

    start = (page - 1) * page_size
    end = start + page_size
    window = baby_dirs[start:end]

    babies = []
    for d in window:
        data = json.loads((d / "birth.json").read_text(encoding="utf-8"))
        summary = {k: v for k, v in data.items() if k != "gestation_log"}
        babies.append(summary)
    return babies, total


def save_womb_graph(baby_id: str, graph: dict) -> None:
    """保存孕育图谱快照到 archive/{id}/womb_graph.json。

    graph 结构: {nodes: [...], edges: [...], metadata: {...}}
    """
    d = ARCHIVE_DIR / baby_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / "womb_graph.json"
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")


def load_womb_graph(baby_id: str) -> Optional[dict]:
    """按 baby_id 读取孕育图谱快照。"""
    path = ARCHIVE_DIR / baby_id / "womb_graph.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================
# 摇篮成长图谱（add-cradle-growth-graph）
# ============================================================

CRADLE_GRAPH_SCHEMA_CURRENT = "v3-business-as-graph"


def save_cradle_graph(baby_id: str, graph: dict) -> None:
    """保存摇篮成长图谱快照到 archive/{id}/cradle_graph.json。

    graph 结构（约定）:
        {
          "baby_id", "species", "sex",
          "schema": "v3-business-as-graph",
          "status": "alive" | "world_ready" | "deceased" | "cradle_incomplete",
          "saved_at", "phases_completed",
          "nodes": [...], "edges": [...],
          "stats": {...}
        }

    不强制校验 schema——调用方负责填好；这里只确保 schema 字段存在。
    """
    if "schema" not in graph:
        graph["schema"] = CRADLE_GRAPH_SCHEMA_CURRENT
    d = ARCHIVE_DIR / baby_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / "cradle_graph.json"
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cradle_graph(baby_id: str) -> Optional[dict]:
    """按 baby_id 读取摇篮成长图谱快照。

    schema 不匹配当前版本时返回 None（视同"请重新跑一次生命"）。这样写的
    原因：老的 cradle_graph_store.py 时代的残留文件若存在，直接返回会让前端
    按 v3 schema 解析时崩溃；让端点返回 404 更干净。
    """
    path = ARCHIVE_DIR / baby_id / "cradle_graph.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != CRADLE_GRAPH_SCHEMA_CURRENT:
        return None
    return data
