# 任务清单：LifeMoment 统一原子 · 阶段 A

> 来源：三轮评审（11 agent）+ 用户场景验证 + D1/D2/D3 三组补强。
> 三问过滤：每条任务动手前自检——真实需求？有更简方案？会破坏什么？
> 死罪：见最末；任一条触及立即停工。

## 1. memory/ 模块骨架

- [ ] 1.1 创建 `backend/memory/` + `__init__.py` + `CLAUDE.md`（L2，按模板）
- [ ] 1.2 `schema.py`：`LifeMoment`（17 字段）+ `Milestone` + `RecalledContext` dataclass（`to_dict` / `from_dict` 防御性）
- [ ] 1.3 `forget_params.py`：`TAU_BY_PHASE`（12 项）+ 常量（`JACCARD_THRESHOLD`/`LOW_INTENSITY`/`PRUNE_SOFT_CAP`/`PRUNE_KEEP_TOP`）+ `MEMORY_V2_ENV` + `PHASE_B_SPEC_ID = "phase-b-unify-memory"`
- [ ] 1.4 `store.py`：复用 `state.py:40-65` 的 threading.Lock + seq 基础设施；`append_life_moment` / `append_milestone` / `load_life_moments` / `load_milestones` / `load_recent_moments(limit)` / `next_moment_seq`
- [ ] 1.5 `store.py`：文件路径统一 `archive/{baby_id}/life_moments.jsonl` 和 `milestones.jsonl`；baby_id 白名单校验复用 `state._validate_baby_id`
- [ ] 1.6 每个新 `.py` 头部补 L3 契约注释

## 2. 新颖性闸门 + 写入口（D2-1, D1-1）

- [ ] 2.1 `ingest.py`：`_tokens(text)` + `_jaccard(a, b)` 纯 Python 实现
- [ ] 2.2 `ingest.py`：`should_ingest(state, baby_id, moment)` 闸门（强制白名单 + Jaccard 过滤）
- [ ] 2.3 `ingest.py`：`record_moment(state, baby_id, **fields) -> LifeMoment | None` 单写入口
- [ ] 2.4 `ingest.py`：`_downgrade_to_memory(moment) -> Memory` 映射（守 interaction 契约，D1-2）
- [ ] 2.5 `ingest.py`：`record_milestone(state, baby_id, **fields) -> Milestone` 单写入口
- [ ] 2.6 **写顺序强制**：先 `append_life_moment` → 再 `state.memories.append` → 最后 `save_state`（D1-4）
- [ ] 2.7 **不变量断言**：`record_moment` 尾部 `assert len(state.memories) == store.count_life_moments(baby_id)`
- [ ] 2.8 单测 `test_ingest.py`：覆盖强制白名单 / 低强度+高相似丢弃 / 双写一致性 / companion_seq 追加

## 3. Memory 字段扩展 + 向后兼容

- [ ] 3.1 `cradle/state.py` `Memory` 新增 `forget_score: float = 1.0`
- [ ] 3.2 `Memory.to_dict` / `from_dict` 同步（`d.get("forget_score", 1.0)`）
- [ ] 3.3 更新 `state.py` L3 头注 OUTPUT
- [ ] 3.4 手工验证：加载 `AC-20260417-14297`（4 条 memories）→ save 后 state.json 含新字段 → 老代码读仍兼容

## 4. 读路径：recall with token_budget（D2-2, D2-3）

- [ ] 4.1 `recall.py`：`_tokens` / `_score(moment, ctx_tokens, tags, age)` 复用 forget 公式
- [ ] 4.2 `recall.py`：`_estimate_tokens(obj)` 按 `len(json.dumps(obj, ensure_ascii=False)) // 4`
- [ ] 4.3 `recall.py`：`_build_tag_index(moments)` 内存倒排 dict（cause_tags + effect_tags → moments）
- [ ] 4.4 `recall.py`：`recall(state, context, current_tags, token_budget=1500) -> RecalledContext` 三层金字塔：
  - Step 1 `phase_summaries[-3:]` 独立读
  - Step 2 `life_moments` 打分 top-8 + tag 一跳扩展 1-3 条
  - Step 3 相关 milestones top-3
  - 每步 budget 裁剪
- [ ] 4.5 `recall.py`：`_legacy_recall(state)` 回退分支（V2=off 走 `memories[-3:]`）
- [ ] 4.6 `__init__.py`：暴露 `recall` / `record_moment` / `record_milestone` / `is_v2_enabled` / `recompute_forget_scores` / `prune_if_needed`
- [ ] 4.7 单测 `test_recall.py`：预算裁剪 / 空库 fallback / V2 开关 / tag 一跳

## 5. 遗忘与巩固

- [ ] 5.1 `consolidation.py`：`_compute_forget_score(moment, age_days)` 按公式
- [ ] 5.2 `consolidation.py`：`recompute_forget_scores(state, baby_id)` 遍历 life_moments 重算 + 重写 jsonl（原子 tempfile + os.replace）
- [ ] 5.3 `consolidation.py`：`prune_if_needed(state, baby_id)` 软归档超 500 条（保留 top 300 forget_score）
- [ ] 5.4 scheduler 睡眠事件分支调用 `recompute_forget_scores` + `prune_if_needed`（复用 `get_baby_lock`）
- [ ] 5.5 单测 `test_forget.py`：TAU 查表 / 高强度保留 / 低强度沉底 / 软归档不删 jsonl

## 6. 接入点改造（共 27 条，按编号对应 design.md §5）

### 6.1 被动经验（#1-#3）
- [ ] 6.1.1 `cradle/mind.py:681` 改为 `record_moment(actor="world", target="self", ...)`
- [ ] 6.1.2 `cradle/mind.py:836` 同上
- [ ] 6.1.3 `scheduler/story.py:140` 同上

### 6.2 自主事件 / 自主日常（#4-#5）
- [ ] 6.2.1 `scheduler/handlers.py:320` turbo 自主事件 → `record_moment(actor="self")`
- [ ] 6.2.2 `scheduler/handlers.py:460` autonomous_routine → 按场景判定
- [ ] 6.2.3 `scheduler/handlers.py:607` autonomous_event → 按场景判定

### 6.3 主动行为（#6-#9, #11, #18）
- [ ] 6.3.1 `heartbeat.evaluate_heartbeat` 成功分支 → `record_moment(actor="self", outcome="pending")`
- [ ] 6.3.2 `heartbeat._check_and_process_ignore` 超时 → **append 新 moment**（不回改）`outcome="ignored"` + `companion_seq`
- [ ] 6.3.3 `heartbeat.mark_responded` → **append 新 moment** `outcome="responded"` + `companion_seq`
- [ ] 6.3.4 `initiative_needs.evaluate_need` 触发 → `record_moment(actor="self", trigger=need_trigger)`
- [ ] 6.3.5 `conversation.post_baby_message` → `record_moment(actor="self", target="caregiver:...")`
- [ ] 6.3.6 `cradle/nanny.py:1332` heartbeat_initiative/ignored → 同 6.3.1/6.3.2 手动路径

### 6.4 互动与家长介入（#10, #15-#17）
- [ ] 6.4.1 `conversation.post_parent_message` → `record_moment(actor="caregiver:...", target="self")`
- [ ] 6.4.2 `scheduler/handlers.py:227,265` critical_expired → `outcome="ignored"` + companion_seq
- [ ] 6.4.3 `scheduler/needs.py:144` need_responded by nanny_fallback → `outcome="fallback"`
- [ ] 6.4.4 `api/cradle.py:382` intervention → `record_moment(actor="caregiver:...")`

### 6.5 里程碑（#12-#14）
- [ ] 6.5.1 `scheduler/handlers.py:694,701` stress_regression/recovery → `record_milestone(kind="capability_lost"/"capability_recovered")`
- [ ] 6.5.2 `scheduler/handlers.py:724,738` capabilities_unlocked/milestones → `record_milestone(kind="capability_gained"/"milestone_reached")`
- [ ] 6.5.3 `scheduler/handlers.py:761,802` phase_completed/cradle_complete → `record_milestone(kind="phase_advanced"/"cradle_complete")`

### 6.6 读路径 mind.py 三入口（#19）
- [ ] 6.6.1 `mind.py:314` `generate_interaction_response` 改 `recall(state, context, tags, token_budget=1500)` + `phase_summaries[-3:]`
- [ ] 6.6.2 `mind.py:554` `process_critical_event` 同上
- [ ] 6.6.3 `mind.py:757` `narrate_phase_events` 同上
- [ ] 6.6.4 `mind.py:882` 上下文注入同上
- [ ] 6.6.5 `cradle/nanny.py:1260,1403` 内部 prompt 同上

### 6.7 下游消费切换（#20-#25）
- [ ] 6.7.1 `world.py:557` `experienced = {...}` V2=on 改读 life_moments.jsonl
- [ ] 6.7.2 `world.py:658` snapshot 最近 5 条 memory 同上
- [ ] 6.7.3 `events/__init__.py:133` 涌现冷却 同上
- [ ] 6.7.4 `api/cradle.py:260` `memories_count` 兼容逻辑
- [ ] 6.7.5 `api/cradle.py:477` /history payload 兼容：V2=on 从 life_moments 反向重建 `memories` 字段
- [ ] 6.7.6 `state.py:628` `rebuild_triggered_events` 双源遍历（D1-3）

### 6.8 前端（#27）
- [ ] 6.8.1 验证 `Cradle.jsx:654` 消费 `h.phase_summaries` 字段不变；如 6.7.5 payload 保持向后兼容则**不需改前端**
- [ ] 6.8.2 手工打开前端，/history 结果面板正常显示 phase_summaries

## 7. CI 保障 + 不变量（D1-1/D1-5）

- [ ] 7.1 `scripts/lint_no_direct_memory_append.py`：AST 扫 `state.memories.append(` 调用，白名单仅 `backend/memory/ingest.py`
- [ ] 7.2 集成到 CI（`pre-commit` 或 GitHub Action），红灯阻断 merge
- [ ] 7.3 运行时 assertion：`record_moment` 尾部 `len(state.memories) == count_life_moments`
- [ ] 7.4 **四象限测试矩阵** `test_quadrants.py`：
  - V2=on + 有 memories（懒重建）
  - V2=on + 无 memories（新 baby）
  - V2=off + 有 memories（旧路径）
  - V2=off + 无 memories（旧路径空）

## 8. 已归档 spec 兼容（D1-3, C11）

- [ ] 8.1 `rebuild_all_tags`（causal-graph spec 依赖）扩展为双源遍历 life_moments ∪ state.memories
- [ ] 8.2 验证 `interaction/requirements.md:49` 契约："most recent 3 memories from state.memories" 在 V2=on 下因降级回写仍成立
- [ ] 8.3 `autonomous-life/specs/agent-state.md:12`：state.memories 字段存在性不变，无需改
- [ ] 8.4 `world-context/*` spec 文档不改；实现切换走 #20/#21
- [ ] 8.5 `cradle-enhancement`：phase_summaries 不迁移（C6）零影响

## 9. 启动自检 + 崩溃恢复（D1-4）

- [ ] 9.1 `api/__init__.py` lifespan 或 scheduler 启动时调用 `memory.self_heal(baby_id)`：
  - 扫 life_moments.jsonl 最后 N 条
  - 对比 state.memories 最后 N 条 seq
  - 差集追加 downgrade 到 state.memories 并 save（幂等）
- [ ] 9.2 日志：记录每次 self_heal 修复条数（`logger.info`）
- [ ] 9.3 单测 `test_self_heal.py`：人为构造"jsonl 有 2 条 state 无"场景，启动后自动修复

## 10. 文档同步（分形同构铁律）

- [ ] 10.1 `backend/CLAUDE.md`（L1）目录清单新增 `memory/`
- [ ] 10.2 `backend/memory/CLAUDE.md`（L2）按模板完成
- [ ] 10.3 `backend/cradle/CLAUDE.md` 说明 `mind.py` / `nanny.py` 对 `memory.record_moment` 的使用
- [ ] 10.4 `backend/scheduler/CLAUDE.md` 说明接入点 6.2/6.4/6.5
- [ ] 10.5 `backend/heartbeat.py` / `initiative_needs.py` L3 OUTPUT 更新
- [ ] 10.6 所有新 `.py` 文件顶部 L3 头注完整

## 11. 验证基线

- [ ] 11.1 冷启动 backend + 前端，API 全部可用
- [ ] 11.2 `AC-20260417-14297` 跑一次 /interact，验证 life_moments.jsonl 生成 + state.memories 同步增长
- [ ] 11.3 构造"找妈妈讨论上学"样本（interact 端点发送）→ 观察 moment 字段：actor="self" target="caregiver:..." outcome="responded"
- [ ] 11.4 主动行为验证：等待 heartbeat 自主触发（或手工触发）→ 确认 moment 写入 + companion_seq 链完整
- [ ] 11.5 触发睡眠事件 → 确认 forget_score 被重算 + 文件无损
- [ ] 11.6 `MEMORY_V2=off` 重启，/interact prompt diff 与之前记录的 V1 基线一致
- [ ] 11.7 `MEMORY_V2=on` 重启，不变量断言零告警运行 ≥ 30 分钟
- [ ] 11.8 AC-20260417-14226（无 state.json）API 端点 /status /lifeline 不崩溃

## 12. 观察期 + 阶段 B 触发条件（D1-5）

- [ ] 12.1 部署后开启观察记录：`docs/phase-a-observations.md`
- [ ] 12.2 每天记录：recall 调用次数、命中 tag 一跳扩展的比例、prompt token 实际值
- [ ] 12.3 ≥ 2 周后，若三触发条件全部满足，起新 spec change `phase-b-unify-memory`：
  - CI 不变量零告警
  - 四象限测试零失败
  - V2=on vs V2=off 的 prompt golden diff 稳定
- [ ] 12.4 未满足前，本 spec 的双写策略**永久保持**，禁止偷偷停止写 `state.memories`

---

## 优先级 · 分 PR 建议

| PR | 任务范围 | 预计 |
|---|---|---|
| PR-1 | §1, §3, §2.1-2.7（模块骨架 + 数据模型 + 写入口）| 0.5 天 |
| PR-2 | §4（recall 读路径）+ §6.6（mind.py 接入）| 0.5 天 |
| PR-3 | §6.1-6.5（写接入点 15 处，含 heartbeat/need/conversation）| 1 天 |
| PR-4 | §6.7-6.8（下游消费切换 + 前端验证）+ §8（兼容 shim）| 0.5 天 |
| PR-5 | §5（巩固）+ §9（自检）+ §7（CI 保障 + 四象限）| 0.5 天 |
| PR-6 | §10（文档）+ §11（验证）| 0.5 天 |

总计 ≈ 3.5 天工作量。

---

## 死罪清单（任一触及立即停工）

- [ ] ❌ 禁止直接调 `state.memories.append(`（仅 `memory/ingest.py` 的 `record_moment` 内允许）—— CI 红灯阻断
- [ ] ❌ 禁止回改已写入 jsonl 的 moment（违反 append-only）—— 状态转移必须 append 新 moment + companion_seq
- [ ] ❌ 禁止删除 `state.memories` 或 `state.phase_summaries` 字段（C3 向后兼容铁律）
- [ ] ❌ 禁止在 V2=on 下"静默跳过"state.memories 降级回写（D1-2 守 interaction 契约）
- [ ] ❌ 禁止引入 SQLite / sentence-transformers / 任何 pip 新依赖（C2）
- [ ] ❌ 禁止改造 `cradle_graph_store` 或写 KG multi-hop 查询（C5，本阶段延后）
- [ ] ❌ 禁止写入 `events.jsonl` 新事件类型（防污染 lifeline SSE）
- [ ] ❌ 禁止在本 spec 内 "悄悄" 进阶段 B（必须显式 spec change `phase-b-unify-memory`）
- [ ] ❌ 禁止合并前留下缺失的 L2/L3 文档（FATAL-002/FATAL-004）
- [ ] ❌ 禁止新发明 tag 格式（C4 严格复用 `causality.generate_cause_tags/effect_tags`）

## 关键文件速查（避免重蹈 `memory/memories` 事实错误）

| 现实 | 位置 |
|---|---|
| 字段名 | `state.memories`（不是 `memory`），`state.phase_summaries` |
| Memory 创建点 | `scheduler/story.py:140` / `cradle/mind.py:681,836`（全项目只有 3 处）|
| 主动行为**当前**完全不写 Memory | `heartbeat.py` / `initiative_needs.py` / `conversation.post_baby_message` |
| 真实 tag 格式 | 见 design.md §3.2 示例表，例如 `phase:5` / `stress:+0.15` / `attachment:toward_secure` / `memory:positive` / `growth:X` |
| 前端 phase_summaries 消费 | `frontend/src/Cradle.jsx:654` |
| interaction 契约 | `specs/interaction/requirements.md:49` |
| 无 state.json 的 baby | `archive/AC-20260417-14226/`（只有 `causal_graph.json`）|
| 有 memories 的 baby | `archive/AC-20260417-14297/` (4 条) |
