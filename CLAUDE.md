# Angel Cradle — 世界子宫 × 摇篮 × 自驱动生命

AI 孵化的数字生命模拟：物种蓝图孕育 → 12 阶段成长 → 进入世界
Python FastAPI + React + Vite + D3 + LLM 编排

<directory>
backend/ - 后端引擎（api / womb / cradle / scheduler / events / world / memory / llm / portrait / scenes）
frontend/ - React 观察界面（力导向图谱 + SSE lifeline + 对话系统）
specs/ - 设计文档（causal-graph-engine / autonomous-life / baby-initiative 等）
openspec/ - OpenSpec 变更管理
</directory>

---

## 设计模式先导（Design-Mode Priming）

**铁律：写第一行代码前必须先进入设计模式。执行模式下写出来的代码，必然在拓扑层、语义层反复出错。**

### 两种模式的差别

| 执行模式（失败模式） | 设计模式（必须进入的状态） |
|---|---|
| spec 写什么我实现什么 | spec 想说什么我理解什么 |
| 节点数对了就好 | 节点的关系对了才好 |
| 测试通过了就完成 | 用户拿到能用才完成 |
| 一次改一层 | 先想清楚再动手 |
| 错了用户指，用户指我改 | 错了我先自查，兜底才问用户 |

**执行模式下会 5 次犯不同的错，但根上是同一个错：从未真正理解任务是什么。**

### 进入设计模式的强制三问

任何涉及**数据模型 / schema / 本体论 / 图谱 / 可视化产物**的任务，在写第一行代码前必须回答：

1. **这个产物给谁看？讲什么故事？主角是谁？**
   （一句话说清。答不出 → 还没准备好动手）

2. **如果只能保留 1 条性质，保留哪条？**
   （这条就是**核心不变量**。之后所有设计决策都围绕它做取舍）

3. **spec 的引言 / stats / meta 字段在说什么？哪些字段被忽略了？**
   （最容易漏的：`center_anchor` / `role: anchor` / `radius` / `active_lens` 这类元信息——它们不是装饰，是意图声明）

三个答案必须写进**交付信息或 commit message**。写不出 = 还没准备好动手。

### ⚠️ 生命图谱状态（2026-04-22 起 v3 上线）

**v3 业务即图架构上线** —— womb 与 cradle 两套图共用同一基础设施：UUIDv5 namespace + `baby_this` raw_id 常量 → `baby_this` 节点 UUID 在两张图中字节完全相等，前端可天然跨图合并。

- **womb 图**（`add-womb-conception-graph`）：`backend/womb/graph_emit.py` + `backend/womb/graph_story.py`。业务函数（hormones/nutrients/teratogen/vitals/fate/stages）在产出业务数据的同时返回 `graph_delta`，编排层 `merge_deltas` 聚合塞进 conceive SSE 事件；落库 `archive/{id}/womb_graph.json`（schema=`v3-business-as-graph`）。前端 `useWombGraph` hook 订阅增量。
- **cradle 图**（`add-cradle-growth-graph`）：`backend/cradle/graph_emit.py` + `graph_story.py` + `ontology.py` + `graph_session.py` + `scheduler/graph_hooks.py`。scheduler handlers 在关键事件（phase_start / capabilities_unlocked / milestones / stress_regression / regression_recovery / phase_completed / cradle_complete）通过 `apply_and_attach` 累积 delta + 塞事件 payload，经 lifeline SSE 推送；api/cradle.py `/intervene` 端点在 critical 决议时附加 `RESOLVES` + `ACQUIRES` 边。**概念两分铁律**：`progression:{name}` 是引擎 12 步游标，`phase:{dim}:{stage}` 是 per-dim 发育期（共 31 个），capability/milestone 的 `OCCURS_IN` **MUST** 指向 per-dim phase 不得指向 progression（由 `edge_occurs_in` 内置断言强制）。
- **两个查询端点**：新规范 `GET /baby/{id}/cradle-graph`（由 `api.cradle.baby_router` 暴露），老 `GET /cradle/{id}/graph` 向后兼容转发。对应 womb 侧的 `GET /baby/{id}/womb-graph`。
- **前端**：`frontend/src/utils/mergeGraph.js` 共享 reducer；`useCradleGraph` + `useWombGraph` 两个独立 hook；Cradle.jsx 通过 lifeline SSE fan-out 把 graph_delta 合并到 cradleGraph 本地状态；LifeGraph 组件零改动。
- **archive 里 2026-04-21 前的老 `cradle_graph.json`** 由 schema 版本号守门（`registry.load_cradle_graph` 非 v3 schema 返回 None），端点直接 404 提示"请重新跑一次生命"。

**对 AI 协作者的约束**：v3 已上线不代表可以随意扩展。对图相关的任何新需求，仍需先回答"设计模式先导"三问 + 四 Gate 验证。严禁破坏"实体稳定 / 时间在边上 / 无时间节点 / 概念两分" 四条铁律。扩展新能力 / 新 need trigger 时必须同步补 `ontology.CAPABILITY_DIMENSION_MAP` / `graph_story.NEED_META`，否则会在运行时 raise KeyError。

### 未来重构时的红线（给自己也给 AI）

当用户开始新一轮图谱重构时，必须遵守：

1. **新目录名**：不要再用 `lifegraph`——建议 `graph` 或 `lifegraph_v2`，避免和已删模块的 memory/git 历史混淆
2. **先三问，后写代码**：CLAUDE.md 上方的"设计模式先导"三问必须有书面回答
3. **先做设计文档**：在 `specs/` 下写新 spec 或设计稿，不能直接进代码
4. **中心度由前端负责**：`role: "anchor"` 是前端锚定 self 的指令，不要通过数据拓扑反向造中心——五版事故已经证明那条路走不通
5. **禁止复制已删的 reducer 逻辑**：`memory/project_lifegraph_engine.md` 里的记录是**失败史**，不是参考架构

### 反模式（见过即拒绝）

| 反模式 | 典型表现 | 破解 |
|---|---|---|
| **sample 照抄** | 看到 sample 91 节点就照搬 91 节点，不问"为什么是 91" | 三问第 2 条——核心不变量是什么 |
| **meta 字段无视** | `"center_anchor": "self"` 路过无数次，代码里从未使用 | 三问第 3 条——扫一遍 meta/stats |
| **见树不见林** | 实现了 spec 每个细节，但没实现 spec 的灵魂 | 三问第 1 条——讲的是什么故事 |
| **补丁思维** | 数据层的错误用前端 CSS 修 | 回到核心不变量，问"这是该在哪层解决的问题" |
| **机械同构** | cradle 方案出错了，womb 照搬同一套 | 每个领域重新做三问，不要复制答案 |
| **时间维度缺失** | scaffolding 一次性播所有未来节点，3mo 宝宝看到 18mo 里程碑 | 三问第 1 条——故事是线性推进的 |

### 元规则：理解性错误 vs 防御性错误

- **防御性错误**（忘加断言、漏写边界）→ 四道 Gate 能兜底
- **理解性错误**（根本没搞懂任务是什么）→ Gate 兜不住，只能靠"设计模式先导"前置拦截

**"用户反复指同一个方向的问题"永远是理解性错误**——说明在错误的认知框架里打转。此时不该继续改代码，应该**停下，重新做三问**。

---

## 四道验证关（Four-Gate Verification）

**铁律：pytest 通过 ≠ 做对事。每次重构/新功能必须过四道关，不过就是半成品。**

### Gate 1：代码能跑（pytest 绿）
最低门槛。编译通过、单元测试绿。这是起点，不是终点。

### Gate 2：单元语义对（reducer 输出符合 spec）
对照 spec/sample 逐字段验证：命名空间、边类型、节点分组、continuant 标记是否同构。
`to_force()` 输出的 JSON 能直接 diff sample JSON 的结构吗？

### Gate 3：整体形状对（跑起来后看图像不像 sample）
**这一步最容易被跳过，但最致命**。必须做的动作：
- 打印**完整度数分布**：每个节点的 in-degree / out-degree，排序看 top-10
- 对照 sample 的 `stats` 字段，验证节点总数、边总数、hub 数、continuant 数
- **对于图谱/可视化产物**：启动服务，打开浏览器实际看图。看不了就明确承认"我只验证了后端"

### Gate 4：用户视角对（真实场景下合不合理）
**站到产品使用者的角度反向验证**：
- "3 个月宝宝的图里会不会出现 18 个月的里程碑？" → 如果会，设计错了
- "spec 写 `center_anchor: "self"`，那 self 在跑起来后是不是视觉中心？" → 入度必须 top-1 或 top-3
- 写**反向测试**："不该存在的东西不存在"——不只是"该存在的存在"

### 强制产物

重构/新功能完成时，必须在交付信息里附：

```
三问回答:
  主角: (一句话)
  核心不变量: (一句话)
  spec 元字段: (列出用到的 / 明确忽略的)

Gate 1: pytest N/N 通过 ✅
Gate 2: 节点数 A vs sample B / 边类型 M vs spec N 种
Gate 3: self in-degree=X (全图 top-Y)，完整度数分布见上 / 截图或 "未看渲染"声明
Gate 4: 反向测试 K 个通过（如 "3mo 无 18mo 节点" / "合子期无出生激素"）
```

**缺任一项 = 未完成。不要等用户追问第 N 次才补。**

### 常见失败反模式（见过即拒绝）

| 反模式 | 表现 | 破解 |
|---|---|---|
| **指标盲区** | "节点数 91 对齐了" 但 self in-degree 是 0 | Gate 3 度数分布 |
| **sample 抄袭** | 把 sample 91 节点平铺 scaffolding，忽略"按时间演化" | Gate 4 反向测试 |
| **meta 字段无视** | spec 的 `center_anchor` / `role: anchor` 从未被代码使用 | Gate 2 字段全覆盖 |
| **测试只验存在** | `assert x in nodes`，没有 `assert y not in nodes` | Gate 4 反向断言 |
| **后端绿就收工** | 视觉产物没打开浏览器 | Gate 3 强制截图或声明 |

### 元规则：谁验证 vs 谁交付

**"用户指出问题"永远是降级信号**——说明应该在交付前自己发现，却没发现。
每次用户指出问题，复盘的不是"怎么修"，而是"哪道 Gate 没过 / 哪个三问没做"。

---

## 具体到 lifegraph 图谱的五版事故教训

五次反复修改 womb/cradle reducer，都错在同一点：**没把 self 当作主角来设计**。

- V1/V2：照抄 sample 91 节点，不问"图谱要说什么故事"
- V3：改事件驱动，但还是平铺式思维
- V4：前端打补丁钉 self 到中心（绕过数据问题）
- V5：用户亲自画 15 条直达边才醒悟——**数据拓扑才是视觉中心的根源**

**本项目图谱类任务的红线**：
1. 任何修改 `lifegraph/reducers/*.py` 或 `lifegraph/*_ontology.py` 的 PR，交付信息必须附 `self` 的 in-degree 与全图 top-5 入度对比
2. `self` 不是全图入度最高的节点 = 设计失败，直接回炉
3. 禁止在前端 `LifeGraph.jsx` 用 `fx/fy` 锚点或特殊渲染来"补救"中心感——视觉中心必须从数据拓扑自然涌现

---

[PROTOCOL]: 变更时更新此文档，然后检查子模块 L2 CLAUDE.md 的一致性
