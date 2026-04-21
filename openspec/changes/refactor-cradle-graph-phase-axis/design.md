# 技术设计：phase / progression 两分

## 1. 概念边界（核心）

| 概念 | 性质 | 数量 | id 规约 | 来源 | 在图谱中的角色 |
|------|------|------|--------|------|---------------|
| **progression** | 引擎调度游标 | 12（全局唯一序列） | `progression:{phase_name}` | `cradle.phases.PHASES` | 叙事时间线，挂在 `baby:core` 下，不参与 OCCURS_IN |
| **phase** | 发育期（领域知识） | 6 维 × 4~5 期 ≈ 28 | `phase:{dim}:{stage}` | `cradle.ontology.DIMENSION_PHASES`（新增静态表） | L2 节点，挂 `BELONGS_TO → dimension:{dim}`；capability/milestone 的 OCCURS_IN 目标 |

铁律：**capability/milestone 永远不再 OCCURS_IN 到 progression**；progression 永远不再持有 BELONGS_TO 维度边。

## 2. per-dimension Phase 静态表（首版）

定义在 `cradle/ontology.py`，对齐 cradle-dev-ontology proposal.md:58-69 + Bayley-IV / Piaget / Vineland-3：

```python
DIMENSION_PHASES: dict[str, list[dict]] = {
    "motor": [
        {"key": "neonatal",     "display": "Neonatal Reflex",   "age_days": (0, 30)},
        {"key": "early_infant", "display": "Early Infant",      "age_days": (30, 180)},
        {"key": "late_infant",  "display": "Late Infant",       "age_days": (180, 365)},
        {"key": "toddler",      "display": "Toddler",           "age_days": (365, 1095)},
        {"key": "preschool",    "display": "Preschool",         "age_days": (1095, 2555)},
    ],
    "language": [
        {"key": "prelinguistic","display": "Prelinguistic",     "age_days": (0, 270)},
        {"key": "first_words",  "display": "First Words",       "age_days": (270, 540)},
        {"key": "telegraphic",  "display": "Telegraphic",       "age_days": (540, 1095)},
        {"key": "grammar",      "display": "Grammar Burst",     "age_days": (1095, 1825)},
        {"key": "narrative",    "display": "Narrative",         "age_days": (1825, 2555)},
    ],
    "cognitive": [  # Piaget 四阶段（前两个）
        {"key": "sensorimotor", "display": "Sensorimotor",      "age_days": (0, 730)},
        {"key": "preoperational","display":"Preoperational",    "age_days": (730, 2555)},
    ],
    "socioemotional": [
        {"key": "attachment_forming", "display": "Attachment Forming", "age_days": (0, 270)},
        {"key": "differentiation",    "display": "Differentiation",    "age_days": (270, 1095)},
        {"key": "peer_emergence",     "display": "Peer Emergence",     "age_days": (1095, 1825)},
        {"key": "moral_self",         "display": "Moral Self",         "age_days": (1825, 2555)},
    ],
    "adaptive": [  # Vineland-3
        {"key": "reflex_routine",  "display": "Reflex & Routine", "age_days": (0, 365)},
        {"key": "self_help",       "display": "Self-Help",        "age_days": (365, 1460)},
        {"key": "rule_following",  "display": "Rule Following",   "age_days": (1460, 2555)},
    ],
    "temperament": [
        {"key": "innate",          "display": "Innate",           "age_days": (0, 365)},
        {"key": "expression",      "display": "Expression",       "age_days": (365, 1460)},
        {"key": "self_regulation", "display": "Self-Regulation",  "age_days": (1460, 2555)},
    ],
}
```

辅助函数：
```python
def phase_for(dim: str, age_days: int) -> str:
    """按年龄路由到 per-dim phase id。"""
    for p in DIMENSION_PHASES.get(dim, []):
        lo, hi = p["age_days"]
        if lo <= age_days < hi:
            return f"phase:{dim}:{p['key']}"
    return f"phase:{dim}:{DIMENSION_PHASES[dim][-1]['key']}"  # 兜底末期

def all_phase_ids() -> list[str]:
    """全部 per-dim phase id（迁移/初始化用）。"""
    return [f"phase:{d}:{p['key']}" for d, ps in DIMENSION_PHASES.items() for p in ps]
```

## 3. 写入路径改造

### 3.1 `_ensure_phase_node`（新增）
替代旧的"按 progression 名直接拼 phase id"：
```python
def _ensure_phase_node(g, dim: str, stage: dict) -> str:
    pid = f"phase:{dim}:{stage['key']}"
    if pid not in g["nodes"]:
        _add_node(g, pid, "phase", stage["display"], stage["display"],
                  weight=3, dimension=dim,
                  age_range=f"{stage['age_days'][0]}-{stage['age_days'][1]}d")
        # 强制 BELONGS_TO → dimension（解决孤岛）
        _ensure_dimension_nodes(g)
        _add_edge(g, f"{pid}->dimension:{dim}", pid, f"dimension:{dim}",
                  "BELONGS_TO", 1.0, f"Phase 归属 {dim} 维度")
    return pid
```

### 3.2 `_ensure_progression_node`（新增）
```python
def _ensure_progression_node(g, phase_index: int, phase_name: str, phase_display: str) -> str:
    pgid = f"progression:{phase_name}"
    if pgid not in g["nodes"]:
        _add_node(g, pgid, "progression", phase_display, phase_display,
                  weight=2, phase_index=phase_index, layer=2)
        if "baby:core" in g["nodes"]:
            _add_edge(g, f"baby:core->{pgid}", "baby:core", pgid,
                      "ENABLES", 0.5, "Cradle progression step")
        if phase_index > 0:
            from cradle.phases import PHASES
            prev = f"progression:{PHASES[phase_index-1].name}"
            if prev in g["nodes"]:
                _add_edge(g, f"{prev}->{pgid}", prev, pgid,
                          "EVOLVES_FROM", 0.7, "Step transition")
    return pgid
```

### 3.3 capability OCCURS_IN 改造
`save_capabilities_graph` 内：
```python
for cap in new_capabilities:
    cid = f"capability:{cap}"
    dim = CAPABILITY_TO_DIMENSION.get(cap)  # 已存在
    bsid_dim = BSID_TO_DIMENSION.get(dim)    # 7 维 → 6 维
    if bsid_dim:
        # 按 baby 当前 age_days 路由到 per-dim phase
        stage = _stage_for_age(bsid_dim, state.age_days)
        pid = _ensure_phase_node(g, bsid_dim, stage)
        _ensure_occurs_in(g, cid, pid)  # 改指 per-dim phase
        _ensure_belongs_to(g, cid)      # 维持
```

### 3.4 旧 `phase:{phase_name}` 调用统一替换为 progression
- `save_phase_graph(...)`：内部 `pid = f"phase:{phase_name}"` → `pgid = _ensure_progression_node(...)`，所有"phase → X"边改为"progression → X"
- `save_milestones_graph` / `save_psychosocial_graph` / `save_caregiver_graph` / `save_scene_graph` / `save_stress_graph` / `save_critical_graph`：把 `pid = f"phase:{phase_name}"` 同步改为 progression id；其中 milestone 额外补 OCCURS_IN → per-dim phase（按 milestone 的 dimension）

## 4. 校验扩展

`validate.py` META-RULE 增补：
```python
# 新增 RULE：phase 节点必须有 BELONGS_TO → dimension
for nid, n in nodes.items():
    if n.get("category") == "phase":
        have = outgoing.get(nid, set())
        if "BELONGS_TO" not in have:
            errors.append(ValidationError(
                rule="META-RULE-PHASE",
                severity="ERROR",
                node_id=nid,
                message="phase 节点无 BELONGS_TO 出边（孤岛 phase）",
            ))
```

并修订原 RULE 描述：capability/milestone 的 OCCURS_IN 目标 category 必须是 `phase`（不能是 `progression`）。

## 5. 数据迁移（v2 → v3）

`scripts/migrate_cradle_graph_v2_to_v3.py` 步骤（机械、零 LLM、idempotent）：

```
1. 备份: cradle_graph.json → cradle_graph.json.v2.bak
2. 遍历 graph["nodes"]:
   for nid, n in list(nodes.items()):
     if n["category"] == "phase":
       # 重分类为 progression
       phase_name = nid.split(":", 1)[1]            # "Neonatal" → 根据 PHASES 反查 .name="neonatal"
       canonical = _normalize(phase_name)
       new_id = f"progression:{canonical}"
       n["category"] = "progression"
       n["node_id"] = new_id
       nodes[new_id] = n
       del nodes[nid]
       # 重写所有引用此节点的边
       for e in edges.values():
         if e["source_id"] == nid: e["source_id"] = new_id
         if e["target_id"] == nid: e["target_id"] = new_id
3. 为每个维度播种 per-dim phase 节点（按 DIMENSION_PHASES 全表）+ BELONGS_TO 边
4. 遍历 capability / milestone:
   - 找出原 OCCURS_IN 边（目标已被改名为 progression:*）
   - 删除该边
   - 按 capability 的 bsid_dimension + 节点的 emerged_at_day 路由到 per-dim phase
   - 添加新 OCCURS_IN 边
5. 写 SCHEMA_VERSION = 3
6. 跑 validate_graph 输出迁移前后对比
```

幂等保护：
- 步骤 2：`if "category" != "phase"` 跳过
- 步骤 3：`if pid in nodes` 跳过
- 步骤 4：`if 已有 OCCURS_IN → phase:{dim}:*` 跳过

## 6. 向后兼容策略

| 旧形式 | 新形式 | 兼容期 |
|--------|--------|--------|
| `phase:Neonatal` 节点 | `progression:neonatal` 节点 | 永久（迁移后旧 id 不再写入） |
| `category=="phase"` 含义 | 仅 per-dim Phase；旧含义已迁移 | 立即（迁移脚本一次性） |
| `_ensure_occurs_in(g, cid, "phase:Neonatal")` 调用 | 内部 deprecation warning，自动转译为 progression id（不创建 OCCURS_IN，仅创建 ENABLES 兜底） | 1 个 release，之后强制报错 |
| 前端 `category=="phase"` 配色 | 自动分配（颜色变化但不报错），可在后续 PR 显式指定 | 立即 |

## 7. 实施顺序与可回退性

| 阶段 | 步骤 | 可回退 |
|------|------|--------|
| **A** 基础设施 | 添加 `DIMENSION_PHASES` 表 + 辅助函数 + `_ensure_phase_node` / `_ensure_progression_node` | 是（纯新增） |
| **B** 写入路径改造 | 重写 8 个 `save_*_graph` 内部 phase id 来源 | 是（git revert 单 commit） |
| **C** 校验扩展 | validate.py 新规则；MVP 仍 warning 级 | 是 |
| **D** 数据迁移 | 跑 `migrate_cradle_graph_v2_to_v3.py`；保留 `.v2.bak` | 是（恢复备份） |
| **E** 测试与文档 | 单元测试 + L2 文档更新 | n/a |

每阶段独立 commit，遇到 bug 可单独 revert。

## 8. 未决问题

1. **Q：现有 `_emit_evolves_from` 已经 per-dim 演化链了，本次改造与它如何对齐？**
   - A：不冲突。EVOLVES_FROM 走 capability↔capability，不涉及 phase 节点。本次只改 OCCURS_IN 目标。

2. **Q：capability 跨维度怎么办（如 `pretend_play` 同时 cognitive + socioemotional）？**
   - A：v3 暂只走 `bsid_dimension` 主维度（CAPABILITY_TO_DIMENSION 已选定）；多维归属推迟到下一变更。

3. **Q：scheduler 的 `phase_index` 仍是 12 步，前端进度条如何展示？**
   - A：前端读 `state.current_phase`（progression 游标）即可，不依赖图谱。本变更不动 state schema。
