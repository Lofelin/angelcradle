# memory/
> L2 | 父级: /backend/ (目前 backend 无 L1 CLAUDE.md)

生命体长期记忆系统 · 阶段 A。统一原子 `LifeMoment` + 独立 `Milestone` + 复用 `state.phase_summaries`。
无嵌入、无 SQLite、无外部依赖。Jaccard + tag + 遗忘分公式，双写灰度守旧 spec 契约。

完整设计：`../specs/long-term-memory/design.md`
评审档案：`../specs/long-term-memory/reviews/`
终结 spec：`phase-b-unify-memory`（触发条件见 proposal.md §阶段 B 触发条件）

## 成员清单

schema.py: 数据模型 — LifeMoment（17 字段，无 kind，actor/target 区分事件类型）+ Milestone（独立，能力变化/首触/阶段节点）+ RecalledContext（recall 返回结构）。所有 dataclass 都有 to_dict/from_dict，字段默认值对老数据 JSON 兼容。

forget_params.py: 常量层 — TAU_BY_PHASE 12 阶段遗忘时间（Ebbinghaus 指数近似，非文献精调）+ JACCARD_THRESHOLD/LOW_INTENSITY/HIGH_INTENSITY 闸门阈值 + CAREGIVER_PREFIX/SELF_ACTOR/WORLD_ACTOR actor 命名空间 + PRUNE_SOFT_CAP/KEEP_TOP 剪枝阈值 + MEMORY_V2_ENV/PHASE_B_SPEC_ID 灰度开关。

store.py: 持久化层 — 复用 cradle.state 的 threading.Lock + baby_id 白名单校验 + 行原子 append。life_moments.jsonl / milestones.jsonl 两套独立 seq（与 events.jsonl 的 seq 也独立）。提供 append/load/count/next_seq/rewrite（后者支持 consolidation 重算 forget_score 时原子替换）。

ingest.py: 写入门面 — **record_moment 是 LifeMoment 唯一写入口**（CI 静态检查通过 scripts/lint_no_direct_memory_append.py 禁用 state.memories.append 直接调用）。顺序约定：next_seq → should_ingest 闸门（Jaccard + 强制白名单）→ append_life_moment → state.memories.append(_downgrade_to_memory 或 _legacy_memory_override) 降级回写守 interaction 契约。_legacy_memory_override 让旧创建点保留 LLM trace 原文等语义。record_milestone 同构，写 milestones.jsonl。_compute_forget_score 为读写两端共用的遗忘公式。assert_invariant 提供运行时不变量校验（MEMORY_STRICT=1 时抛异常）。

recall.py: 读取门面（D2 对齐 Omni-SimpleMem）— **recall(state, context, current_tags, token_budget=1500)** 三层金字塔检索：Step 1 semantic（phase_summaries[-3:]，_semantic_tokens 只算 summary 字段 ≤ budget*40% 防吃光）→ Step 2 episodic（life_moments 按 Jaccard + tag_overlap + forget_score 排序 top-8，再通过 _build_tag_index 做 cause/effect_tags 一跳倒排扩展 1-3 条，_RESERVE_FOR_MILESTONE=150 预留）→ Step 3 milestone（按 phase + tag 相关性 top-3）。build_memory_prompt_block 渲染为 "Long-term traits / Recent episodes / Milestones" 三块 LLM prompt 片段。V2=off 时 _legacy_recall 返回空 episodic，回退业务代码的 memories[-3:] 旧行为。

consolidation.py: 维护层（PR-5）— recompute_forget_scores 遍历 life_moments 按 state.age_days 重算 forget_score 并原子 rewrite 文件；prune_if_needed 超 PRUNE_SOFT_CAP=500 时按 forget_score 保留 top PRUNE_KEEP_TOP=300 硬剪；self_heal 启动自检（D1-4 崩溃恢复）——扫描 jsonl 与 state.memories 差集，补齐 Step 3 成功 Step 4 未完成的孤儿降级条目，幂等。

## 对外暴露

```python
from memory import (
    # 数据模型
    LifeMoment, Milestone, RecalledContext,
    # 写入口（业务代码唯一入口）
    record_moment, record_milestone,
    # 读取门面
    recall, build_memory_prompt_block,
    # 维护与自检（PR-5）
    recompute_forget_scores, prune_if_needed, self_heal,
    # 控制流
    is_v2_enabled, assert_invariant,
    # 只读查询（recall/consolidation/debug）
    load_life_moments, load_milestones, load_recent_moments,
    count_life_moments, count_milestones,
    # 常量
    TAU_BY_PHASE, JACCARD_THRESHOLD, MEMORY_V2_ENV, PHASE_B_SPEC_ID,
)
```

## 依赖关系

- `cradle.state`：只读复用 `_validate_baby_id` / `_baby_dir` / `_infra_lock` / `_count_lines` 基础设施；写侧通过 `state.memories.append(_downgrade)` 实现降级回写（D1-2 守 interaction 契约）
- `causality.py`：tag 格式完全复用（`phase:N` / `stress:+X` / `attachment:toward_*` / `memory:*` / `growth:*` 等），本模块不产生任何新 tag 格式
- **无**外部 pip 依赖（无 sentence-transformers / sqlite / FAISS）

## 数据流

```
写路径（业务代码调用）:
  nanny/mind/heartbeat/initiative_needs/conversation/scheduler
    → memory.record_moment(state, baby_id, actor=..., ...)
      → next_moment_seq(baby_id)         (复用 state.py threading.Lock)
      → should_ingest(baby_id, moment)   (Jaccard + 强制白名单)
      → append_life_moment                (行原子写 life_moments.jsonl)
      → state.memories.append(_downgrade 或 _legacy_memory_override) (V2 开关无关，总是回写)
    → 调用方负责 save_state(state)

读路径（mind.py 三入口 + heartbeat_provider.py:406）:
  → memory.recall(state, context, tags, token_budget=1500)
    → Step 1 semantic: state.phase_summaries[-3:]，_semantic_tokens 只算 summary 字段，≤ budget*40%
    → Step 2 episodic: load_life_moments + _score(Jaccard+tag+forget) + _tag_expand 一跳
    → Step 3 milestone: load_milestones 相关性过滤 top-3
  → build_memory_prompt_block 渲染三块 prompt
  → RecalledContext(semantic, episodic, milestones, used_tokens, budget)

巩固路径（world.py:504 sleep 事件 + 启动 lifespan）:
  → recompute_forget_scores: 遍历重算并 rewrite jsonl
  → prune_if_needed: soft_cap=500 超限时保留 top 300
  → self_heal: 启动自检修复 jsonl 与 state.memories 的不一致（api/__init__.py lifespan）

兼容矩阵（已归档 spec）:
  interaction/requirements.md:49: 最近 3 memories from state.memories
    → V2=on/off 都成立（降级回写保证 state.memories 完整）
  causal-graph/tasks.md:54: rebuild_all_tags 遍历 state.memories
    → cradle/state.rebuild_triggered_events 已扩展为双源遍历（jsonl + state.memories）
  world.py / events/__init__.py: 读 state.memories
    → 保持原路径（降级回写守住），未来 phase-b-unify-memory 升级
```

## 不动的边界

- `cradle_graph_store`：阶段 A 不碰（零读取消费者，C5 共识）
- `state.memories` schema：不删不改（C3 向后兼容铁律）
- `events.jsonl`：不写新事件类型（防污染 lifeline SSE）
- `pyproject.toml`：不新增依赖（C2）

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
