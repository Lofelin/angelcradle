# 架构重设计草案：LifeMoment 统一生命经验原子

> ⚠️ 本文是**待评审草案**，非最终设计。由多 agent 严审后决定是否落地。
> 上游背景：`proposal.md`（Phase 0）被评估为治标不治本，用户授权推翻现架构。

## 动机

当前"生命体经验"相关数据散落在至少 7 个不相交位置，没有统一原子：

| 位置 | 存什么 | 创建点 | 被消费路径 |
|---|---|---|---|
| `state.memories: list[Memory]` | 被动经验 | `scheduler/story.py:140` / `mind.py:681,836`（仅 3 处）| `mind.py` 注入取 `[-3:]` |
| `state.phase_summaries: list[dict]` | 阶段要点 | `mind.generate_phase_summary` | 几乎未读取 |
| `state.triggered_events: set[str]` | 全局去重集合 | event rolling | event rolling |
| `state.initiative: InitiativeState` | 主动行为**计数+pending** | `heartbeat.py` / `initiative_needs.py` | 频率门、忽略升级 |
| `state.caregivers: dict[CaregiverProfile]` | 关系画像 | nanny 更新 | LLM prompt |
| `events.jsonl` | 时间真相全集 | 到处 | lifeline SSE 回放 |
| `cradle_graph` 六层 KG | 因果图节点/边 | `cradle_graph_store.save_*` | **零读取** |

### 根本问题

1. **主动行为不进记忆**：`Memory()` 只在 3 处创建，`heartbeat.evaluate_heartbeat` / `initiative_needs.evaluate_need` / `conversation.post_baby_message` 成功触发时**不写 Memory**。Baby 不会"记得自己做过什么"。
2. **Memory 字段假设了被动模式**：`stimulus / reaction` 语义硬编码单向（世界→我）。主动行为是反向的（我→世界），强塞进去会扭曲语义。
3. **phase_summaries 和 Memory 并列而非分层**：两者都是"生命经验"，一个是 episodic 一个是 synthesis，却分列存储不互通。
4. **cradle_graph 是第二套记忆但不同步**：写入有路径、读取无消费者，是投资未收回的固定资产。
5. **events.jsonl 是真相但不是记忆**：含脚手架事件（`loading`/`extracting`/`phase_start`/`capabilities_unlocked`），不适合作为检索源；但选什么升格为记忆没有明确规则。

## 核心设计：`LifeMoment` 统一原子

### 数据模型

```python
@dataclass
class LifeMoment:
    # 身份
    id: int                     # 自增主键（单 baby 单序列）
    kind: str                   # 4 选 1，见下
    source_seq: int | None      # events.jsonl 反查链接（若有对应 event）

    # 时空
    phase: int
    age_days: int
    sim_time: float

    # 当事人
    actor: str                  # "world" / "self" / caregiver_id
    involves: list[str]         # 涉及的其他 actor，默认空

    # 内容
    trigger: str                # 事件名 / need trigger / caregiver action key
    content: str                # 自然语言描述（what happened，≤ 200 字）
    outcome: str                # "neutral" / "responded" / "ignored" / "succeeded" / "failed"

    # 感受
    valence: str                # positive / negative / neutral
    intensity: float            # 0..1

    # 语义标签（复用 causality.py 已有产物）
    tags: list[str]             # ["cause:fear:stranger", "effect:attachment:anxious", ...]

    # 遗忘
    forget_score: float = 1.0

    # kind 选填段（用 "" 表示不适用，不使用 Optional 减少分支）
    # kind=passive_experience
    stimulus: str = ""          # 世界刺激描述
    reaction: str = ""          # 婴儿反应
    # kind=self_initiative
    self_intent: str = ""       # 内心意图
    world_response: str = ""    # 世界回应（空字符串表示被忽略）
    # kind=interaction 共享 stimulus+reaction 语义
    # kind=synthesis 共享 content 字段表达要点
```

### 4 种 kind 语义

| kind | 语义 | 当前对应 | 新创建点 |
|---|---|---|---|
| `passive_experience` | 世界刺激 → 婴儿反应 | `state.memories` 全量 | `nanny.py` / `mind.py:681,836` / `scheduler/story.py:140` |
| `self_initiative` | 婴儿意图 → 行动 → 世界回应 | **当前完全缺失** | `heartbeat.py` LLM 产出 initiative 时 / `initiative_needs.py` 成功触发时 / `conversation.post_baby_message` |
| `interaction` | 多方对话/照护/关键事件 | 散落在 `critical_event` / 对话 | `conversation.post_parent_message` / `mind.process_critical_event` |
| `synthesis` | 压缩态：阶段总结、性格凝结 | `state.phase_summaries` 全量 | `mind.generate_phase_summary` / 未来可扩展 trait 凝结 |

### 存储

```
archive/{baby_id}/
├── state.json              # 不再含 memories / phase_summaries（迁移后）
├── events.jsonl            # 保持不变（时间真相）
├── life_moments.jsonl      # 【新增】LifeMoment 流（append-only，seq 同步递增）
├── causal_graph.json       # 子宫期（不动）
└── cradle_graph/...        # 摇篮期六层图（节点改引 life_moment.id，见 §集成）
```

无 SQLite、无嵌入。检索仍用 Jaccard + tags + `intensity × exp(-Δ/τ)`，与 Phase 0 相同公式。

### 统一检索接口

```python
def recall(
    state,
    context: str,
    current_tags: set[str],
    kinds: set[str] | None = None,    # 过滤 kind
    k: int = 8,
) -> list[LifeMoment]:
    """
    对所有 LifeMoment 按 Jaccard(content)+tags_overlap+forget_score 排序，返 top-k。
    默认返回所有 kind 混合；需要分组呈现由调用方拆。
    """
```

`mind.py` 三入口：
```python
semantic = recall(state, context, tags, kinds={"synthesis"}, k=3)
episodic = recall(state, context, tags, kinds={"passive_experience", "self_initiative", "interaction"}, k=8)
```

### 与 `cradle_graph` 的关系

改造为**视图层**：
- 节点：保留类型（`phase` / `capability` / `milestone` / `event` / `caregiver`），但 `event` 类节点改存 `life_moment_id` 而非嵌入事件快照
- 边：保留因果关系
- 新增 `query_associative(tags, hops=2) -> list[life_moment_id]`（Phase 0 推迟的 API 在这里回归）

好处：`cradle_graph` 从"第二套记忆"退化为"LifeMoment 之上的关系网络"，消除双源不同步问题。

### 迁移路径（破坏性，但明确）

**一次性迁移脚本** `scripts/migrate_to_life_moments.py`：

```python
# 1. 遍历 archive/{baby_id}/：
for baby_dir in archive_dirs:
    state = load_state_raw(baby_dir)  # 原 state.memories / phase_summaries 仍在
    moments = []

    # 2. state.memories → passive_experience
    for m in state.get("memories", []):
        moments.append(LifeMoment(
            id=next_id,
            kind="passive_experience",
            phase=m["phase"], age_days=m["age_days"],
            actor="world", involves=[],
            trigger=m["event"], content=f"{m['stimulus']} → {m['reaction']}",
            outcome="responded" if m.get("parent_involved") else "neutral",
            valence=m["emotional_valence"], intensity=m["intensity"],
            tags=split_trace_to_tags(m.get("trace", "")),
            forget_score=m.get("forget_score", 1.0),
            stimulus=m["stimulus"], reaction=m["reaction"],
        ))

    # 3. state.phase_summaries → synthesis
    for s in state.get("phase_summaries", []):
        moments.append(LifeMoment(
            id=next_id, kind="synthesis",
            phase=s.get("phase", 0), age_days=s.get("age_days", 0),
            actor="world", involves=[],
            trigger="phase_summary", content=s.get("summary", ""),
            outcome="neutral", valence="neutral", intensity=0.7,
            tags=[],
        ))

    # 4. 原字段从 state.json 中移除；写 life_moments.jsonl
    state["schema_version"] = 2
    del state["memories"]
    del state["phase_summaries"]
    save_state(baby_dir, state)
    save_life_moments(baby_dir, moments)
```

老代码一次性作废。若想要灰度，可保留 `state.memories` 字段但标记 `deprecated`，读代码不再走它。

### 集成接入点全量清单

| # | 旧行为 | 新行为 |
|---|---|---|
| 1 | `scheduler/story.py:140` `Memory(...)` → `state.memories.append` | `create_moment(kind="passive_experience", ...)` → append life_moments.jsonl |
| 2 | `mind.py:681` 同上 | 同上 |
| 3 | `mind.py:836` 同上 | 同上 |
| 4 | `heartbeat.evaluate_heartbeat` 返回 initiative **不写记忆** | 新增 `create_moment(kind="self_initiative", self_intent=..., world_response="")` |
| 5 | `heartbeat._check_and_process_ignore` 超时忽略 **不写记忆** | `create_moment(kind="self_initiative", outcome="ignored", world_response="")` |
| 6 | `heartbeat.mark_responded` **不写记忆** | 修改最近一条 pending moment 的 `world_response` 字段并 `outcome="responded"` |
| 7 | `initiative_needs.evaluate_need` **不写记忆** | `create_moment(kind="self_initiative", trigger=need_trigger)` |
| 8 | `conversation.post_baby_message` **不写记忆** | `create_moment(kind="self_initiative" 或 "interaction")` |
| 9 | `conversation.post_parent_message` **不写记忆** | `create_moment(kind="interaction")` |
| 10 | `mind.generate_phase_summary` → `state.phase_summaries.append` | `create_moment(kind="synthesis")` |
| 11 | `mind.py` 三入口 memory 注入 `state.memories[-3:]` | `recall(..., k=8)` 混合 kind |
| 12 | `cradle_graph_store` event 节点存快照 | 改存 `life_moment_id` 引用 |
| 13 | `lifeline` SSE 消费 events.jsonl（含旧 schema 的 memory 字段？需查证）| 保持 events.jsonl 完整；life_moments.jsonl 不推 SSE（可选） |

### 保留字段（与 LifeMoment 正交，不迁移）

- `InitiativeState`：频率计数、pending 流水号——**纯控制流**，保留
- `state.triggered_events: set[str]`：纯去重集合——保留
- `state.caregivers`：关系画像累计——保留（但 caregiver 相关的具体互动瞬间由 `kind=interaction` 的 LifeMoment 承担）
- `state.stress_state / emotional_state / physical_state / nutrition_sleep_state`：当前快照，不是记忆——保留

## 风险清单（待评审回答）

1. **LifeMoment 字段选填段是否破坏好品味**：按 kind 填不同字段，本质是"存在特殊情况"。能不能用更统一的结构（比如 `context_before / action / context_after` 三元组）消除分支？
2. **迁移脚本真实风险**：现有 2 个 baby 的 state.json 结构不同（14226 无 state.json），迁移必须幂等；回滚方案是什么？
3. **前端兼容性**：lifeline SSE 是否依赖 `state.memories` 或 `phase_summaries` 的任何结构？需要全量 grep 前端代码。
4. **与 Phase 0 的关系**：Phase 0 的 `forget_score + Jaccard recall` 是否可以直接复用到 LifeMoment？迁移时是否需要保留 Phase 0 字段含义？
5. **cradle_graph 改造成本**：现有 save_phase/save_event/save_critical/save_caregiver 多个写入路径，如何一致切换到"存 id 不存快照"？
6. **未来扩展（世界层）**：LifeMoment 能否容纳跨 baby 社交（两个 baby 同一场景各记一次）？`actor / involves` 是否足够？
7. **成本**：3-5 天工作量，破坏性迁移，是否值得？如果 `kind=self_initiative` 单独补到 Memory 就能满足 80% 收益，统一原子是否过度？（反方论点）

## 评审请求

5 个 agent 并行评审：
- ① 架构严肃性（消除特殊情况 vs 按 kind 选填）
- ② 字段与数据模型自洽
- ③ 迁移与向后兼容
- ④ 领域覆盖完整性（能否真正替代 7 处碎片）
- ⑤ 反方视角（LifeMoment 是否为过度设计）
