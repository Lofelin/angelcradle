# 任务清单：long-term-memory

> 三问过滤：每个任务动手前自检——真实需求？有更简的方案？会破坏什么？

## 1. memory/ 模块骨架

- [ ] 1.1 创建 `backend/memory/` 目录 + `__init__.py` + `CLAUDE.md`（L2 文档）
- [ ] 1.2 `schema.sql`：memory_episodic / memory_semantic 两表 DDL
- [ ] 1.3 `store.py`：SQLite 连接池（单库单 baby：`archive/{baby_id}/memory.db`）+ 建表 + upgrade 幂等
- [ ] 1.4 `store.py`：CRUD 函数（insert_episodic / list_episodic / insert_semantic / update_forget_score / archive）
- [ ] 1.5 `embedder.py`：sentence-transformers 单例（延迟加载 + 磁盘缓存模型权重到 `archive/_cache/`）
- [ ] 1.6 `embedder.py`：`embed(text) -> np.ndarray` + `cosine(a, b) -> float`

## 2. 写入路径（Selective Ingestion）

- [ ] 2.1 `ingest.py`：`compute_novelty(embedding, recent_embeddings) -> float`
- [ ] 2.2 `ingest.py`：`should_ingest(memory, novelty) -> bool`（强制入库白名单 + 闸门）
- [ ] 2.3 `ingest.py`：`ingest(baby_id, memory, state) -> bool` 主入口，写 SQLite
- [ ] 2.4 `nanny.py`：`_snapshot_state` 后调 `memory.ingest`，旧 `state.memory.append` 保留
- [ ] 2.5 单测：`test_ingest_filter.py` 覆盖低强度丢弃 / 关键事件强制入库 / 新颖性过滤

## 3. 读取路径（Progressive Retrieval）

- [ ] 3.1 `retrieval.py`：`semantic_hits(baby_id, current_tags, budget)` 标签加权 + top_k
- [ ] 3.2 `retrieval.py`：`episodic_hits(baby_id, query_emb, current_tags, budget)` 向量余弦 + KG 2-hop 合并
- [ ] 3.3 `retrieval.py`：`sensory_refs(baby_id, budget)` 读 `events.jsonl` 最近 N 条
- [ ] 3.4 `retrieval.py`：`recall(baby_id, context, current_tags, token_budget) -> RecalledContext` 主入口
- [ ] 3.5 `retrieval.py`：`estimate_tokens(text)` 简易 token 估算（中文 1 char ≈ 1 token，英文按 /4）
- [ ] 3.6 单测：`test_retrieval.py` 覆盖预算裁剪 / 优先级排序 / 空库 fallback

## 4. 巩固路径（Consolidation）

- [ ] 4.1 `consolidation.py`：`decay_forget_scores(baby_id, current_age_days)` 批量更新
- [ ] 4.2 `consolidation.py`：`archive_low_score(baby_id, threshold=0.1)` 软归档
- [ ] 4.3 `consolidation.py`：`cluster_and_merge(baby_id, phase, sim_threshold=0.85)` 合并近似记忆到 semantic pattern
- [ ] 4.4 `consolidation.py`：`promote_phase_summary(baby_id, phase, summary_text, source_ids)` 登记阶段要点
- [ ] 4.5 `consolidation.py`：`consolidate(baby_id, phase, sim_time) -> ConsolidationReport` 主入口
- [ ] 4.6 `scheduler` 睡眠事件分支调用 `memory.consolidate`，写入 `memory_consolidation` 事件到 `events.jsonl`
- [ ] 4.7 `mind.generate_phase_summary` 后调用 `promote_phase_summary` 固化到 semantic 层

## 5. KG 关联检索（复用 cradle_graph_store）

- [ ] 5.1 `cradle_graph_store.py`：`query_associative(baby_id, tags, hops=2)` BFS 实现
- [ ] 5.2 `cradle_graph_store.py`：返回 `GraphHit(node, path, distance)` 结构，便于 retrieval 合并
- [ ] 5.3 更新 `cradle/cradle_graph_store.py` 的 L3 头部注释（OUTPUT 增加 query_associative）
- [ ] 5.4 单测：`test_graph_query.py` 覆盖 1-hop / 2-hop / 标签不存在 / 环路

## 6. mind.py 接入（三个 LLM 入口）

- [ ] 6.1 `mind.generate_interaction_response`：recall 替换"最近 K 条"注入
- [ ] 6.2 `mind.process_critical_event`：同上
- [ ] 6.3 `mind.narrate_phase_events`：同上
- [ ] 6.4 保留旧分支通过 env 开关 `MEMORY_V2=off` 回退（灰度控制）
- [ ] 6.5 prompt 模板新增 `<memory_semantic>` / `<memory_episodic>` / `<memory_graph>` 三块标签

## 7. 向后兼容与迁移

- [ ] 7.1 `BabyState` 增加 `memory_index_version: int = 0` 字段
- [ ] 7.2 `load_state` 后检查 version，=0 则投递一个后台 task 走 `ingest_legacy(baby_id)`
- [ ] 7.3 `ingest_legacy`：遍历 `state.memory` 逐条走 ingest（bypass selective 闸门），写完升 version=1
- [ ] 7.4 单测：`test_backward_compat.py` 覆盖空 memory / 正常 list / 损坏 JSON 场景
- [ ] 7.5 手工验证：加载一个已有 baby（`AC-20260417-14226`），观察 memory.db 生成和索引完整

## 8. 生物同构参数

- [ ] 8.1 `memory/forget_params.py`：12 阶段 `TAU_BY_PHASE` 查表
- [ ] 8.2 `memory/forget_params.py`：`EMOTIONAL_BOOST_CURVE` 情感抗遗忘系数
- [ ] 8.3 `memory/forget_params.py`：`CONSOLIDATION_THRESHOLDS`（archive / merge / promote 各阈值）
- [ ] 8.4 README/注释说明参数依据（Ebbinghaus 遗忘曲线 + infantile amnesia 文献）

## 9. 性能与可观测性

- [ ] 9.1 `llm_log.py` 或新增 `memory_log.py`：记录每次 recall 的 (used_tokens, hits_count, latency_ms)
- [ ] 9.2 `memory/__init__.py`：暴露 `stats(baby_id) -> dict` 供调试（episodic_count / semantic_count / archived_count）
- [ ] 9.3 加一个 `scripts/memory_inspect.py` CLI：列印某 baby 的记忆分布（调试用）

## 10. 文档与规范

- [ ] 10.1 `backend/memory/CLAUDE.md`（L2）：成员清单 / 对外暴露 / 依赖关系 / 数据流
- [ ] 10.2 `backend/CLAUDE.md`（L1）：目录树增加 `memory/`
- [ ] 10.3 `cradle/CLAUDE.md`（L2）：依赖关系新增 `memory/`，说明 nanny / mind 的接入
- [ ] 10.4 所有新建 Python 文件顶部添加 L3 契约注释（`[INPUT] / [OUTPUT] / [POS] / [PROTOCOL]`）
- [ ] 10.5 `openspec/project.md` 或项目技术栈文档：记录新依赖（sentence-transformers / sqlite-vss）

## 11. 验证基线

- [ ] 11.1 端到端手工跑：`conceive` → `admit` → 跑完 3 个阶段 → 观察 `memory.db` 条目变化
- [ ] 11.2 对比实验：同一个 baby 用 MEMORY_V2=on/off 各跑一次，记录 prompt token 差异
- [ ] 11.3 遗忘验证：快进时间 30 天，确认低强度记忆 forget_score 明显下降、高强度保留
- [ ] 11.4 巩固验证：触发夜睡事件，确认 episodic 归档 + semantic 新增
- [ ] 11.5 recall 关联验证：当前事件含 `fear:stranger`，检查 KG 2-hop 能否找到旧"陌生人靠近"记忆

## 优先级建议（按阶段交付）

**Phase A（基础能力，可跑）**：1 → 2 → 6 → 7（跳过 selective 闸门的最简版）
**Phase B（核心收益）**：3 → 5（检索和图关联真正替代朴素注入）
**Phase C（生物同构）**：4 → 8（遗忘 + 巩固 + 参数化）
**Phase D（可观测 + 验证）**：9 → 10 → 11

## 死罪清单（禁止触碰）

- [ ] 禁止改 `events.jsonl` 结构或删除任何旧事件——它是日志即真相
- [ ] 禁止删除 `BabyState.memory` list——向后兼容铁律
- [ ] 禁止引入 Milvus / Redis / 任何需要独立进程的组件
- [ ] 禁止用 GPT-4o 做实体抽取——`causality.py` 已提供零 LLM 方案
- [ ] 禁止在任何 task 分支合并前留下缺失的 L2/L3 文档（FATAL-002/FATAL-004）
