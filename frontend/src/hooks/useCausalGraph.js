/**
 * [INPUT]: graphState (from graphReducer), graphDispatch
 * [OUTPUT]: traceUpstream(), addNodesFromSSE(), addEdgesFromSSE(), stats
 * [POS]: 因果图数据管理 hook，SSE 事件收集 + BFS 追溯 + 批量合并
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */
import { useCallback, useRef, useMemo } from 'react'

// ── graphReducer ─────────────────────────────────
// 放在 hook 文件中导出，供 App.jsx 顶层使用

export const GRAPH_INITIAL = {
  nodes: new Map(),       // id -> Node
  edges: [],              // Edge[]
  filter: null,           // null = 全部, Set<group> = 过滤
  showLabels: false,      // 边标签开关，默认关闭（参考 MiroFish 风格）
  highlight: null,        // null | { nodes: Set, edges: Set }
}

export function graphReducer(state, action) {
  switch (action.type) {
    case 'ADD_NODES': {
      const now = Date.now()
      const newNodes = new Map(state.nodes)
      for (const node of action.payload) {
        if (!node.id) continue
        const existing = newNodes.get(node.id)
        newNodes.set(node.id, { ...node, __addedAt: existing?.__addedAt ?? now })
      }
      return { ...state, nodes: newNodes }
    }
    case 'ADD_EDGES': {
      const now = Date.now()
      const keyOf = e => `${e.source}->${e.target}:${e.type}`
      const existingIds = new Set(state.edges.map(keyOf))
      const newEdges = action.payload
        .filter(e => !existingIds.has(keyOf(e)))
        .map(e => ({ ...e, __addedAt: now }))
      if (newEdges.length === 0) return state
      return { ...state, edges: [...state.edges, ...newEdges] }
    }
    case 'REMOVE_NODES': {
      const removeIds = new Set(action.payload)
      const keptNodes = new Map()
      for (const [id, node] of state.nodes) {
        if (!removeIds.has(id)) keptNodes.set(id, node)
      }
      const keptEdges = state.edges.filter(
        e => !removeIds.has(e.source) && !removeIds.has(e.target)
      )
      return { ...state, nodes: keptNodes, edges: keptEdges }
    }
    case 'CLEAR_GRAPH':
      return { ...GRAPH_INITIAL }
    case 'LOAD_GRAPH': {
      // 从后端加载完整图谱：payload = { nodes: [...], links: [...] }
      const now = Date.now()
      const loadedNodes = new Map()
      for (const node of (action.payload.nodes || [])) {
        if (!node.id) continue
        loadedNodes.set(node.id, { ...node, __addedAt: now })
      }
      const loadedEdges = (action.payload.links || []).map(e => ({
        ...e, __addedAt: now,
      }))
      return { ...GRAPH_INITIAL, nodes: loadedNodes, edges: loadedEdges }
    }
    case 'SET_FILTER': {
      const group = action.payload
      if (!group) return { ...state, filter: null }
      const newFilter = new Set(state.filter || [])
      if (newFilter.has(group)) {
        newFilter.delete(group)
        return { ...state, filter: newFilter.size === 0 ? null : newFilter }
      }
      // 首次点击：创建完整集合并移除当前 group（反选逻辑）
      if (!state.filter) {
        const all = new Set()
        for (const [, n] of state.nodes) all.add(n.group)
        all.delete(group)
        return { ...state, filter: all }
      }
      newFilter.add(group)
      return { ...state, filter: newFilter }
    }
    case 'TOGGLE_LABELS':
      return { ...state, showLabels: !state.showLabels }
    case 'SET_HIGHLIGHT':
      return { ...state, highlight: action.payload }
    case 'TRACE_NODE': {
      // BFS 上游追溯
      const nodeId = action.payload
      if (!nodeId) return { ...state, highlight: null }
      const visitedNodes = new Set()
      const visitedEdges = new Set()
      const queue = [nodeId]
      while (queue.length > 0) {
        const current = queue.shift()
        if (visitedNodes.has(current)) continue
        visitedNodes.add(current)
        for (const edge of state.edges) {
          if (edge.target === current) {
            visitedEdges.add(`${edge.source}->${edge.target}:${edge.type}`)
            if (!visitedNodes.has(edge.source)) queue.push(edge.source)
          }
        }
      }
      return { ...state, highlight: { nodes: visitedNodes, edges: visitedEdges } }
    }
    default:
      return state
  }
}

// ── Hook ──────────────────────────────────────────
export function useCausalGraph(graphState, graphDispatch) {
  const batchRef = useRef({ nodes: [], edges: [], timer: null })

  // 批量合并（100ms 窗口）
  const flushBatch = useCallback(() => {
    const batch = batchRef.current
    if (batch.nodes.length > 0) {
      graphDispatch({ type: 'ADD_NODES', payload: batch.nodes })
      batch.nodes = []
    }
    if (batch.edges.length > 0) {
      graphDispatch({ type: 'ADD_EDGES', payload: batch.edges })
      batch.edges = []
    }
    batch.timer = null
  }, [graphDispatch])

  const scheduleBatch = useCallback(() => {
    if (!batchRef.current.timer) {
      batchRef.current.timer = setTimeout(flushBatch, 100)
    }
  }, [flushBatch])

  // 从 SSE 事件添加节点
  const addNodesFromSSE = useCallback((nodes) => {
    batchRef.current.nodes.push(...nodes)
    scheduleBatch()
  }, [scheduleBatch])

  // 从 SSE 事件添加边
  const addEdgesFromSSE = useCallback((edges) => {
    batchRef.current.edges.push(...edges)
    scheduleBatch()
  }, [scheduleBatch])

  // 追溯
  const traceUpstream = useCallback((nodeId) => {
    graphDispatch({ type: 'TRACE_NODE', payload: nodeId })
  }, [graphDispatch])

  // 清除高亮
  const clearHighlight = useCallback(() => {
    graphDispatch({ type: 'SET_HIGHLIGHT', payload: null })
  }, [graphDispatch])

  // 统计
  const stats = useMemo(() => ({
    nodes: graphState.nodes.size,
    edges: graphState.edges.length,
  }), [graphState.nodes.size, graphState.edges.length])

  return {
    addNodesFromSSE,
    addEdgesFromSSE,
    traceUpstream,
    clearHighlight,
    stats,
  }
}
