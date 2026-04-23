/**
 * [INPUT]: 通过 applyEvent(data) 喂入 SSE 事件；loadSnapshot(graph) 注入完整快照；reset() 清空
 * [OUTPUT]: 导出 useCradleGraph() hook，返回 { nodes, edges, applyEvent, reset, loadSnapshot }
 * [POS]: hooks/ 的摇篮图谱实时状态管理，被 Cradle.jsx / App.jsx 消费，
 *        对应 add-cradle-growth-graph 提案 Phase F
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 *
 * 设计原则（见 openspec/changes/add-cradle-growth-graph/design.md §7）:
 *   - delta 四种原子操作由共享工具 utils/mergeGraph 处理，与 useWombGraph 行为同构
 *   - applyEvent 从 lifeline SSE 事件中抽取 graph_delta 并 merge（字段缺失静默跳过）
 *   - loadSnapshot 接受后端 /baby/{id}/cradle-graph 返回的完整快照 {nodes, edges}
 *     作为初始化态（session 重连或查看历史宝宝时使用）
 *   - 不触发 SSE 连接自身；SSE 订阅由 useLifeline 负责（通过 onEvent 数组 fan-out）
 */
import { useCallback, useMemo, useState } from 'react'
import { mergeGraph, EMPTY_STATE } from '../utils/mergeGraph'

export function useCradleGraph() {
  const [state, setState] = useState(EMPTY_STATE)

  /**
   * 处理任意 lifeline SSE 事件——识别两种来源：
   *   1) scheduler/handlers 直接在 payload 里塞 graph_delta
   *   2) nanny / initiative_needs 透传的 event 里挂 graph_delta
   * 判据：事件里有 graph_delta 对象字段即处理，不卡 event 名。
   */
  const applyEvent = useCallback((data) => {
    if (!data || typeof data !== 'object') return
    const delta = data.graph_delta
    if (!delta || typeof delta !== 'object') return
    setState(prev => mergeGraph(prev, delta))
  }, [])

  const reset = useCallback(() => setState(EMPTY_STATE), [])

  /**
   * 载入完整快照 (后端 /baby/{id}/cradle-graph 返回的 {nodes, edges}).
   * 用于初次进入宝宝页面时从落库快照恢复图谱，之后 applyEvent 在此基础上增量。
   */
  const loadSnapshot = useCallback((graph) => {
    if (!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
      setState(EMPTY_STATE)
      return
    }
    setState({ nodes: graph.nodes, edges: graph.edges })
  }, [])

  // useMemo 稳定返回对象的 identity：同一份 state 下只返回同一个对象，
  // 避免消费端（Cradle.jsx 等）误把它当作 useCallback/useEffect 依赖后出现
  // "每次 render 都新对象 → SSE 连接反复重建" 的死循环。
  return useMemo(() => ({
    nodes: state.nodes,
    edges: state.edges,
    applyEvent,
    reset,
    loadSnapshot,
  }), [state.nodes, state.edges, applyEvent, reset, loadSnapshot])
}
