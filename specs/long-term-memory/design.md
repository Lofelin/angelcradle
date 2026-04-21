# 技术设计：LifeMoment 统一原子 · 阶段 A

> 依据：三轮评审 11 条共识（C1~C11）+ 三组补强（D1 架构安全 / D2 Omni 对齐 / D3 回补）+ 用户场景验证。
> 评审档案：`reviews/`

## 1. 架构总览

```
┌────────────────────────────────────────────────────────────────┐
│ 写路径：record_moment() 单写入口（CI 禁用直接 append）            │
│                                                                │
│  业务代码调用 record_moment(state, baby_id, **fields)           │
│      │                                                         │
│      ▼                                                         │
│  ┌─ ingest.should_ingest(...) ──── Jaccard 新颖性闸门 ───┐       │
│  │   高强度/首触/caregiver 参与 → 强制入库               │       │
│  └──────────────────────────────────────────────────────┘       │
│      │                                                         │
│      ▼                                                         │
│  1. append life_moments.jsonl（新真相源）                        │
│  2. state.memories.append(_downgrade_to_memory(moment))          │
│     (V2=on 依然保留，守 interaction 等 spec 契约)                 │
│  3. save_state（原子 tempfile + os.replace）                     │
│                                                                │
│  写顺序：先 jsonl，后 state.json。进程崩溃时 jsonl 孤儿可容忍    │
│  (recall fallback 到 state.memories)；反之不行                   │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│ 读路径：recall(state, context, tags, token_budget=1500)         │
│                                                                │
│  MEMORY_V2=off  → 旧分支：state.memories[-3:]                  │
│  MEMORY_V2=on   → 新分支（下）                                  │
│      │                                                         │
│      ▼                                                         │
│  Step 1 semantic: state.phase_summaries[-3:]（独立，不混）       │
│         budget -= tokens                                       │
│      │                                                         │
│      ▼                                                         │
│  Step 2 episodic: life_moments 按 (jaccard + tag_overlap        │
│         + forget_score) 排序 top_k                              │
│         ├─ tag 一跳倒排：从 top_k 的 cause/effect_tags 扩展     │
│         │  同 tag 历史条目 1-3 条（内存 dict，cradle_graph 不碰）│
│         └─ budget -= tokens                                    │
│      │                                                         │
│      ▼                                                         │
│  Step 3 milestone: 相关里程碑 top 3（若 budget 允许）            │
│                                                                │
│  返回 RecalledContext(semantic, episodic, milestones, used)    │
└────────────────────────────────────────────────────────────────┘
```

## 2. 模块结构

```
backend/
├── memory/                       ← 新增 L2 模块
│   ├── __init__.py               ← 导出 record_moment / recall / recompute / prune / is_v2_enabled
│   ├── CLAUDE.md                 ← L2 文档
│   ├── schema.py                 ← LifeMoment / Milestone / RecalledContext dataclass
│   ├── store.py                  ← life_moments.jsonl / milestones.jsonl 原子 append + seq
│   ├── ingest.py                 ← should_ingest 新颖性闸门 + record_moment 单写入口
│   ├── recall.py                 ← 三层金字塔检索 + token_budget 裁剪 + tag 一跳倒排
│   ├── forget_params.py          ← TAU_BY_PHASE / 阈值常量 / MEMORY_V2_ENV
│   └── consolidation.py          ← recompute_forget_scores / prune_if_needed
├── cradle/
│   ├── state.py                  ← Memory 增 forget_score 字段（向后兼容）
│   ├── mind.py                   ← 三 LLM 入口接入 recall（保留 V2=off 回退）
│   └── nanny.py                  ← 原 Memory() 创建点 → record_moment()
├── scheduler/
│   ├── story.py / handlers.py / needs.py
│                                 ← 多处 Memory() + 新增主动行为/里程碑 record_moment
├── heartbeat.py                  ← initiative 产出 → record_moment(actor="self")
├── initiative_needs.py           ← need 触发 → record_moment
├── world.py                      ← experienced / snapshot 读路径改走 recall
├── events/__init__.py            ← 涌现冷却 读 memory 改走 life_moments
└── api/cradle.py                 ← /status /history /intervention 三端点兼容改造
```

## 3. 数据模型

### 3.1 LifeMoment（事件原子）

```python
# backend/memory/schema.py
from dataclasses import dataclass, field

@dataclass
class LifeMoment:
    # 身份（单 baby 单序列，复用 state.py 的 _get_seq_lock 基础设施）
    seq: int
    source_seq: int = -1             # events.jsonl 反查；-1=无

    # 时空
    phase: int = 0
    age_days: int = 0
    sim_time: float = 0.0

    # 当事人（无 kind，用 actor/target 组合推断事件类型）
    actor: str = "world"             # "world" / "self" / f"caregiver:{stable_key}"
    target: str = ""                 # 同格式；"" = 无特定对象
    witnesses: list[str] = field(default_factory=list)

    # 内容
    trigger: str = ""                # 事件名 / need trigger / action key
    action: str = ""                 # what happened（≤ 120 字）
    response: str = ""               # 对方回应；"" = 无回应/被忽略
    outcome: str = "neutral"         # responded / ignored / succeeded / failed / neutral
    companion_seq: int = -1          # append-only 状态转移链：后续响应/超时 moment 的 seq

    # 感受
    valence: str = "neutral"         # positive / negative / neutral
    intensity: float = 0.5           # 0..1

    # 标签（严格复用 causality.py 产出，示例见下）
    cause_tags: list[str] = field(default_factory=list)
    effect_tags: list[str] = field(default_factory=list)

    # 首触标记（第 2 轮领域 agent 补强）
    is_first: bool = False

    # 遗忘分（recall 时动态计算，持久化作 cache 以便 rebuild）
    # 公式：forget_score = intensity × exp(-Δ_days / TAU_BY_PHASE[phase])
    forget_score: float = 1.0
```

### 3.2 真实 tag 格式示例（核对 causality.py）

`causality.py` 实际产出的标签（本 spec 严格复用，**禁止自造**）：

| 命名空间 | 格式 | 示例 |
|---|---|---|
| sensory | `sensory_dominant:{n}` / `sensory_weak:{n}` / `sensory_related:{n}` | `sensory_dominant:touch` |
| arousal | `arousal:{level}` | `arousal:high` / `arousal:sensitive` / `arousal:overstimulated` |
| stress | `stress:{level}` / `stress:{sign}{delta}` | `stress:high` / `stress:+0.15` / `stress:stable` |
| phase | `phase:{N}` | `phase:5` |
| defect | `defect:{name}` / `defect:related` | `defect:hearing_impairment` |
| attachment | `attachment:toward_{style}` | `attachment:toward_secure` |
| capability | `capability:unlock:{cap}` / `capability:regress:{cap}` | `capability:unlock:walking` |
| memory | `memory:{valence}` | `memory:positive` |
| growth | `growth:{X}` | `growth:self_regulation` |
| category | `category:{cat}` | `category:critical` |
| 动态 | `{prefix}:add:{item}` | `preference:add:music` |

#### "找妈妈讨论上学" 的装载示意

```python
LifeMoment(
    seq=42,
    actor="self",
    target="caregiver:mom",
    witnesses=[],
    trigger="discuss_schooling",
    action="提出想和妈妈聊要不要上学",
    response="妈妈列了上学和不上学的各自利弊",
    outcome="responded",
    valence="positive",
    intensity=0.75,
    cause_tags=["phase:6", "arousal:moderate"],          # ← causality.generate_cause_tags 真实产出
    effect_tags=["memory:positive", "growth:decision_forming"],  # ← causality.generate_effect_tags
    is_first=True,
    forget_score=0.75,
)
```

### 3.3 Milestone（独立 dataclass，时间语义不同）

```python
@dataclass
class Milestone:
    seq: int
    phase: int
    age_days: int
    sim_time: float
    kind: str           # capability_gained / capability_lost / capability_recovered
                        # / milestone_reached / first_X / phase_advanced / cradle_complete
    subject: str        # 能力名 / milestone 名 / first_X 事件名
    description: str
    intensity: float = 0.8
    tags: list[str] = field(default_factory=list)
```

### 3.4 RecalledContext

```python
@dataclass
class RecalledContext:
    semantic: list[dict]             # phase_summaries[-3:] 直读，保持 dict 结构
    episodic: list[LifeMoment]
    milestones: list[Milestone]
    used_tokens: int
    budget: int                      # 原预算，便于日志
```

### 3.5 Memory 字段扩展（向后兼容增量）

```python
# cradle/state.py Memory
@dataclass
class Memory:
    # ...原字段不动
    forget_score: float = 1.0        # ← 新增，from_dict 防御性 d.get("forget_score", 1.0)
```

**state schema 不改**：`state.memories` / `state.phase_summaries` 保持原结构，只增一个可选字段。向后兼容铁律（C3）。

## 4. 核心算法

### 4.1 record_moment 单写入口（D1-1 保障）

```python
# backend/memory/ingest.py
def record_moment(state, baby_id: str, *,
                  actor, target="", trigger="", action="", response="",
                  outcome="neutral", valence="neutral", intensity=0.5,
                  cause_tags=None, effect_tags=None, witnesses=None,
                  is_first=False, source_seq=-1, companion_seq=-1) -> LifeMoment | None:
    """唯一 LifeMoment 写入口。CI 静态检查将禁止 state.memories.append 直接调用。"""
    seq = store.next_moment_seq(baby_id)
    moment = LifeMoment(
        seq=seq, phase=state.current_phase, age_days=state.age_days,
        sim_time=state.sim_time, actor=actor, target=target,
        witnesses=witnesses or [], trigger=trigger, action=action,
        response=response, outcome=outcome, valence=valence,
        intensity=intensity, cause_tags=cause_tags or [],
        effect_tags=effect_tags or [], is_first=is_first,
        source_seq=source_seq, companion_seq=companion_seq,
    )
    moment.forget_score = _compute_forget_score(moment, state.age_days)

    # 新颖性闸门（D2-1 补强）
    if not should_ingest(state, baby_id, moment):
        return None

    # 写顺序：先 jsonl，再 state（崩溃时 jsonl 孤儿可容忍）
    store.append_life_moment(baby_id, moment)

    # V2=on 降级回写 state.memories（D1-2 保障：守 interaction 等 spec 契约）
    state.memories.append(_downgrade_to_memory(moment))

    return moment

def _downgrade_to_memory(moment: LifeMoment) -> "Memory":
    """把 LifeMoment 压缩成传统 Memory，供 interaction 等旧契约消费。"""
    from cradle.state import Memory
    return Memory(
        phase=moment.phase, age_days=moment.age_days,
        event=moment.trigger or moment.action[:40],
        stimulus=moment.action if moment.actor != "self" else "",
        reaction=moment.response if moment.actor != "self" else moment.action,
        trace=",".join(moment.cause_tags),
        emotional_valence=moment.valence, intensity=moment.intensity,
        parent_involved=(moment.actor.startswith("caregiver:") or moment.target.startswith("caregiver:")),
        parent_action=moment.action if moment.actor.startswith("caregiver:") else "",
        growth_signal=",".join(t for t in moment.effect_tags if t.startswith("growth:")),
        forget_score=moment.forget_score,
    )
```

### 4.2 Selective Ingestion（D2-1）

```python
# backend/memory/ingest.py
_RECENT_WINDOW = 20
_JACCARD_THRESHOLD = 0.7
_LOW_INTENSITY = 0.4

def should_ingest(state, baby_id: str, moment: LifeMoment) -> bool:
    # 强制入库白名单
    if moment.intensity >= 0.7 or moment.is_first:
        return True
    if moment.actor.startswith("caregiver:") or moment.target.startswith("caregiver:"):
        return True

    # 低强度 + 高重复 → 丢弃
    if moment.intensity < _LOW_INTENSITY:
        recent = store.load_recent_moments(baby_id, limit=_RECENT_WINDOW)
        for r in recent:
            if _jaccard(_tokens(moment.action + moment.trigger),
                        _tokens(r.action + r.trigger)) >= _JACCARD_THRESHOLD:
                return False
    return True
```

### 4.3 Recall with Token Budget（D2-2）

```python
# backend/memory/recall.py
import json, math

def _estimate_tokens(obj) -> int:
    return max(1, len(json.dumps(obj, ensure_ascii=False)) // 4)

def recall(state, context: str, current_tags, token_budget: int = 1500) -> RecalledContext:
    if not is_v2_enabled():
        return _legacy_recall(state)  # phase_summaries[-3:] + memories[-3:]

    budget = token_budget
    # Step 1 semantic：phase_summaries 优先
    semantic = (state.phase_summaries or [])[-3:]
    budget -= sum(_estimate_tokens(s) for s in semantic)

    # Step 2 episodic：加载 life_moments + 动态打分
    moments = store.load_life_moments(state.baby_id)
    ctx_tokens = _tokens(context)
    tags = set(current_tags or ())
    age = state.age_days
    scored = [(m, _score(m, ctx_tokens, tags, age)) for m in moments]
    scored.sort(key=lambda x: -x[1])

    # tag 一跳倒排（D2-3）：从 top-k 扩展同 tag 历史条目
    inverted = _build_tag_index(moments)
    top_k = [m for m, _ in scored[:8]]
    expand = []
    for m in top_k:
        for t in m.cause_tags + m.effect_tags:
            for cand in inverted.get(t, []):
                if cand not in top_k and cand not in expand:
                    expand.append(cand)
                    if len(expand) >= 3: break
            if len(expand) >= 3: break
    episodic = top_k + expand
    # 按 budget 裁剪
    accepted_ep = []
    for m in episodic:
        cost = _estimate_tokens(m)
        if budget - cost < 200: break      # 给 milestone 留余地
        budget -= cost
        accepted_ep.append(m)

    # Step 3 milestone 兜底
    milestones = _relevant_milestones(state, tags, limit=3)
    accepted_ms = []
    for ms in milestones:
        cost = _estimate_tokens(ms)
        if budget - cost < 0: break
        budget -= cost
        accepted_ms.append(ms)

    return RecalledContext(semantic, accepted_ep, accepted_ms, token_budget - budget, token_budget)
```

### 4.4 Forgetting Curve（C7 回补）

```python
# backend/memory/forget_params.py

# Ebbinghaus 指数近似（粗量级，v1 升级为 Wickelgren 幂律）
TAU_BY_PHASE: dict[int, int] = {
    0: 3,    1: 7,    2: 14,   3: 30,   4: 60,   5: 90,
    6: 180,  7: 270,  8: 365,  9: 540, 10: 720, 11: 1080,
}
DEFAULT_TAU = 180

# 新颖性闸门
JACCARD_THRESHOLD = 0.7
LOW_INTENSITY = 0.4

# 剪枝软上限（防失控）
PRUNE_SOFT_CAP = 500
PRUNE_KEEP_TOP = 300

# 灰度
MEMORY_V2_ENV = "MEMORY_V2"            # 值 "on"/"off"；默认 "on"
PHASE_B_SPEC_ID = "phase-b-unify-memory"  # D1-5 预设终结 spec 编号
```

```python
# backend/memory/consolidation.py
import math
from .forget_params import TAU_BY_PHASE, DEFAULT_TAU

def _compute_forget_score(m, current_age_days: int) -> float:
    delta = max(current_age_days - m.age_days, 0)
    tau = TAU_BY_PHASE.get(m.phase, DEFAULT_TAU)
    boost = 1.0 + 0.5 * m.intensity
    return m.intensity * math.exp(-delta / (tau * boost))

def recompute_forget_scores(state, baby_id: str) -> None:
    """遍历所有 life_moments 重算 forget_score，原地更新 jsonl（追加重写方式）。"""
    # 实现略：读 moments → 计算 → 调 store.rewrite_with_forget_scores

def prune_if_needed(state, baby_id: str) -> int:
    """len > PRUNE_SOFT_CAP 时按 forget_score 保留 top PRUNE_KEEP_TOP。软归档（标 archived，不删）。"""
```

### 4.5 Append-Only 状态转移（C8 + D3 C1 回补）

heartbeat initiative 产生时 → 写一条 moment A（`outcome="pending", response=""`）。后续被响应时**不回改 A**，append moment B 带 `companion_seq=A.seq, outcome="responded", actor=responder`。被忽略时同理 append B `outcome="ignored"`。

recall 时按 `companion_seq` 链查询最终状态，`A.outcome="pending"` 本身保持原样——这是 append-only 铁律的直接体现。

### 4.6 四象限测试矩阵（D1-5）

| V2 | memories 有/无 | 预期 |
|---|---|---|
| on | 有旧数据 | 首次调 recall 触发懒重建 life_moments.jsonl；V2 路径正常；state.memories 降级回写保持 |
| on | 无旧数据（新 baby）| life_moments.jsonl 从零生长；state.memories 同步增长；不变量 `len` 相等 |
| off | 有旧数据 | 走 `memories[-3:]` 旧路径；life_moments.jsonl 若已存在则忽略 |
| off | 无旧数据 | 走旧路径，life_moments.jsonl 不创建 |

## 5. 接入点全量清单（C10 回补完整）

| # | 位置 | 改造动作 | 类型 |
|---|---|---|---|
| 1 | `cradle/mind.py:681` | `Memory(...)` + `record_moment(actor="world", target="self", ...)` | passive |
| 2 | `cradle/mind.py:836` | 同上 | passive |
| 3 | `scheduler/story.py:140` | 同上 | passive |
| 4 | `scheduler/handlers.py:320` (turbo 自主事件) | `record_moment(actor="self", ...)` | initiative |
| 5 | `scheduler/handlers.py:460,607` (autonomous_routine/event) | 按场景判定 actor | passive / initiative |
| 6 | `heartbeat.evaluate_heartbeat` 返回 initiative | `record_moment(actor="self", outcome="pending", response="")` | initiative |
| 7 | `heartbeat._check_and_process_ignore` 超时 | **append 新 moment**（不回改 pending）：`record_moment(actor="world", outcome="ignored", companion_seq=orig.seq)` | interaction |
| 8 | `heartbeat.mark_responded` | **append 新 moment**（不回改 pending）：`record_moment(actor=responder, outcome="responded", companion_seq=orig.seq)` | interaction |
| 9 | `initiative_needs.evaluate_need` 触发 | `record_moment(actor="self", trigger=need_trigger)` | initiative |
| 10 | `cradle/conversation.post_parent_message` | `record_moment(actor="caregiver:...", target="self")` | interaction |
| 11 | `cradle/conversation.post_baby_message` | `record_moment(actor="self", target="caregiver:...")` | initiative |
| 12 | `scheduler/handlers.py:694,701` stress_regression / recovery | `Milestone(kind="capability_lost"/"capability_recovered")` | milestone |
| 13 | `scheduler/handlers.py:724,738` capabilities_unlocked / milestones | `Milestone(kind="capability_gained"/"milestone_reached")` | milestone |
| 14 | `scheduler/handlers.py:761,802` phase_completed / cradle_complete | `Milestone(kind="phase_advanced"/"cradle_complete")` | milestone |
| 15 | `scheduler/handlers.py:227,265` critical_expired | `record_moment(outcome="ignored")` + companion_seq 链 | interaction |
| 16 | `scheduler/needs.py:144` need_responded by nanny_fallback | `record_moment(outcome="fallback")` | interaction |
| 17 | `api/cradle.py:382` intervention | `record_moment(actor="caregiver:...")` | interaction |
| 18 | `cradle/nanny.py:1332` heartbeat_initiative / heartbeat_ignored | 同 #6/#7 的手动路径 | initiative |
| 19 | `cradle/mind.py:314,554,757,882` LLM 注入 | `recall(state, context, tags, token_budget=1500)` + `phase_summaries[-3:]`（V2=on） | read |
| 20 | `world.py:557` `experienced = {m.event for m in state.memories}` | V2=on 改读 `life_moments.jsonl`；V2=off 原路径 | read |
| 21 | `world.py:658` snapshot 最近 5 条 memory | 同上 | read |
| 22 | `events/__init__.py:133` 涌现冷却 | 同上 | read |
| 23 | `api/cradle.py:260` `memories_count` | `len(life_moments) if V2 else len(state.memories)` | api |
| 24 | `api/cradle.py:477` /history 返回 memories / phase_summaries | V2=on 从 `life_moments.jsonl` 反向重建兼容 payload | api |
| 25 | `state.py:628` `rebuild_triggered_events` | 双源遍历：优先 life_moments，fallback state.memories（D1-3）| compat |
| 26 | `cradle/nanny.py:1260,1403` | 同 #19 的 nanny 内部路径 | read |
| 27 | `frontend/src/Cradle.jsx:654` `h.phase_summaries` | **不改前端**——/history 端点兼容 payload 保持 `phase_summaries` 字段 | compat |

## 6. 已归档 spec 兼容矩阵（C11 回补）

| Spec | 真实依赖 | V2=off | V2=on | 策略 |
|---|---|---|---|---|
| `interaction/requirements.md:49` | "include the most recent 3 memories from `state.memories`" | 原路径 state.memories[-3:] | **state.memories 由降级回写保持完整**（D1-2），原契约仍成立 | 不破坏契约，不改 interaction spec |
| `causal-graph/tasks.md:54` rebuild_all_tags | 遍历 `state.memories` 逐条打 tag | 原路径 | 双源遍历（life_moments ∪ state.memories 去重），保证覆盖（D1-3） | 扩展 rebuild 函数，不改 spec |
| `world-context/*` | `world.py:557,658` 读 state.memories | 原路径 | 切到读 life_moments.jsonl（#20/#21）| 不破坏 spec，行为一致 |
| `autonomous-life/specs/agent-state.md:12` | BabyState.memories 字段存在性 | 存在 ✓ | 存在 ✓（未删） | 零影响（C3） |
| `cradle-enhancement` | phase_summaries 存在 | 存在 ✓ | 存在 ✓（未迁移） | 零影响（C6） |
| 前端 `Cradle.jsx:654` | `h.phase_summaries` | 原路径 | /history 兼容 payload 保持该字段（#24） | 零前端改动 |

## 7. 双写策略（D1-1/D1-2/D1-4）

```python
# 写顺序约定（design doc 也作为启动自检依据）
# Step 1: store.append_life_moment(baby_id, moment)      # → life_moments.jsonl
# Step 2: state.memories.append(_downgrade_to_memory)    # → BabyState 内存
# Step 3: save_state(baby_id, state)                     # → state.json 原子写

# 崩溃恢复语义：
# - Step 1 完成、Step 3 未完成：jsonl 有新 moment，state.json 无对应 memory
#   → 启动自检：scan life_moments.jsonl 最后 N 条，若 seq > state 侧任何 memory 推断的最大 seq，
#     则追加 downgrade 到 state.memories 并 save（幂等修复）
# - Step 1 未完成：一致，什么都没发生
# - Step 3 完成但 Step 1 未完成：不可能（顺序约定强制）
```

### CI 静态检查（D1-1）

`scripts/lint_no_direct_memory_append.py`：ast-grep 或纯 AST 扫描，禁止 `state.memories.append(` 调用点（仅允许出现在 `backend/memory/ingest.py` 的 `record_moment` 内）。CI 红灯阻断 merge。

### 不变量断言（D1 强制前提）

```python
# 调用点：每次 save_state 前 + 测试环境每次 record_moment 后
assert len(state.memories) == store.count_life_moments(baby_id, exclude_kind=None), \
    "memories/life_moments 数量不变（违反 D1-2 降级回写）"
```

## 8. 性能估算

| 操作 | 实测预期 | 复杂度 |
|---|---|---|
| record_moment（含 Jaccard 闸门）| < 3ms | O(recent_window × token_size) |
| recall（N=1000 moments）| < 20ms | O(N) Jaccard + tag 倒排内存 dict |
| recompute_forget_scores（N=1000）| < 5ms | O(N) 纯算术 |
| prune_if_needed | < 5ms | O(N log N) |
| 启动自检 | < 50ms | O(N) 扫 jsonl 尾部 |

纯 Python 纯 IO，无 asyncio 阻塞风险。

## 9. 分形同构检查

- **L1** `backend/CLAUDE.md`：目录清单新增 `memory/`
- **L2** `backend/memory/CLAUDE.md`：成员清单 / 对外暴露 / 依赖关系 / 数据流 / `[PROTOCOL]`
- **L3** 所有新 `.py` 头部 `[INPUT] / [OUTPUT] / [POS] / [PROTOCOL]`
- `cradle/CLAUDE.md`：`mind.py`、`nanny.py` 增加对 `memory/` 的说明
- `scheduler/CLAUDE.md`（若存在）：增加接入点 #4/#5/#12-#16 说明
- `heartbeat` / `initiative_needs` 顶部 L3 更新（OUTPUT 新增 record_moment 调用）

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 静默遗失（V2=on 写 moment 未同步 state.memories）| record_moment 内强制双写 + 不变量断言 + CI 静态检查 |
| 接入点漏改（27 处全靠人工）| CI 禁 `state.memories.append` + 不变量 assertion 运行时捕获 |
| 崩溃半成功 | 写顺序约定 + 启动自检幂等修复 |
| `MEMORY_V2` 成永久技术债 | 预设 `phase-b-unify-memory` 终结 spec id 写入 forget_params.py，并在 proposal §阶段 B 触发条件约束 |
| jsonl 并发写 | 复用 `state.py:40-65` 的 threading.Lock + seq 基础设施 |
| Jaccard 闸门过滤掉真实重要事件 | 高强度/首触/caregiver 参与三重强制入库白名单 |
| 迁移期老 baby 无 life_moments.jsonl | 首次 recall 懒重建（从 state.memories 全量转 passive LifeMoment），幂等 |

## 11. 开关与终结

- **默认值**：`MEMORY_V2=on`（阶段 A 全量启用新路径；旧代码回退靠设为 `off`）
- **回退条件**：CI 不变量红灯 / 四象限测试任意失败 → 立即 `MEMORY_V2=off` 并紧急发布，life_moments.jsonl 保留不删
- **终结路径**：阶段 B spec（`phase-b-unify-memory`）满足触发条件（见 proposal.md）后接管，本 spec 的 V2 开关和 state.memories 双写才可移除
