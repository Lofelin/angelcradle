# 评审归档 · long-term-memory

本目录保留 `long-term-memory` spec 三轮评审过程中的关键文档，供未来追溯决策来源。

## 归档清单

| 文件 | 阶段 | 状态 |
|---|---|---|
| `ARCHITECTURE-DRAFT.md` | 第 2 轮（LifeMoment 架构草案，5 方评审后被大改）| 作为"原始提议 v1"留存 |
| `CANDIDATE-FINAL.md` | 第 3 轮（三轮共识基线 + 用户场景验证后的收敛候选）| 作为"共识整合版"留存 |

## 最终正式 spec

见上级目录：
- `../proposal.md`
- `../design.md`
- `../tasks.md`

## 评审轨迹

| 轮次 | 日期 | 评审 agent | 结论 |
|---|---|---|---|
| 1 | 2026-04-17 | 5 方（Linus / 兼容 / 科学 / 性能 / 反方） | 原大方案冗余 70%，降级为 Phase 0 |
| 2 | 2026-04-17 | 5 方（好品味 / 数据模型 / 迁移 / 领域 / 反方） | LifeMoment 草案 NOT 可执行，需大改 |
| 3 | 2026-04-17 | 3 方（D1 重构判决 / D2 Omni-SimpleMem 对齐 / D3 共识核对） | 混合（倾向重构）可执行 + 11 处补强 |
| 用户场景验证 | 2026-04-17 | "讨论上学" | 否决三 dataclass 并列方案，确立统一原子 + 无 kind |

## 十一条共识锚点（正式 spec 必须兑现）

C1 主动行为进记忆 / C2 不引 SQLite/嵌入 / C3 禁破坏性迁移 / C4 严格复用 causality.py tags /
C5 cradle_graph 不碰 / C6 phase_summaries 独立保持 / C7 forget_score 公式显式化 /
C8 append-only / C9 Milestone 独立 dataclass / C10 接入点全量覆盖 / C11 已归档 spec 兼容矩阵

## 三组补强（正式 spec 必须整合）

- **D1 架构安全 5 条**：record_moment 单写入口 / V2=on 降级回写 / rebuild_all_tags 双源 / 写顺序约定 / 四象限测试 + 终结 spec 编号
- **D2 Omni 对齐 3 条**：Jaccard 新颖性闸门 / recall token_budget / tag 一跳倒排
- **D3 共识回补 5 条**：C1 pending 不回改 / C4 tag 示例真实化 / C7 公式和 τ 表 / C10 补行号+前端 / C11 兼容矩阵
