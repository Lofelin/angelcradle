"""
预生成模板库：LLM 离线批量生成高质量叙事模板，运行时规则引擎查表 + 连续参数化填充。

核心思想：把在线 LLM 调用拆成"离线生成模板 × 运行时组合采样"，零运行时 LLM 成本，
多样性远高于硬编码模板。

[INPUT]: templates/ 下的 JSON 文件
[OUTPUT]: TemplateLibrary 类，sample(key, filters, context) 返回填充后的文本
[POS]: womb/templates/ 的运行时入口，被 rule_engine.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent


def _fill_var(spec: dict, context: dict | None = None) -> Any:
    """按 var spec 生成一个填充值。

    spec 格式：
      {"type": "int_range", "min": 36, "max": 60}
      {"type": "float_range", "min": 0.1, "max": 0.5, "precision": 2}
      {"type": "choice", "options": ["...", "..."]}
      {"type": "context", "key": "budget"}  # 从 context 读
    """
    t = spec.get("type", "choice")
    if t == "int_range":
        return random.randint(int(spec["min"]), int(spec["max"]))
    if t == "float_range":
        precision = int(spec.get("precision", 2))
        v = random.uniform(float(spec["min"]), float(spec["max"]))
        return round(v, precision)
    if t == "choice":
        return random.choice(spec.get("options", [""]))
    if t == "context":
        if context is None:
            return spec.get("default", "")
        # 支持 "env.stress_level" 这种点号路径
        keys = spec["key"].split(".")
        cur: Any = context
        for k in keys:
            if isinstance(cur, dict):
                cur = cur.get(k)
            else:
                return spec.get("default", "")
        return cur if cur is not None else spec.get("default", "")
    return ""


def _template_matches(tpl: dict, filters: dict) -> bool:
    """检查模板的 applies_when 是否匹配给定 filters。"""
    applies = tpl.get("applies_when") or {}
    for k, want in filters.items():
        if k not in applies:
            continue
        constraint = applies[k]
        if isinstance(constraint, list):
            if want not in constraint:
                return False
        else:
            if want != constraint:
                return False
    return True


class TemplateLibrary:
    """模板库：JSON 文件集合 → 按 key 查池 → 按 filters 过滤 → 随机采样 + 填充变量。"""

    def __init__(self, root: Path):
        self._root = root
        self._cache: dict[str, list[dict]] = {}

    @classmethod
    def load(cls, root: Path | None = None) -> "TemplateLibrary":
        return cls(root or _TEMPLATE_DIR)

    def _load_pool(self, key: str) -> list[dict]:
        """延迟加载：首次访问某池时才读盘。"""
        if key in self._cache:
            return self._cache[key]
        path = self._root / f"{key}.json"
        if not path.is_file():
            logger.warning("模板池不存在: %s", path)
            self._cache[key] = []
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "templates" in data:
                pool = data["templates"]
            elif isinstance(data, list):
                pool = data
            else:
                logger.warning("模板池格式非法: %s", path)
                pool = []
        except Exception as e:
            logger.error("模板池加载失败 %s: %s", path, e)
            pool = []
        self._cache[key] = pool
        return pool

    def sample(
        self,
        key: str,
        filters: dict | None = None,
        context: dict | None = None,
    ) -> str:
        """查池 → 过滤 → 随机挑一条 → 填充变量 → 返回文本。

        key: 模板池路径（不带 .json），例如 "birth/first_cry_onset"
        filters: applies_when 匹配条件
        context: 变量填充上下文
        """
        pool = self._load_pool(key)
        if not pool:
            return ""
        filters = filters or {}
        candidates = [t for t in pool if _template_matches(t, filters)]
        if not candidates:
            candidates = pool  # 条件过严时退化为全池
        tpl = random.choice(candidates)
        text = tpl.get("text", "")
        var_specs = tpl.get("vars") or {}
        values = {name: _fill_var(spec, context) for name, spec in var_specs.items()}
        try:
            return text.format(**values)
        except (KeyError, IndexError) as e:
            logger.warning("模板变量填充失败 key=%s: %s", key, e)
            return text

    def pool_size(self, key: str) -> int:
        return len(self._load_pool(key))
