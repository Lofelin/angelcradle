# 变更提案：生命体长期记忆系统（Long-Term Memory）

## 动机

当前摇篮中的"记忆"是一个线性增长的 `Memory` list，写入即沉睡——没有检索、没有遗忘、没有巩固。
LLM 每次做反应时只能简单塞最近 K 条，既超 token 预算又破坏仿真真实性：一个机器人不会"忘记"。
真正的生命体必须有记忆层级，像人一样：有要点（我怕蜘蛛）、有情节（上周五被蛛吓到）、有原始感知（那天几点、谁在场）。

本提案借鉴 [Omni-SimpleMem](https://arxiv.org/html/2604.01007) 的**记忆架构思想**（MAU / Selective Ingestion / Progressive Retrieval / Knowledge Graph），
**本土化**改造成符合婴幼儿发育生物学的三层记忆栈，复用现有 `Memory` / `events.jsonl` / `cradle_graph_store.py`。

### 现有问题

1. **线性增长无上限**：`BabyState.memory` 跑完 12 阶段必然爆 LLM context window
2. **朴素注入**：`mind.py` 往 prompt 里塞"最近 K 条"而非"最相关 K 条"，既浪费 token 又不真实
3. **因果图只写不查**：`cradle_graph_store.py` 的六层 KG 已在写入，从未被 `recall` 消费
4. **无遗忘曲线**：婴儿记忆应遵循 infantile amnesia（新生儿 τ≈3 天），现在是完美持久——这是"机器人记忆"
5. **无巩固机制**：睡眠状态已建模但未触发记忆压缩，浪费了天然的生物同构钩子
6. **关键事件与日常事件权重相同**：高情感强度的经历不应该和刷牙一样平等存储

## 目标

- 将 `Memory` 从 list 升级为可检索、可遗忘、可巩固的三层栈（Semantic / Episodic / Sensory）
- LLM prompt 注入从"最近 K 条"改为"基于当前上下文最相关 K 条"
- 记忆动态符合婴幼儿发育生物学（遗忘曲线随阶段变化、睡眠巩固、情感放大）
- 复用 `cradle_graph_store` 做关联检索，不新增 KG 基础设施
- 不引入重型依赖（不用 Milvus / 不用 GPT-4o 做实体抽取）
- 向后兼容：旧 `BabyState.memory` list 保留，新字段采用可选追加

## 范围

### 包含

- 新增 `backend/memory/` 模块（L2 文档同构）
- 三层记忆栈：Semantic（阶段要点）/ Episodic（Memory + 向量）/ Sensory（`events.jsonl`）
- Selective Ingestion：新颖性 + 强度双闸门
- Progressive Retrieval：金字塔检索（summary → episodic → raw），自动 token 预算裁剪
- Forgetting curve：`forget_score = intensity * e^(-Δdays/τ)`，τ 按阶段查表
- 睡眠触发的记忆巩固（低分条目归档/合并到 semantic 层）
- 本地嵌入（sentence-transformers `all-MiniLM-L6-v2`，80MB，CPU 可用）
- SQLite + vss 扩展做向量存储（单 baby 单库，无中心化服务）
- `cradle_graph_store` 新增 `query_associative(tag, hops=2)` 做图关联检索
- `mind.py` 记忆注入策略替换（生成回应 / 阶段总结 / 关键事件处理 3 个 LLM 入口）
- `scheduler` 睡眠事件处理器调用巩固

### 不包含

- 多模态嵌入（当前记忆无图像/音频信号，不提前建）
- 跨 baby 的共享记忆/集体记忆（属于"世界层"话题，下一个提案）
- LLM-based 记忆重写/幻想（违反"代码是给机器运行"原则，生物不会篡改自己的记忆）
- 记忆导出 / 可视化 UI（观察可用 CLI 脚本，前端留到后续）
- 自动 benchmark 评估（Omni-SimpleMem 论文那套 F1 评估不适用于此仿真）

## 成功标准

- LLM 上下文中的记忆 token 数稳定在预算内（目标 ≤ 1500 tokens），不再随成长线性膨胀
- 同一个 baby 跨阶段重新遭遇"陌生人靠近"时，`mind.py` 能检索到先前相似记忆并注入
- 低强度日常事件（喝奶、刷牙）3 天内被遗忘/合并，高强度事件（关键事件、高情感 valence）持久保留
- 睡眠事件触发后，episodic 层条目数下降（有合并/归档发生）且 semantic 层摘要条数增加
- 不引入 Milvus / Redis / 任何外部服务；所有状态留在 `archive/{baby_id}/` 目录下
- 执行一次 recall 平均耗时 < 50ms（本地嵌入 + SQLite 查询）
- 旧 baby JSON 能直接加载，首次查询时懒触发索引重建（向后兼容铁律）

## 非目标（明确拒绝）

- **不做**自动优化代码的 autoresearch loop——那是 Omni-SimpleMem 的原始场景，不是我们的
- **不做**完全忠于论文的 MAU / 多模态原子单元——你的记忆是结构化文本 + 标签，硬凑多模态反而增加复杂度
- **不做**跨 baby 的向量库合并——单 baby 单库，保持数据边界清晰
