# v1-deferred — 延伸目标归档

本目录下的三份文档（proposal.md / design.md / tasks.md）是 2026-04-17 经 5 方并行评审后**主动归档**的早期大方案。

## 归档原因

评审发现核心冗余度约 70%，主要问题：

1. **臆想需求**：方案动机"LLM context 会爆"是臆想——实际 `mind.py:314/554/757` 已写死 `memories[-3:]`，每次注入 ~600 token，远低于 1500 预算
2. **事实错误**：全文将 `state.memories` 误写为 `state.memory`；迁移路径未考虑 `AC-20260417-14226` 这类无 `state.json` 的 baby
3. **盲点**：`BabyState.phase_summaries: list[dict]` 已作为 semantic 层持久化（`state.py:469`），方案凭空新建 `memory_semantic` 表属于造轮子
4. **过度设计**：为 0-4 条记忆规模的系统引入 SQLite + sentence-transformers + 双表 schema + consolidation 聚类，违反"先写最简单能运行的实现"铁律
5. **性能高估**：MiniLM-L6 CPU 实测 15-35ms（方案声称 10ms），且 blocking asyncio 未处理
6. **科学偏差**：遗忘曲线、情感 boost、睡眠巩固的建模形式与婴幼儿记忆神经科学主流文献不符

正式方案已降级为 Phase 0 最小可行版（≤ 200 行，零新依赖），见上级目录的 proposal.md / design.md / tasks.md。

## 何时回看本目录

以下任一**有数据支撑的**信号出现时，重新评估引入 v1 组件：

- Phase 0 的 Jaccard + trace 标签召回被证实**跨阶段语义泛化不足**（观察 2 周后 bad case 归因）
- 单 baby `memories` 条数稳定超过 2000 条（当前 AC-20260417-14297 只有 4 条）
- 出现真实下游消费者需要 `cradle_graph_store.query_associative` 多跳关联
- LLM prompt 注入 token 实测超过预算

触发后可参考本目录的 §3 数据模型、§4 算法设计作为升级路径参考，但**神经科学参数**（arousal/valence 拆分、Wickelgren 幂律、REM/SWS 区分）已由领域评审补充，实施时需一并纳入。

## 参考文献（评审产出）

- Josselyn & Frankland (2012). Infantile amnesia: a neurogenic hypothesis.
- Akers et al. (2014). Hippocampal neurogenesis regulates forgetting.
- Wixted & Carpenter (2007). Wickelgren Power Law.
- Friedrich et al. (2015). Timely sleep facilitates declarative memory consolidation in infants. PNAS.
- Kensinger & Corkin (2004). Two routes to emotional memory. PNAS.
- Canada et al. (2025). Pattern separation and completion in early childhood. PNAS.
- Hayne (2004). What infant memory tells us about infantile amnesia.
