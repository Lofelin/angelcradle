# 变更提案：生命体长期记忆系统（LifeMoment 统一原子 · 阶段 A）

> 三轮评审（11 agent）+ 用户场景验证后的最终提案。
> 评审过程档案：`reviews/`（ARCHITECTURE-DRAFT + CANDIDATE-FINAL）
> v1 大方案已归档：`v1-deferred/`（证据触发后再启）

## 动机

### 现状的根本问题

"生命体经验"相关数据当前散落在至少 7 个不相交位置，没有统一原子概念：

| 位置 | 存什么 | 读取消费者 |
|---|---|---|
| `state.memories: list[Memory]` | 被动经验 | `mind.py` 取 `[-3:]` |
| `state.phase_summaries: list[dict]` | 阶段要点 | `Cradle.jsx:654` / 几乎未被 LLM 消费 |
| `state.triggered_events: set[str]` | 全局去重 | event rolling |
| `state.initiative: InitiativeState` | 主动行为**仅计数** | 频率门、忽略升级 |
| `state.caregivers` | 关系画像 | LLM prompt |
| `events.jsonl` | 时间真相全集 | lifeline SSE |
| `cradle_graph` | 六层因果图 | **零读取** |

### 三个真实缺陷（第 1 / 2 轮评审证实）

1. **主动行为不进记忆**：`Memory()` 全项目只在 3 处创建（`scheduler/story.py:140` / `mind.py:681,836`）。`heartbeat.evaluate_heartbeat` / `initiative_needs.evaluate_need` / `conversation.post_baby_message` 成功触发时均**不写 Memory**。Baby 不会"记得自己做过什么"——self-model 数据源为零。
2. **Memory 字段假设被动模式**：`stimulus/reaction` 语义硬编码单向（世界→我）。主动行为是反向的（我→世界），硬塞会扭曲语义（用户场景"找妈妈讨论上学"直接证明）。
3. **phase_summaries 和 Memory 并列而非分层**：都是"生命经验"不同尺度的表达，却分列存储不互通；`mind.py` 注入仅读 Memory 近 3 条，phase_summaries 几乎从未被 LLM 消费。

### Omni-SimpleMem 的参考价值（D2 评审）

[Omni-SimpleMem 论文](https://huggingface.co/papers/2604.01007) 的 5 核心组件：MAU / Selective Ingestion / Progressive Retrieval / Hot-Cold Tiering / Knowledge Graph。本提案**合理本土化**保留其架构哲学——**统一原子 + 分层检索 + 生物同构**——但不引入嵌入/SQLite/向量索引（当前单 baby 千条级规模不需要）。

## 目标

- **架构**：用统一原子 `LifeMoment` 替换当前碎片化的记忆分布；**无 `kind` 字段**，用字段维度（actor/target/response/outcome）自然区分事件类型——任一真实事件可完整装载
- **覆盖**：通过 **27 个明确的接入点**确保所有"生命经验"（被动/主动/互动/里程碑）进入统一记忆
- **读路径**：`recall()` 统一接口，**token_budget 感知**的渐进式检索；phase_summaries 作为独立 semantic 层
- **安全**：**双写灰度**（新代码同时写 state.memories + life_moments.jsonl，V2=on 强制降级回写守住旧 spec 契约）+ CI 静态检查防漏改
- **本土化 Omni-SimpleMem**：text-Jaccard 新颖性闸门 + token_budget + tag 一跳倒排，保留长期记忆系统的读写两端预算控制灵魂
- **生物同构**：forget_score 遗忘曲线 + 睡眠触发巩固 + 情感 boost（粗量级，v1 再做神经科学精调）

## 范围

### 包含（阶段 A）

- **新 dataclass**：`LifeMoment`（17 字段无 kind）+ `Milestone`（独立，能力变化/首触/阶段节点）
- **新模块**：`backend/memory/`（L2，包含 store / recall / ingest / consolidation / forget_params / embedder-free）
- **新存储**：`archive/{baby_id}/life_moments.jsonl` + `milestones.jsonl`（append-only，复用 `state.py` seq 锁基础设施）
- **27 个接入点改造**（见 design.md §接入点）：nanny / mind / scheduler/\* / heartbeat / initiative_needs / conversation / world / events / api / 前端 Cradle.jsx
- **读路径**：`recall(state, context, tags, token_budget=1500) -> RecalledContext`，`mind.py` 三入口接入
- **双写灰度**：`MEMORY_V2` 环境变量 + `record_moment()` 单写入口（封装 state.memories 降级回写）
- **新颖性闸门**（D2 补强）：Jaccard > 0.7 且 intensity < 0.4 时丢弃；高强度/首触/caregiver 参与强制入库
- **token_budget 渐进裁剪**（D2 补强）：按 `len(json.dumps)//4` 近似累加；phase_summaries 优先 → moments 次之 → milestones 兜底
- **tag 倒排一跳**（D2 补强）：内存 dict，按 cause/effect_tags 反查补 1-3 条（`cradle_graph` 仍不碰）
- **忘记巩固**：`recompute_forget_scores` + `prune_if_needed` 在睡眠事件触发
- **兼容矩阵**（C11）：显式声明与 `interaction` / `world-context` / `causal-graph` / `autonomous-life` 四个已归档 spec 的继续兼容策略

### 不包含（阶段 B，新 spec 触发）

- 停止向 `state.memories` 写入（当前**必须继续写**守 interaction 契约）
- 删除 `state.memories` / `state.phase_summaries` 字段
- 向量嵌入 / sentence-transformers / SQLite
- `cradle_graph_store.query_associative` 多跳查询（待真实下游消费者出现）
- `MEMORY_V2` 开关移除（预设终结 spec `phase-b-unify-memory`）
- 神经科学精调（REM/SWS 区分 / Wickelgren 幂律 / arousal-valence 拆分）

## 成功标准

- **功能**：27 个接入点全部改造完成；主动行为（heartbeat/need/post_baby_message）产生可检索的 LifeMoment
- **兼容**：`MEMORY_V2=off` 时系统行为完全等同改造前；`interaction` 等已归档 spec 契约（如 "include the most recent 3 memories from `state.memories`"）在两种模式下均成立
- **不变量**：任意时刻 `len(state.memories) == len(non-synthesis LifeMoments)`（CI assertion）
- **性能**：recall with N=1000 moments 耗时 < 20ms；新颖性闸门过滤率 > 20%（防噪声膨胀）
- **观测**：四象限测试矩阵（V2=on/off × memories 有/无）全绿
- **零新依赖**：`pyproject.toml` 不变
- **零破坏性迁移**：`state.memories` / `state.phase_summaries` schema 不删不改

## 非目标（明确拒绝）

- **不做**立即废弃 Memory——留给阶段 B spec 在数据充分后决定
- **不做**新架构或新 dataclass（本提案已由三轮评审收敛，继续发散将浪费前序评审价值）
- **不做**Omni-SimpleMem 的 KG multi-hop / 向量嵌入 / 多模态 MAU（D2 明确为"合理本土化"省略）
- **不做**改造 `cradle_graph_store`（零读取消费者，改它是伪收益）
- **不做**自动化 bench（千条级规模 + 手工观察足以发现问题）

## 阶段 B 触发条件（写入本提案以防灰度永久化）

阶段 B spec 名称预设：**`phase-b-unify-memory`**（代号 P2UM）

触发任一条件启动 P2UM：
1. 双写期（≥ 2 周）连续 CI 绿、四象限测试零失败、`len(memories) == len(moments)` 不变量零偏差
2. 发现 V2 读路径相对 V1 在 `mind.py` prompt 生成 diff 稳定（ golden test 通过率 100%）
3. `interaction` spec 同步迁移到"读 life_moments 而非 state.memories"完成（或该 spec 正式 deprecate）

未满足上述条件前，**阶段 A 的双写策略永久保持**；不允许"悄悄停止写 state.memories"。
