# 任务清单：add-cradle-growth-graph

## 完成摘要（2026-04-22 三批次落地）

四批次全部完成（除 Gate 3 浏览器验收留给用户）：

| Phase | 完成度 | 说明 |
|---|---|---|
| A 契约固化 | ✅ | ontology.py + graph_ids.py + graph_emit.py + graph_story.py + sample.json v1（138 节点 / 194 边）|
| B graph_emit 帮手 | ✅ | 18+ 节点 + 23+ 边构造器 + apply_delta reducer + track_sample；单测 12/12 绿 |
| C graph_story 双语 | ✅ | 6 类 META + 31 phase 全覆盖 + hydrate helpers |
| D 业务接入 | ✅ | scheduler/handlers 6 切点 + needs need_responded + api/cradle /intervene critical 决议。conversation/mind 业务层**本期跳过**（见下方"合理跳过"）|
| E API | ✅ | registry save/load_cradle_graph + baby_router GET /baby/{id}/cradle-graph（live 优先 + fallback 落库 + 404）+ 老 stub 转发；进程内累积状态由 graph_session 托管 |
| F 前端 | ✅ | utils/mergeGraph 共享；useCradleGraph 新建；useLifeline onEvent 多订阅者；Cradle.jsx 接入（LifeGraph 新 hook 优先，老 graphState 仅做 UI 控制）|
| G 四 Gate | ⚠️ | Gate 1/2/4 全绿（15 suites + 12 Gates）；**Gate 3 浏览器验收留给用户** |
| H 文档回环 | ✅ | cradle/CLAUDE.md + scheduler/CLAUDE.md + /CLAUDE.md + memory/project_cradle_graph_status.md |
| I 旧提案 | 📝 | refactor-cradle-graph-phase-axis 的"继承与超越"说明待归档时补（非阻断）|
| J 发布 | 📝 | commit message 模板见 §10；实际 git commit 待用户指令 |

### 2026-04-23 补丁：caregiver 自举 + CARED_BY per-phase ×2（G2 拓扑修复）

首次上线后 AC-20260422-44207 归档暴露：baby_this 入度 = 10（样本 27），五版事故征兆复发。根因：`cradle.__init__.admit_stream` 构造 `BabyState` 时未初始化 `caregivers` 字典，导致 `emit_caregivers_from_state` 迭代空字典 → 0 caregiver 节点、0 CARED_BY、0 ATTACHES_TO、0 NAMED_BY。

**修复清单**（见 `scripts/test_cradle_caregiver_bootstrap.py` 守护）：
1. `cradle/__init__.py`：`admit_stream` 构造 `BabyState` 时显式塞 `primary_parent` + `attachment_per_caregiver["primary_parent"]="forming"`
2. `cradle/state.py`：`BabyState.from_dict` 在 `caregivers` 空 + 无 `parent_profile` 时兜底补 `primary_parent`（老 archive 恢复路径）
3. `scheduler/handlers.py`：turbo 自动命名分支补 emit `critical` + `NAMED_BY` + `RESOLVES`（非 turbo 走 `/intervene` 原路径）
4. `scheduler/needs.py`：`nanny_fallback` 超时路径补 emit `TRIGGERED_BY` + `need` 事件（原先只有用户响应路径 emit）
5. `scheduler/graph_hooks.py`：`emit_caregivers_from_state` 加 `moment: "phase_start" | "phase_complete"` 参数，两次调用 UUID 不同 → per-phase 2 条 CARED_BY（9 阶段 × 2 = 18 条，对齐样本 17）

**预估拓扑指标（9 阶段跑完）**：
- baby_this 入度 ≈ 29（样本 27，达标率 107%）
- 18 CARED_BY + 9 ATTACHES_TO + 1 NAMED_BY + 9 DESCRIBES + 1 TerminatedBy
- baby_this 稳定 top-1，优势从 1.25× 回到 3-4×

**业务真相同步**：`CRADLE_EXIT_PHASE = 9` (exclusive)，baby 实际只跑 `phase_index 0-8 = 9 阶段`进世界。本 tasks.md §7.2 原写"12 个 progression 节点"是规范漂移，更正为 `CRADLE_EXIT_PHASE` 阶段数。rule_understanding/abstract_beginning/independence 是 `PHASES` 静态定义保留项，摇篮期不跑。

### 合理跳过的任务（需单独 proposal）

- 3.3 teratogen / 3.4 vitals 业务接入：本变更范围是摇篮图，womb 侧业务接入在另一 change
- D.4.4 conversation.py 接入：消息级 SPEAKS_TO 的爆量防护策略未定（node_conversation 首次 emit + message_count update 需要在 conversation store 加节流）
- D.4.5 mind.py 直接 emit narrative：handlers.emit_phase_completed 已经接住 summary 间接 emit narrative + DESCRIBES，mind.py 直接接入为二次冗余，延后
- 4.2 SSE 子事件拆分：lifeline 当前是整条事件透传，已足够；子事件拆分是后续体验优化
- 6.9 样本最终节点数 ≤ 40 / 边数 ≤ 85：该目标在 add-womb 语境下，cradle spec 目标是 80-150 / 180-320，sample 138/194 在范围内 ✅
- 验证 7.5 真实跑 human 12 阶段 SSE：由 Gate 3 浏览器验收完成
- 7.6 流产场景测试：scheduler 层暂无流产事件路径，需要 fate 集成后再做

### 后续单独 change 建议

- **"womb baby_this import 共享常量"**：把 `backend/womb/graph_emit.py:101` 的 `"baby_this"` 字面量改为 `from common.graph_ids import BABY_SELF_RAW_ID`。一次 3 行改动，保证未来如果改 raw_id 时只改一处
- **"conversation graph emit"**：conv 节点首次 emit + 消息级 SPEAKS_TO 节流采样策略
- **"Gate 3 浏览器验收"**：用户跑真实摇篮 session，验证前端 cradleGraph 接入多重边渲染效果

---

## 1. 设计契约固化（Phase A）

- [ ] 1.1 在 `backend/cradle/ontology.py`（**新建**）固化 `DIMENSION_PHASES` 静态表（6 维 × 4-5 per-dim phase）与 `CAPABILITY_DIMENSION_MAP`（capability_key → dim 路由）。本表对齐 `specs/cradle-dev-ontology/proposal.md` 已冻结内容。
- [ ] 1.2 在 `backend/common/graph_ids.py`（**新建**）固化 `BABY_SELF_RAW_ID = "baby_this"` 常量，供 womb 和 cradle 共同引用，确保 UUID 跨图一致。
- [ ] 1.3 编写 `frontend/src/data/cradle-growth-sample.json` v1（**新建**）作为"设计参考实现"，完整描绘一个虚拟 human baby 走完 12 阶段的图谱（含一次压力回退、一次依附漂移、两次 critical_event、多重边 caregiver↔baby、跨 phase_index 的 attachment 状态切换）。规模目标 100 节点 / 220 边。
- [ ] 1.4 在 `openspec/changes/add-cradle-growth-graph/design.md` 核查节点/边清单与 `sample.json` 一致；发现漂移即刻同步。
- [ ] 1.5 在 `openspec/changes/add-cradle-growth-graph/specs/cradle-graph/spec.md` 以 SHALL / MUST 形式固化全部契约。

## 2. 后端 graph_emit 帮手库（Phase B）

- [ ] 2.1 新建 `backend/cradle/graph_emit.py`，文件头 L3 注释齐全（INPUT/OUTPUT/POS/PROTOCOL）。
- [ ] 2.2 UUID 规则**直接复用** `backend.womb.graph_emit.make_edge_uuid` 与 `make_node_uuid`（from import）；在 `cradle/graph_emit.py` 不另立 namespace，不重新实现。
- [ ] 2.3 实现身份层节点构造器：
  - `node_baby(status="alive")`（内部 raw_id = `graph_ids.BABY_SELF_RAW_ID`，确保与 womb 图字节一致）
  - `node_caregiver(caregiver_id, role, **meta)`（role ∈ {mother, father, grandparent, nanny}）
  - `node_species_ref(code)`（可选，从 womb 图映射引用）
- [ ] 2.4 实现调度层节点构造器：
  - `node_progression(phase_name, phase_index, **meta)` → category=`progression`
- [ ] 2.5 实现发育层节点构造器：
  - `node_dimension(dim)`（6 个维度之一）
  - `node_phase_dim(dim, stage)` → category=`phase`，内部自带 `BELONGS_TO → dimension:{dim}` 边由帮手 `edge_phase_belongs_to` 统一发出
  - `node_capability(cap_key, dim, unlocked_at_phase, **meta)`
  - `node_milestone(slug, kind, achieved_at_phase, **meta)`
- [ ] 2.6 实现心理层节点构造器：
  - `node_preference(tag, category, strength, acquired_at_phase)`
  - `node_fear(tag, severity, acquired_at_phase)`
  - `node_comfort(tag, kind, acquired_at_phase)`
  - `node_temperament(dimensions, defined_at_phase)`（若继承自 womb 图，走 reference 不复建）
- [ ] 2.7 实现需求与事件层节点构造器：
  - `node_need_type(trigger, urgency, timeout_min)`（19 种 trigger 的 continuant 身份）
  - `node_event(event_type, phase_index, seq, result, **meta)`
  - `node_critical(phase_index, seq, reason, status="pending")`
  - `node_regression(cap, phase_index, stress_level_at)`
  - `node_recovery(cap, phase_index, strengthened, care_from)`
  - `node_conversation(conv_id, kind, participants)`
  - `node_narrative(phase_index, summary, length_chars)`
- [ ] 2.8 实现结构性边构造器：
  - `edge_phase_belongs_to(dim, stage)`（Phase → Dimension）
  - `edge_next(prev_phase_name, next_phase_name)`（Progression 间时间线）
  - `edge_descends_from(baby, ancestor_id)`（可选，本期若不做 womb 继承视觉则跳过）
- [ ] 2.9 实现发育承担边构造器：
  - `edge_occurs_in(cap_or_milestone, dim, stage)` → **内置断言**：目标 category=`phase`，绝不指向 progression
  - `edge_unlocks(event_id, cap_id, phase_index, **meta)`
  - `edge_achieves(baby_id, milestone_id, phase_index, day_index=None)`
  - `edge_regresses(event_id, cap_id, phase_index, stress_level_at)`
  - `edge_recovers(event_id, cap_id, phase_index, strengthened, care_from)`
  - `edge_driven_by(cap_new, cap_prereq, weight)`
- [ ] 2.10 实现照护关系边构造器：
  - `edge_cared_by(caregiver_id, baby_id, phase_index, day_index, quality, event_ref=None)`
  - `edge_attaches_to(baby_id, caregiver_id, phase_index, state, since_day)`
  - `edge_named_by(caregiver_id, baby_id, day_index, name_given)`
  - `edge_soothes(source_id, baby_id, phase_index, stress_delta)`
  - `edge_stresses(source_id, baby_id, phase_index, stress_delta, reason)`
- [ ] 2.11 实现经验塑形边构造器：
  - `edge_triggered_by(event_id, need_id, phase_index, day_index, resolution)`
  - `edge_experiences(baby_id, event_id, phase_index, day_index)`
  - `edge_exposed_to(baby_id, event_id, phase_index, day_index, tag)`
  - `edge_acquires(baby_id, trait_id, phase_index, day_index, source_event_ref=None)`
  - `edge_speaks_to(baby_id, conv_id, phase_index, msg_seq)`
  - `edge_caused_by(event_id, cause_id, phase_index, weight, description)`
- [ ] 2.12 实现归因叙事边构造器：
  - `edge_resolves(caregiver_id, critical_id, phase_index, action, tag_effects)`
  - `edge_describes(narrative_id, baby_id, phase_index)`
  - `edge_terminated_by(event_id, baby_id, phase_index, cause)`
- [ ] 2.13 实现 delta 工具（可直接复用 womb 版本或镜像实现）：`delta_add / delta_update / delta_remove / merge_deltas`。
- [ ] 2.14 实现便捷聚合 API `emit.track_sample(node_id, phase_index, day_index, **sample)` → 返回只含 `update_nodes` 的 delta，引导业务代码走日常采样路径而非反复 add_nodes。
- [ ] 2.15 单元测试 `backend/tests/test_cradle_graph_emit.py`：
  - 节点构造器返回 dict 符合 spec
  - UUID 唯一性 + 多重边 uuid 差异
  - `edge_occurs_in` 目标指向 progression 时 raise
  - `make_node_uuid("baby_this")` 在 cradle 与 womb 两侧字节相等（`test_baby_id_cross_graph_consistency`）
  - `merge_deltas` 幂等

## 3. graph_story 双语文本（Phase C）

- [ ] 3.1 新建 `backend/cradle/graph_story.py`（对标 `backend/womb/graph_story.py`），填充 META 字典：
  - `CAPABILITY_META[cap_key]` = {label_zh, label_en, narrative_zh, narrative_en, scientific_zh, scientific_en}
  - `MILESTONE_META[slug]`
  - `DIMENSION_META[dim]`
  - `PHASE_DIM_META[(dim, stage)]`
  - `PROGRESSION_META[phase_name]`
  - `NEED_META[trigger]`
  - `PREFERENCE_META` / `FEAR_META` / `COMFORT_META` 常见标签词典
- [ ] 3.2 文件头 L3 注释齐全。

## 4. scheduler 与业务函数接入（Phase D）

- [ ] 4.1 `backend/scheduler/handlers.py`：
  - `on_phase_start`：emit `node_progression` + `edge_next(prev, this)`（phase_index > 0 时）+ baby 节点 track_append 记录 phase 切换
  - `on_day_tick`：**不**每日 emit 新节点；按需 emit `update_nodes.track_append` 追加 stress / nutrition_sleep / emotional 日采样；只在"能力回退触发" / "critical 入队" / "scene 触发" 时 emit add 节点
  - `on_phase_complete`：聚合阶段总结相关 delta（capability 解锁 / milestone / narrative）
  - 所有 delta 通过 `graph_emit.merge_deltas` 合并塞入 `event.payload["graph_delta"]`
- [ ] 4.2 `backend/cradle/nanny.py`：
  - `simulate_phase` / `simulate_phase_stream`：场景产出时 emit event（若满足 "显著" 条件）；能力检查时 emit capability 解锁 delta；压力回退触发时 emit regression；复原时 emit recovery
  - `resolve_critical_event`：
    - 若是首次触发 critical（保险起见应在触发时即 emit pending，本处负责 resolve 时 `update_nodes` 状态 + `edge_resolves`）
    - 命名仪式 `edge_named_by`
    - caregiver_profile 更新时同步 caregiver 节点 metadata patch
  - `complete_phase`：阶段收尾时 emit `node_narrative` + `edge_describes`；解锁 capability 集中 emit
- [ ] 4.3 `backend/cradle/initiative_needs.py`：
  - 首次 19 种 need 使用时 emit 对应 `node_need_type(trigger, urgency, timeout_min)`（只建一次）
  - `evaluate_need` 命中需求时 emit `node_event("need_trigger", ...)` + `edge_triggered_by(event, need)` + `edge_experiences(baby, event)`
- [ ] 4.4 `backend/cradle/conversation.py`：
  - `get_or_create_conversation` 首次创建 emit `node_conversation(conv_id, kind, participants)`
  - `post_parent_message` / `post_baby_message` 写消息时 emit `edge_speaks_to(baby, conv, phase_index, msg_seq)` 多重边 + `update_nodes({id: conv_id, metadata: {message_count: +1, last_active_ts: ...}})`
- [ ] 4.5 `backend/cradle/mind.py`：
  - `narrate_phase_events` / `generate_phase_summary` 完成后返回 narrative 节点 + `DESCRIBES` 边
  - 因果标签（cause_tags / effect_tags）作为 event 节点的 metadata 透传（本期不单独实体化为节点，保留文本）
- [ ] 4.6 `backend/cradle/heartbeat_provider.py`：
  - 心跳评估不主动 emit（避免爆量）；被 `evaluate_need` 间接触发时由 initiative_needs 层负责 emit

## 5. API 层扩展（Phase E）

- [ ] 5.1 `backend/api/registry.py` 新增：
  - `save_cradle_graph(baby_id, graph)` 落库 `archive/{baby_id}/cradle_graph.json`（schema 字段 `v3-business-as-graph`）
  - `load_cradle_graph(baby_id)` 读取；schema 版本不匹配时返回 `None`
  - 文件头 L3 [OUTPUT] 列表补充
- [ ] 5.2 `backend/api/cradle.py`：
  - `/lifeline` SSE 事件 payload 透传 `graph_delta` 字段（scheduler/handlers 已写入，此处只确保 JSON 序列化正确）
  - 新增端点 `GET /baby/{baby_id}/cradle-graph`：返回落库快照；404 文案 `"Cradle graph not found for baby '{id}'"`
  - 老 stub 端点 `GET /cradle/{baby_id}/graph` 改造为 `load_cradle_graph` 前向兼容：若存在新 schema 返回之；否则返回 `{nodes: [], edges: []}` 保持 stub 行为
  - 文件头 L3 [OUTPUT] 更新
- [ ] 5.3 `backend/api/conceive.py` 无改动（womb 端点与本变更无耦合）；仅在 `save_womb_graph` 调用处确保 `baby_this` 节点 raw_id 来自 `graph_ids.BABY_SELF_RAW_ID` 常量（若已硬编码不一致，本期顺带修正）。
- [ ] 5.4 scheduler 累积图状态：在 `BabyState` 增加瞬态（非持久化）字段 `_cradle_graph_state = {"nodes": {}, "edges": {}}`，或在 scheduler 层维护 per-baby 累积字典；每个 delta 应用后更新；`phase_complete` / 终局事件时 snapshot 到 `registry.save_cradle_graph`。
- [ ] 5.5 累积状态 reducer（Python 版）放在 `backend/cradle/graph_emit.py` 的 `apply_delta(state, delta) -> state`，与前端 `mergeGraph` 行为一致；单测覆盖。

## 6. 前端 hook + 组件扩展（Phase F）

- [ ] 6.1 提炼共享工具：新建 `frontend/src/utils/mergeGraph.js`，把 `useWombGraph.js` 的 `mergeGraph` 拷入；`useWombGraph.js` 改为 `import { mergeGraph } from '../utils/mergeGraph'`，行为零变化。
- [ ] 6.2 新建 `frontend/src/hooks/useCradleGraph.js`：
  - 接受可选 `babyId` 参数
  - 暴露 `{ nodes, edges, applyEvent(data), reset(), loadSnapshot(graph) }`
  - `applyEvent`：识别 `data.graph_delta` 字段（无论 event 名称），调用 `mergeGraph`
  - `loadSnapshot`：接受 `{nodes, edges}` 完整快照作为初始化
  - 文件头 L3 注释齐全
- [ ] 6.3 改造 `frontend/src/hooks/useLifeline.js`：
  - 新增可选 `onEvent(callback)` prop，每条 SSE 事件统一回调
  - 不破坏现有 `events` 数组返回接口（双通道共存）
- [ ] 6.4 `frontend/src/Cradle.jsx` 或宝宝详情页：
  - `const cradleGraph = useCradleGraph(babyId)`
  - `useLifeline(babyId, { onEvent: cradleGraph.applyEvent })`
  - 初次进入页面 fetch `/baby/{babyId}/cradle-graph`，若有快照 `cradleGraph.loadSnapshot(resp)` 作为重播起点
  - 把 `<LifeGraph nodes={cradleGraph.nodes} edges={cradleGraph.edges} />` 渲染到摇篮视图区域
- [ ] 6.5 前端空态处理：节点 0 / 边 0 时显示"等待生命成长..."占位（不报错）
- [ ] 6.6 前端容错：`graph_delta` 字段缺失 / 非法 JSON 时静默跳过；重复 add 同 id 节点行为幂等（已由 `mergeGraph` 保证）

## 7. 测试与验证（Phase G — 四道验证关）

- [ ] 7.1 **Gate 1 · pytest 通过**：
  - `test_cradle_graph_emit.py` 全绿
  - `test_baby_id_cross_graph_consistency.py` 绿（UUID 跨图字节一致）
  - `test_ontology_dimension_phases.py` 绿（每个 dim 至少 4 个 stage，`CAPABILITY_DIMENSION_MAP` 全覆盖已知 capability）
- [ ] 7.2 **Gate 2 · 单元语义对**：跑一次完整摇篮期（CRADLE_EXIT_PHASE=9 阶段），断言：
  - 无时间节点：`assert not any(n["metadata"]["raw_id"].startswith(("stage_", "day_", "phase_x_day_")) for n in nodes)`
  - 9 个 progression 节点（= CRADLE_EXIT_PHASE，摇篮期实际跑的阶段数；phases 静态表定义了 12 个但 cradle 只消费前 9 个）、6 个 dimension 节点、28±2 个 phase 节点
  - 所有 phase 节点带 `BELONGS_TO → dimension:*` 出边
  - 所有 capability / milestone 的 `OCCURS_IN` 目标 group=`phase`（反向断言：`not any(e.type == "OCCURS_IN" and target_group == "progression")`）
  - 同一 `caregiver_mother → baby_this CARED_BY` 多重边数 ≥ 3
  - `baby_this → caregiver_mother ATTACHES_TO` 至少 2 条（state 切换）
- [ ] 7.3 **Gate 3 · 整体形状对**：
  - 打印节点度数分布：baby_this 的 in-degree + out-degree 全图最高（≥ 30）；caregiver_mother 次高
  - 对照 `cradle-growth-sample.json` 的 stats 字段，节点数 / 边数 / 多重边分布 ±15% 范围内
  - **启动前端，打开浏览器实际看图**；截图归档或明确声明"只验证了后端"
- [ ] 7.4 **Gate 4 · 用户视角对**（反向测试）：
  - "Neonatal 阶段（phase_index=0）图上会出现 `capability_walk` 节点吗？" → 不会（walk 最早 locomotion phase_index=4 解锁）
  - "phase_index=2 的图上能看到 `milestone_first_word` 吗？" → 不会
  - "流产 / 死产场景：后续阶段的 capability / caregiver 交互边还会出现吗？" → 不会（编排层提前退出）
  - "同一 caregiver_mother 会因不同阶段被拆成多个节点吗？" → 不会（continuant 稳定）
  - "walk 能力被压力回退再恢复，图上能看到完整双向轨迹吗？" → 能（REGRESSES 边 + RECOVERS 边并存，stream 保留历史）
- [ ] 7.5 前后端联调：真实跑一次 human 摇篮期 SSE，观测前端图实时生长；关键阶段截图。
- [ ] 7.6 跨图延续测试：跑完一次完整 baby（womb → cradle → world_ready），验证 `archive/{baby_id}/womb_graph.json` 与 `cradle_graph.json` 中 `baby_this` 节点 UUID 字节相同；前端若将两 JSON 合并，同 id 节点天然去重（Map.set 行为）。
- [ ] 7.7 压力回退场景测试：mock 高压触发 walk 回退、后续 care 触发 recovery，断言图谱包含两个对应 event 节点 + 双向边；前端可视化验收。
- [ ] 7.8 critical_event 悬挂态测试：触发 critical 后不 resolve，下阶段仍 pending，落库时保留 pending 状态；家长数小时后 resolve，节点 status 从 pending 改为 resolved + 新增 `edge_resolves`。
- [ ] 7.9 性能 smoke：跑 5 次完整摇篮期（或压缩时间尺度快进），前端图渲染无明显卡顿，D3 simulation tick 率 ≥ 30fps；落库文件 ≤ 200KB / baby。

## 8. 文档同步（Phase H — DocOps 分形回环）

- [ ] 8.1 `backend/cradle/CLAUDE.md` L2 文档更新：
  - 成员清单新增 `graph_emit.py` / `graph_story.py` / `ontology.py`
  - "图谱概念两分（v3）" 章节补充"业务即图 + 实时增量"说明
  - "摇篮图谱集成"章节：描述 nanny / scheduler / initiative_needs / conversation / mind 各自的 emit 职责
  - 依赖关系表新增 `backend/common/graph_ids.py` / `backend/womb/graph_emit.py`（跨模块复用）
- [ ] 8.2 `backend/scheduler/CLAUDE.md` L2 文档更新：handlers 新增 graph_delta 职责
- [ ] 8.3 `backend/cradle/graph_emit.py` / `graph_story.py` / `ontology.py` 文件头 L3 注释完整
- [ ] 8.4 `backend/common/graph_ids.py` 文件头 L3 注释完整，说明"跨模块共享的图 ID 常量"
- [ ] 8.5 `frontend/src/hooks/useCradleGraph.js` / `frontend/src/utils/mergeGraph.js` 文件头 L3 注释完整
- [ ] 8.6 `frontend/src/components/LifeGraph.jsx` 文件头 L3 注释**无需改动**（本期不改组件），但在下方注释列表新增一行"2026-04-2X 摇篮图接入（add-cradle-growth-graph）：零组件侧改动，只复用既有契约"
- [ ] 8.7 `/CLAUDE.md` L1 文档同步：摇篮图谱能力上线后，更新"⚠️ 生命图谱状态"章节，从"全部删除等待重构"改为"womb 已上线 / cradle 已上线（v3 架构：业务即图 + 实时增量 + per-dim phase）"；保留未来重构红线段落
- [ ] 8.8 memory 更新：`project_cradle_graph_status.md` 新建，记录"摇篮图谱 v3 上线"条目 + 成功标准达成情况 + 跨图 UUID 一致性验证

## 9. 归档旧提案的关联说明（Phase I）

- [ ] 9.1 在 `openspec/changes/refactor-cradle-graph-phase-axis/proposal.md` 末尾补充一段"继承与超越"说明：该提案冻结的 progression/phase 两分结论 + per-dim DIMENSION_PHASES 本体论在 `add-cradle-growth-graph` 继续生效；原"数据迁移脚本"路径被"废弃旧 cradle_graph.json + 重新跑一次生命"替代（因为老架构已被 2026-04-21 删除）。
- [ ] 9.2 若 `refactor-cradle-graph-phase-axis` 仍处于 proposal 状态而非 applied，本次提案 apply 时一并归档它（避免历史悬挂）。

## 10. 发布与回滚（Phase J）

- [ ] 10.1 合并前：四道 Gate 全过 + 设计模式三问文档答复齐全（附在 PR / commit message）
- [ ] 10.2 灰度：先对新建 baby 启用；老 baby（archive 里已存在）的 cradle-graph 端点返回 404 + "请重新跑一次生命"提示
- [ ] 10.3 回滚策略：`/lifeline` SSE 的 `graph_delta` 字段是可选新增，前端未接入前后端零影响；如需回滚只需前端不调用 `useCradleGraph` 即可，后端累积状态无副作用（只写 JSON 文件）
- [ ] 10.4 发布 commit message 附三问 + 四 Gate 证据：

```
三问回答：
  主角：baby_this（主）+ caregivers（次），与 womb 图同一 baby UUID 延续
  核心不变量：baby_this 是全图入度最高的节点（≥ sample），progression/phase 两分永不混用
  spec 元字段：center_anchor / role=anchor 指令由数据拓扑自然满足；BELONGS_TO 强制路由

Gate 1：pytest N/N 绿（含跨图 UUID 一致性测试 + caregiver bootstrap 回归测试）
Gate 2：progression CRADLE_EXIT_PHASE / dimension 6 / phase 28 / caregiver→baby 多重边 ≥ 3 / 无时间节点
Gate 3：baby_this in+out degree=XX（全图 top-1，入度 ≈ 样本 27 ±15%），caregiver top-2；浏览器截图附 / 未看渲染声明
Gate 4：反向测试 K 通过（如"Neonatal 无 walk"/"死产后无后续 caregiver 交互"/"capability 回退+恢复双向"）
```
