# 收敛候选方案：LifeMoment 统一原子（无 kind 字段版）

> 本文**不是新方案**。它是三轮（共 11 个 agent 视角）评审的共识整合，加上用户场景验证后的收敛版。
> 本轮 agent 评审不得再提出新的替代方案，只做三件事：①判重构/更新、②判 Omni-SimpleMem 对齐、③核对共识是否被完整继承。

## Part 1 · 三轮评审共识矩阵（不容置疑的基线）

### ✅ 五方共识（所有评审 agent 都同意）

| # | 共识 | 来自 |
|---|---|---|
| C1 | 主动行为不进记忆是**真问题**（heartbeat / need / post_baby_message 全部不写 Memory） | 所有评审 + 用户 |
| C2 | 不引入 SQLite / 不引入嵌入模型（sentence-transformers）——Phase 0 精神 | 第 1 轮 5 方 + 第 2 轮反方 |
| C3 | **严禁破坏性一次性迁移**（`del state["memories"]`）——违反向后兼容铁律 | 第 2 轮 ③迁移 + ⑤反方 |
| C4 | **严禁重新发明 tags**——必须严格复用 `causality.generate_cause_tags` / `generate_effect_tags`（格式 `"stress:+0.15"` / `"attachment:toward_secure"`）| 第 2 轮 ②数据模型 |
| C5 | `cradle_graph` 当前是**零读取**写入器，改造它属伪收益——先不碰 | 第 1 轮 Linus + 第 2 轮 ⑤反方 |
| C6 | `phase_summaries` 已是现成的 semantic 层（`state.py:469`，`mind.py:882` 已用），**保持独立**不塞进统一原子 | 第 2 轮 ①好品味 + ②数据模型 + ⑤反方 |
| C7 | `forget_score = intensity × exp(-Δ/τ)` 公式够用；`TAU_BY_PHASE` 粗量级即可，v1 再做神经科学精调 | 第 1 轮 科学 + 第 1 轮 Linus |
| C8 | **append-only**：状态变化（如 pending → responded）必须 append 新条目带 `companion_seq` 链，不得回改历史 | 第 2 轮 ①好品味 |
| C9 | Milestone 类（`capabilities_unlocked` / `stress_regression` / `regression_recovery` / `first_X` / `phase_advance`）是**真实遗漏**，必须单独 dataclass | 第 2 轮 ④领域 |
| C10 | 接入点清单必须**全量覆盖**：`world.py:557,658` / `events/__init__.py:133` / `api/cradle.py:260,477` / `Cradle.jsx:654` / `rebuild_triggered_events` / nanny / mind / heartbeat_provider / scheduler/story / scheduler/handlers / scheduler/needs | 第 2 轮 ③迁移 |
| C11 | 已归档 spec（`interaction` / `world-context` / `causal-graph` / `autonomous-life`）假设 `state.memories` 存在——若改 schema 必须同步声明作废或迁移契约 | 第 2 轮 ③迁移 |

### 🎯 用户场景验证（2026-04-17）

用户提出："今天找了妈妈讨论要不要上学"。

这件事同时是 initiative（self 发起）+ interaction（妈妈参与）+ 可能 milestone（人生决策），**用任何单一 `kind` 字段或 dataclass 分类都会撕裂**。

→ 直接否决了 Phase 0.5 的 `Memory + Initiative + Milestone` 三 dataclass 并列方案（反方派）。
→ 回到第 2 轮 ①好品味 agent 的 B 判决：**统一原子 + 用字段维度区分 + 不要 kind 分支**。

### ⚖️ 未决问题（本轮 agent 裁决）

- **D1**：统一原子是"重构"还是"更新"？旧 `Memory` 是废弃还是演化？
- **D2**：本方案是否真的符合 Omni-SimpleMem 长期记忆系统的核心哲学（MAU / Selective Ingestion / Progressive Retrieval / KG / 分层）？
- **D3**：三轮评审共识是否被当前方案**完整继承**？有没有悄悄丢掉关键建议？

## Part 2 · 收敛后的最终候选

### 2.1 数据模型（来自第 2 轮 ①好品味 + 用户场景验证）

```python
# 事件型原子（瞬时发生的一段经历）
@dataclass
class LifeMoment:
    # 身份
    seq: int                          # 单 baby 单序列，复用 state.py 的 _get_seq_lock 基础设施
    source_seq: int = -1              # events.jsonl 反查；-1 表示无对应 event

    # 时空
    phase: int = 0
    age_days: int = 0
    sim_time: float = 0.0

    # 当事人（无 kind，用 actor/target 组合推断事件类型）
    actor: str = "world"              # "world" / "self" / f"caregiver:{stable_key}"
    target: str = ""                  # 同格式；"" 表示无特定对象
    witnesses: list[str] = field(default_factory=list)

    # 内容（统一自然语言，不按 kind 分字段）
    trigger: str = ""                 # 事件名 / need trigger / action key
    action: str = ""                  # what happened（≤ 120 字）
    response: str = ""                # 对方回应；"" 表示无回应或被忽略
    outcome: str = "neutral"          # responded / ignored / succeeded / failed / neutral
    companion_seq: int = -1           # 链接到后续响应 moment 的 seq（append-only 状态转移）

    # 感受
    valence: str = "neutral"          # positive / negative / neutral
    intensity: float = 0.5

    # 标签（严格复用 causality.py 产出，不重新发明）
    cause_tags: list[str] = field(default_factory=list)
    effect_tags: list[str] = field(default_factory=list)

    # 首触标记（第 2 轮 ④领域 agent）
    is_first: bool = False

    # 遗忘（recall 时动态计算，可选持久化作 cache）
    forget_score: float = 1.0

# 里程碑型原子（能力变化、阶段节点、首触）——时间语义不同，独立存储
@dataclass
class Milestone:
    seq: int
    phase: int
    age_days: int
    sim_time: float
    kind: str                         # capability_gained / capability_lost / capability_recovered
                                      # / milestone_reached / first_X / phase_advanced / cradle_complete
    subject: str                      # 能力名 / milestone 名 / first_X 事件名
    description: str
    intensity: float = 0.8            # 里程碑天然高权重
    tags: list[str] = field(default_factory=list)

# 阶段总结（跨时段压缩态，不是事件）——保持独立 dataclass，不迁移
# 继续使用现有 state.phase_summaries: list[dict]，from_dict 不动
```

### 2.2 "找妈妈讨论上学" 场景的装载示意

```python
LifeMoment(
    seq=42,
    actor="self",                          # 主动发起信号
    target="caregiver:mom",                # 讨论对象
    witnesses=[],
    trigger="life_decision_discussion",
    action="提出想和妈妈聊要不要上学",
    response="妈妈列了上学和不上学的各自好处",
    outcome="responded",
    valence="positive",
    intensity=0.75,
    cause_tags=["attachment:seek_guidance"],
    effect_tags=["cognitive:decision_forming"],
    is_first=True,                         # 首次主动发起决策讨论
)
```

同一事件由 `actor/target/response/outcome` 四个字段完整表达 initiative + interaction + decision 三重语义，**无 kind 分支**。

### 2.3 覆盖四种边界场景

| 场景 | actor | target | response | outcome |
|---|---|---|---|---|
| 被妈妈抱 | caregiver:mom | self | 我靠在她肩上 | responded |
| **找妈妈讨论上学** | **self** | **caregiver:mom** | **妈妈列利弊** | **responded** |
| 一个人玩积木 | self | "" | "" | succeeded |
| 雷声吓哭 | world | self | 我抱头哭 | neutral |
| 主动求抱被忽略 | self | caregiver:mom | "" | ignored |

### 2.4 存储

```
archive/{baby_id}/
├── state.json              # 保留 memories/phase_summaries 字段（双写期）
├── events.jsonl            # 不变
├── life_moments.jsonl      # 【新增】append-only LifeMoment 流
├── milestones.jsonl        # 【新增】append-only Milestone 流
├── causal_graph.json       # 子宫期，不动
└── cradle_graph/           # 摇篮期六层图，本阶段不改造（C5）
```

### 2.5 迁移策略（**双写灰度，不做破坏性迁移**）

**阶段 A（本 spec 范围）**：
- 新增 LifeMoment / Milestone 追加写入（新代码写两份：旧的 `state.memories.append` + 新的 `life_moments.jsonl`）
- 读路径通过 `MEMORY_V2=on` 环境变量切换：on 走 `life_moments.jsonl`，off 走 `state.memories`
- **旧数据可选懒重建**：首次读 `life_moments.jsonl` 不存在时，从 `state.memories` 和 `state.phase_summaries` 懒生成一份，写回文件，后续不再转换
- `state.memories` / `state.phase_summaries` schema **不删不改**（C3 铁律）
- 已完成 spec 的契约不破坏（C11）

**阶段 B（未来 spec，不在本次）**：
- 双写观察 ≥ 2 周，读路径确认无异常
- 起新 spec change 决定是否停止旧写路径

### 2.6 统一检索

```python
def recall(
    state,
    context: str,
    current_tags: set[str],
    k: int = 8,
) -> RecalledContext:
    """
    统一检索 LifeMoment（无 kind 过滤——一件事就是一件事）+ Milestone（里程碑）。
    phase_summaries 独立调用，不混进来。
    """
    return RecalledContext(
        moments=_top_k_moments(state, context, current_tags, k),
        milestones=_relevant_milestones(state, current_tags, k=3),
    )
```

`mind.py` 三入口：
```python
rc = recall(state, context, current_tags, k=8)
semantic = state.phase_summaries[-3:]    # 独立读，不混
prompt_memory = render(semantic, rc.moments, rc.milestones)
```

### 2.7 接入点（全量覆盖 C10）

| # | 位置 | 新行为 |
|---|---|---|
| 1 | `cradle/mind.py:681` | 原 `Memory(...)` + `life_moments.append(LifeMoment(actor="world", target="self", ...))` |
| 2 | `cradle/mind.py:836` | 同上 |
| 3 | `scheduler/story.py:140` | 同上 |
| 4 | `scheduler/handlers.py:320` (turbo 自主事件) | 新增 LifeMoment 写入 |
| 5 | `scheduler/handlers.py:460,607` (autonomous_routine/event) | 同上 |
| 6 | `heartbeat.evaluate_heartbeat` 产出 initiative 成功分支 | `LifeMoment(actor="self", outcome="pending", response="", companion_seq=-1)` |
| 7 | `heartbeat._check_and_process_ignore` 超时 | append 新 `LifeMoment(actor="world", ..., companion_seq=orig.seq, outcome="ignored")`（不回改）|
| 8 | `heartbeat.mark_responded` | append 新 `LifeMoment(actor=responder, companion_seq=orig.seq, outcome="responded")` |
| 9 | `initiative_needs.evaluate_need` 触发 | `LifeMoment(actor="self", trigger=need_trigger)` |
| 10 | `cradle/conversation.post_parent_message` | `LifeMoment(actor="caregiver:...", target="self")` |
| 11 | `cradle/conversation.post_baby_message` | `LifeMoment(actor="self", ...)` |
| 12 | `scheduler/handlers.py:694,701` stress_regression / recovery | **Milestone** 写入 |
| 13 | `scheduler/handlers.py:724,738` capabilities_unlocked / milestones | **Milestone** 写入 |
| 14 | `scheduler/handlers.py:761,802` phase_completed / cradle_complete | **Milestone** 写入（phase_advanced / cradle_complete）|
| 15 | `scheduler/handlers.py:227,265` critical_expired | LifeMoment `outcome="ignored"` |
| 16 | `scheduler/needs.py:144` need_responded by nanny_fallback | LifeMoment `outcome="fallback"` |
| 17 | `api/cradle.py:382` intervention | LifeMoment `actor="caregiver:..."` |
| 18 | `cradle/nanny.py:1332` heartbeat_initiative / heartbeat_ignored | 同 #6/#7 |
| 19 | `mind.py:314 / 554 / 757 / 882` | 注入改 `recall()` + `phase_summaries[-3:]`（V2=on） |
| 20 | `world.py:557` `experienced = ...` | 改读 `life_moments.jsonl` |
| 21 | `world.py:658` snapshot 最近 5 条 memory | 同上 |
| 22 | `events/__init__.py:133` 涌现冷却 | 同上 |
| 23 | `api/cradle.py:260` memories_count | 兼容：返回 `len(life_moments) if V2 else len(state.memories)` |
| 24 | `api/cradle.py:477` /history 返回 memories/phase_summaries | 兼容：V2 时从 `life_moments.jsonl` 反向重建兼容 payload |
| 25 | `state.py:628` rebuild_triggered_events | V2 时从 `life_moments.jsonl` 重建 |
| 26 | `cradle/nanny.py:1260,1403` | 同 #19 |

## Part 3 · 本轮 agent 评审请求

### 决策 D1：重构 vs 更新？

本方案保留 `Memory` dataclass 不删，但新增 `LifeMoment` 作为**读路径的主源**，旧 Memory 进入"双写观察期"。

- 若视为**更新**（evolve）：Memory 仍在，只是逐步让路给 LifeMoment
- 若视为**重构**（rebuild）：统一原子 + 无 kind 字段本质是数据模型重新设计

本轮 agent ①回答：这个判断对不对？边界是什么？如果定义为重构，双写灰度策略是否真的守住"非破坏性"铁律？

### 决策 D2：是否对齐 Omni-SimpleMem？

Omni-SimpleMem 核心组件：
- MAU（多模态原子单元）
- Selective Ingestion（新颖性过滤）
- Progressive Retrieval（pyramid: summary → full → raw）
- Hot/Cold tiering
- Knowledge Graph + multi-hop

本方案：
- ✅ LifeMoment = **原子单元**（神似 MAU，但非多模态）
- ⏸ **无 Selective Ingestion 闸门**（全量入库，recall 时排序）
- ✅ **三层检索**：`phase_summaries`（semantic 压缩）→ `LifeMoment`（episodic 原子）→ `events.jsonl`（sensory 全量）
- ✅ **Hot/Cold**：moments.jsonl 是 hot（近期可检索），events.jsonl 是 cold（追溯时读）
- ⏸ **无 KG 查询**（`cradle_graph` 延后，Phase 0 精神）

本轮 agent ②回答：本方案的本土化简化（省 embedding/省 KG 查/省 selective 闸门）是**合理实用主义**还是**丢失了长期记忆系统的核心价值**？

### 决策 D3：三轮共识是否被完整继承？

Part 1 列出的 11 条共识（C1~C11）是否在 Part 2 方案中被明确兑现？

本轮 agent ③回答：逐条核对，找出漏项或暗改。
