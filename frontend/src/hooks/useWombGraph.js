/**
 * [INPUT]: 通过 applyEvent(data) 喂入 SSE 事件; 外部 reset() 清空
 * [OUTPUT]: 导出 useWombGraph() hook, 返回 { nodes, edges, applyEvent, reset }
 * [POS]: hooks/ 的子宫图谱实时状态管理, 被 App.jsx 消费, 对应 add-womb-conception-graph 提案 Phase E
 * [PROTOCOL]: 变更时更新此头部, 然后检查 CLAUDE.md
 *
 * 设计原则（见 openspec/changes/add-womb-conception-graph/design.md §5）:
 *   - graph_delta 四种原子操作: add_nodes / add_edges / update_nodes / update_edges / remove_nodes / remove_edges
 *   - metadata 深合并（保留前值 + 后值覆盖）
 *   - metadata.track_append 特殊处理: 追加样本点到 track 数组
 *   - add 幂等: 同 id 节点后 add 覆盖前 add
 *   - remove_nodes 级联删边 (以该节点为端点的边自动清除)
 *   - 缺失 graph_delta 字段的事件静默跳过, 不 crash
 */
import { useCallback, useMemo, useState } from 'react'
import { mergeGraph, EMPTY_STATE } from '../utils/mergeGraph'

// re-export 保持旧引用路径兼容（如果外部模块 import 了 useWombGraph 的 mergeGraph）
export { mergeGraph }

export function useWombGraph() {
  const [state, setState] = useState(EMPTY_STATE)

  // 处理任意 SSE 事件: 识别两种来源
  //   1) api/conceive.py 直接 yield (init)   → { event: 'graph_delta', graph_delta: ... }
  //   2) stages.py yield → api 包一层 event:'stage' → { event: 'stage', status: 'graph_delta', graph_delta: ... }
  const applyEvent = useCallback((data) => {
    if (!data || !data.graph_delta) return
    const isGraphDelta =
      data.event === 'graph_delta' || data.status === 'graph_delta'
    if (!isGraphDelta) return
    const delta = data.graph_delta
    // 调试日志（开发期保留，生产期可删）
    // eslint-disable-next-line no-console
    console.log('[wombGraph]', data.phase || 'stage', {
      add_nodes: delta.add_nodes?.length || 0,
      add_edges: delta.add_edges?.length || 0,
      update_nodes: delta.update_nodes?.length || 0,
      remove_nodes: delta.remove_nodes?.length || 0,
      error: data.error,
    })
    setState(prev => mergeGraph(prev, delta))
  }, [])

  const reset = useCallback(() => setState(EMPTY_STATE), [])

  // 载入完整快照 (后端 /baby/{id}/womb-graph 返回的 {nodes, edges}) - 用于查看历史宝宝
  const loadSnapshot = useCallback((graph) => {
    if (!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
      setState(EMPTY_STATE)
      return
    }
    setState({ nodes: graph.nodes, edges: graph.edges })
  }, [])

  // useMemo 稳定对象 identity，避免消费端把整个返回值当依赖时死循环。
  return useMemo(
    () => ({ nodes: state.nodes, edges: state.edges, applyEvent, reset, loadSnapshot }),
    [state.nodes, state.edges, applyEvent, reset, loadSnapshot]
  )
}
