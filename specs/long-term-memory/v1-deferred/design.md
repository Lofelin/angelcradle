# 技术设计：生命体长期记忆系统

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                      三层记忆栈（单向流动）                         │
│                                                                 │
│   ┌──────────────────────────────────────────────────────┐      │
│   │ L1 Semantic（语义层）                                   │      │
│   │   "我怕蜘蛛"、"我依赖奶奶"                              │      │
│   │   来源：phase_summary + 高强度 episodic 合并            │      │
│   │   存储：SQLite 表 memory_semantic                       │      │
│   │   检索：标签匹配 + 嵌入余弦（短文本）                     │      │
│   └───────────────────────▲──────────────────────────────┘      │
│                           │ 巩固（consolidation）                 │
│   ┌──────────────────────────────────────────────────────┐      │
│   │ L2 Episodic（情节层）                                   │      │
│   │   Memory 条目 + cause/effect 标签 + 嵌入向量             │      │
│   │   存储：SQLite 表 memory_episodic + embeddings          │      │
│   │   检索：向量余弦 + KG 多跳关联（via cradle_graph）        │      │
│   └───────────────────────▲──────────────────────────────┘      │
│                           │ 选择性写入（selective ingestion）     │
│   ┌──────────────────────────────────────────────────────┐      │
│   │ L0 Sensory（原始层）                                    │      │
│   │   events.jsonl 全量日志（已存在，不改结构）              │      │
│   │   存储：archive/{baby_id}/events.jsonl                  │      │
│   │   检索：按 seq / 时间范围追溯（只在调试 / 归因时读）       │      │
│   └──────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      检索金字塔（读路径）                            │
│                                                                 │
│   mind.py 需要 recall(context, budget=1500 tokens)               │
│              │                                                   │
│              ▼                                                   │
│   ┌──────────────────────────────────────────┐                   │
│   │ Step 1: Semantic 层全量取（几十条，百级 token） │                   │
│   └──────────────────────────────────────────┘                   │
│              │ 剩余预算                                            │
│              ▼                                                   │
│   ┌──────────────────────────────────────────┐                   │
│   │ Step 2: Episodic 向量检索 top-K           │                    │
│   │   + cradle_graph 2-hop 关联补充            │                    │
│   └──────────────────────────────────────────┘                   │
│              │ 剩余预算（可选）                                     │
│              ▼                                                   │
│   ┌──────────────────────────────────────────┐                   │
│   │ Step 3: Sensory 追溯最近 N 条原始事件       │                    │
│   │   （仅在 budget 尚有结余时启用）            │                    │
│   └──────────────────────────────────────────┘                   │
│              │                                                   │
│              ▼                                                   │
│       按 token 预算裁剪 → 返回 RecalledContext                      │
└─────────────────────────────────────────────────────────────────┘
```

## 2. 模块结构

```
backend/
├── memory/                          ← 新增 L2 模块
│   ├── __init__.py                  ← 对外 API: ingest / recall / consolidate
│   ├── CLAUDE.md                    ← L2 文档
│   ├── store.py                     ← SQLite schema + hot/cold 读写
│   ├── embedder.py                  ← sentence-transformers 单例 + 磁盘缓存
│   ├── ingest.py                    ← selective ingestion（新颖性 + 强度闸门）
│   ├── retrieval.py                 ← 三层金字塔 recall
│   ├── consolidation.py             ← 睡眠触发的遗忘/归档/合并
│   └── schema.sql                   ← 建表 DDL（便于冷启动和迁移）
├── cradle/
│   ├── nanny.py                     ← _update_phase_state 后调 memory.ingest
│   ├── mind.py                      ← 三个 LLM 入口改为 memory.recall
│   └── state.py                     ← BabyState 增加 memory_index_version 字段
├── cradle_graph_store.py            ← 新增 query_associative(tag, hops)
└── scheduler/                       ← 睡眠事件分支调用 memory.consolidate
```

## 3. 数据模型

### 3.1 SQLite Schema

```sql
-- 情节记忆：每条 Memory 一行，带嵌入
CREATE TABLE memory_episodic (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    baby_id       TEXT NOT NULL,
    phase         INTEGER NOT NULL,
    age_days      INTEGER NOT NULL,
    sim_time      REAL NOT NULL,
    event         TEXT NOT NULL,
    stimulus      TEXT,
    reaction      TEXT,
    trace         TEXT,
    valence       TEXT,              -- positive / negative / neutral
    intensity     REAL,              -- 0..1
    cause_tags    TEXT,              -- JSON array，复用 causality.py 产出
    effect_tags   TEXT,              -- JSON array
    parent_involved INTEGER,
    parent_action TEXT,
    growth_signal TEXT,
    embedding     BLOB,              -- float32[384]，MiniLM-L6
    forget_score  REAL DEFAULT 1.0,  -- 遗忘分数，每次巩固重算
    archived      INTEGER DEFAULT 0, -- 1 表示被合并到 semantic 层
    created_at    REAL NOT NULL,
    INDEX idx_baby_phase (baby_id, phase),
    INDEX idx_baby_forget (baby_id, archived, forget_score)
);

-- 语义记忆：阶段要点和聚合摘要
CREATE TABLE memory_semantic (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    baby_id       TEXT NOT NULL,
    kind          TEXT NOT NULL,     -- phase_summary / trait / pattern
    phase_range   TEXT,              -- "3-5" 表示跨第 3 到第 5 阶段
    content       TEXT NOT NULL,     -- 短文本，≤ 200 字
    tags          TEXT,              -- JSON array
    source_ids    TEXT,              -- 来源 episodic id 的 JSON array
    embedding     BLOB,
    created_at    REAL NOT NULL,
    INDEX idx_baby_kind (baby_id, kind)
);
```

### 3.2 对外 API（memory/__init__.py）

```python
# 写入路径
def ingest(baby_id: str, memory: Memory, state: BabyState) -> bool:
    """selective ingestion。返回 True 表示入库，False 表示被过滤。"""

# 读取路径
def recall(
    baby_id: str,
    context: str,               # 当前情境描述（由 mind.py 组装）
    current_tags: list[str],    # 当前事件的 cause_tags，用于 KG 关联
    token_budget: int = 1500,
) -> RecalledContext:
    """三层金字塔检索。"""

# 巩固路径
def consolidate(baby_id: str, phase: int, sim_time: float) -> ConsolidationReport:
    """睡眠触发。遗忘衰减 + 低分归档 + 高相似合并 + 语义摘要生成。"""

@dataclass
class RecalledContext:
    semantic: list[SemanticHit]   # 要点
    episodic: list[EpisodicHit]   # 情节 + 相似度
    graph_hits: list[GraphHit]    # KG 关联补充
    raw_refs: list[int]           # events.jsonl seq 引用（可选）
    used_tokens: int
```

## 4. 关键算法

### 4.1 Selective Ingestion

```
memory 进来 → 判定是否入库：

  intensity < 0.2 且 valence == "neutral"  → 丢弃（日常刷牙类）
  novelty_score < 0.3                       → 丢弃（和已有条目语义近乎重复）
  parent_involved == True 或 intensity ≥ 0.6 或 event ∈ CRITICAL_EVENTS
                                             → 强制入库
  其他                                       → 入库

novelty_score 计算：
  取最近 20 条 episodic 的 embedding
  novelty = 1 - max(cosine(new_embedding, recent_embeddings))
```

### 4.2 Progressive Retrieval

```
budget = 1500 tokens

Step 1 Semantic:
  SELECT * FROM memory_semantic WHERE baby_id=?
    ORDER BY created_at DESC LIMIT 20
  → 按标签匹配 current_tags 加权 → 取 top 5
  budget -= used

Step 2 Episodic:
  query_emb = embed(context)
  top_K = SQLite vector search (cosine) top 10
  # KG 关联：通过 cause_tags 在 cradle_graph 中做 2-hop 扩展
  graph_neighbors = cradle_graph.query_associative(current_tags, hops=2)
  merged = dedupe(top_K + graph_neighbors) 按 (相似度 * forget_score) 排序
  budget -= used

Step 3 Sensory:
  if budget > 300:
    取最近 N 条 events.jsonl（通常 N=3~5）
  else:
    跳过
```

### 4.3 Forgetting Curve

```python
TAU_BY_PHASE = {
    0: 3,    # 新生儿 τ=3 天，infantile amnesia 最强
    1: 7,
    2: 14,
    3: 30,
    4: 60,
    5: 90,
    6: 180,
    7: 365,
    # ...12 阶段渐增
}

def update_forget_score(mem, current_age_days):
    age = current_age_days - mem.age_days
    tau = TAU_BY_PHASE[mem.phase]
    emotional_boost = 1.0 + 0.5 * mem.intensity  # 强情感抗遗忘
    mem.forget_score = mem.intensity * math.exp(-age / (tau * emotional_boost))
```

### 4.4 Consolidation（睡眠触发）

```
consolidate(baby_id, phase, sim_time):
    1. 重算所有非 archived episodic 的 forget_score
    2. forget_score < 0.1 → 标记 archived=1（不删除，便于审计）
    3. 找出 cluster（嵌入余弦 > 0.85 且同 phase）→ 合并成 semantic.kind="pattern"
    4. 若当前是阶段末尾睡眠事件：
         生成 phase_summary（引用 mind.generate_phase_summary 的已有输出）
         写入 semantic.kind="phase_summary"
    5. 返回 ConsolidationReport（归档数 / 合并数 / 新增语义数）
```

## 5. 接入点（最小侵入）

### 5.1 nanny.py（写入）

```python
# _snapshot_state 生成 memory 后：
from memory import ingest
if ingest(baby_id, new_memory, state):
    state.memory.append(new_memory)   # 保留旧 list 做向后兼容
```

### 5.2 mind.py（读取，3 个入口）

```python
# generate_interaction_response / process_critical_event / narrate_phase_events
from memory import recall
recalled = recall(baby_id, context=scene_desc, current_tags=cause_tags, token_budget=1500)
prompt = render_prompt(recalled=recalled, ...)    # 替换原来的"最近 K 条"
```

### 5.3 scheduler 睡眠事件（巩固）

```python
# 在现有 sleep 事件处理器中：
if event.name in {"night_sleep", "nap"}:
    from memory import consolidate
    report = consolidate(baby_id, state.current_phase, state.sim_time)
    # 可选：把 report 写入 events.jsonl 作为 memory_consolidation 事件
```

### 5.4 cradle_graph_store.py（新增查询）

```python
def query_associative(baby_id: str, tags: list[str], hops: int = 2) -> list[GraphHit]:
    """从 tags 出发 BFS 扩展 hops 层，返回关联到的节点及路径。纯读路径，不改写入。"""
```

## 6. 向后兼容

| 旧数据 | 行为 |
|---|---|
| `BabyState.memory` list 已有 N 条 | 加载时触发"索引重建"：逐条走一次 ingest（强制 bypass selective 闸门），生成嵌入写入 SQLite |
| `BabyState` 无 `memory_index_version` | 视为 0，触发重建；重建后写入 1 |
| 老 baby 无 embeddings | 首次 recall 前按需补算，后台 task 不阻塞请求 |
| 新代码 crash / 被回滚 | 旧 list 仍然完整，读路径退回到"最近 K 条"行为 |

## 7. 技术选型理由

| 决策 | 选择 | 拒绝的替代方案 | 理由 |
|---|---|---|---|
| 向量存储 | SQLite + `sqlite-vss`（或纯 Python numpy）| Milvus / Qdrant / pgvector | 单 baby 规模几千条，起一个独立服务违反"三问过滤" |
| 嵌入模型 | sentence-transformers MiniLM-L6-v2 | OpenAI text-emb-3 / GPT-4o 实体抽取 | 本地零成本，80MB，CPU 即可；LLM 嵌入每次心跳烧钱 |
| 实体抽取 | 复用 `causality.py` 的纯规则 cause/effect_tags | 用 GPT-4o 抽实体 | 已存在且零 LLM 成本，论文的 LLM 抽取是 overkill |
| 巩固触发 | 睡眠事件 | 定时 cron / 每 N 条触发 | 生物同构，无额外调度器负担 |
| 遗忘模型 | 指数衰减 `e^(-Δ/τ)` | 机器学习 forgetting | 简单、可解释、符合 Ebbinghaus 经典曲线 |
| KG 查询 | 复用 `cradle_graph_store` 加 `query_associative` | 新建专门的 memory KG | 分形复用铁律，避免两套 KG 失同步 |

## 8. 性能估算

| 操作 | 频率 | 成本 |
|---|---|---|
| ingest 一条 memory | ≈ 10 次/天/baby | 嵌入 ~10ms + SQL insert ~1ms |
| recall 一次 | ≈ 5 次/天/baby（LLM 调用前）| 嵌入 ~10ms + 向量查 ~20ms + KG 2-hop ~10ms ≈ 50ms |
| consolidate 一次 | ≈ 2 次/天/baby（午睡 + 夜睡）| 全表扫描 + 聚类，预期 200ms 内 |
| 存储 | 每 baby | ~1MB/月（episodic 几百条 + 嵌入）|

调度器瓶颈不变。嵌入模型首次加载 ~2s，之后单例常驻。

## 9. 风险与取舍

| 风险 | 缓解 |
|---|---|
| SQLite vss 扩展跨平台编译问题 | 回退到纯 numpy 余弦，性能下降可接受（几千条数量级）|
| MiniLM-L6-v2 中文支持一般 | 大部分记忆字段是结构化 + 英文标签，中文叙事用 `paraphrase-multilingual-MiniLM-L12-v2`（120MB）做备选 |
| 巩固合并误删重要记忆 | `archived=1` 软删除，可随时恢复；审计日志记录每次合并 |
| 旧 baby 重建索引耗时 | 异步后台 task，不阻塞 API；状态标记 `index_version` 幂等 |
| 遗忘曲线参数需要调 | `TAU_BY_PHASE` 单独放 `memory/forget_params.py`，便于 A/B 调整 |

## 10. 分形同构检查

- L1 `/CLAUDE.md`: 顶层目录清单新增 `memory/`
- L2 `memory/CLAUDE.md`: 新建，按模板包含成员清单 / 对外暴露 / 依赖关系 / 数据流
- L3 每个新文件头部含 `[INPUT] / [OUTPUT] / [POS] / [PROTOCOL]` 四行注释
- `cradle/CLAUDE.md`: 在"依赖关系"小节增加 `memory/` 条目
- `events/CLAUDE.md`: 无需变更
