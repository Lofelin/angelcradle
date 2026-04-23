/**
 * [INPUT]: state { nodes: Node[], edges: Edge[] }, delta (graph_delta 四原子操作对象)
 * [OUTPUT]: 导出 mergeGraph(state, delta) 纯函数 + EMPTY_STATE 常量
 * [POS]: utils/ 的共享图状态 reducer，被 hooks/useWombGraph.js 与 hooks/useCradleGraph.js 共同引用
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 *
 * 共享语义
 * ========
 * 提案 add-womb-conception-graph 与 add-cradle-growth-graph 共用同一 delta schema:
 *   add_nodes / add_edges / update_nodes / update_edges / remove_nodes / remove_edges
 *
 * 合并规则（与后端 cradle/graph_emit.py apply_delta 行为一致）:
 *   - add 幂等: 同 id 节点后 add 覆盖前 add
 *   - update_nodes: 浅合并 + metadata 深合并 + track_append 追加到 track 数组
 *   - update_edges: 浅合并
 *   - remove_nodes: 级联删除所有以该节点为端点的边
 *   - 缺 id / 缺 uuid 的 patch 静默跳过
 *
 * 本文件以前内嵌在 useWombGraph.js; add-cradle-growth-graph 把它抽成共享工具，
 * useWombGraph.js 改为 re-export, 零行为破坏。
 */

export const EMPTY_STATE = { nodes: [], edges: [] }

/** 把 graph_delta 合并到当前图状态。返回新对象（不改旧对象）。 */
export function mergeGraph(state, delta) {
  if (!delta) return state
  const nodes = new Map(state.nodes.map(n => [n.id, n]))
  const edges = new Map(state.edges.map(e => [e.uuid, e]))

  // add_nodes
  for (const n of delta.add_nodes || []) {
    if (n && n.id) nodes.set(n.id, n)
  }
  // add_edges
  for (const e of delta.add_edges || []) {
    if (e && e.uuid) edges.set(e.uuid, e)
  }

  // update_nodes — 浅合并 + metadata 深合并 + track_append 特殊语义
  for (const patch of delta.update_nodes || []) {
    if (!patch || !patch.id) continue
    const cur = nodes.get(patch.id)
    if (!cur) continue
    const nextMeta = { ...(cur.metadata || {}) }
    if (patch.metadata) {
      for (const [k, v] of Object.entries(patch.metadata)) {
        if (k === 'track_append' && v && typeof v === 'object') {
          const track = Array.isArray(nextMeta.track) ? [...nextMeta.track] : []
          track.push(v)
          nextMeta.track = track
        } else {
          nextMeta[k] = v
        }
      }
    }
    nodes.set(patch.id, { ...cur, ...patch, metadata: nextMeta })
  }

  // update_edges
  for (const patch of delta.update_edges || []) {
    if (!patch || !patch.uuid) continue
    const cur = edges.get(patch.uuid)
    if (!cur) continue
    edges.set(patch.uuid, { ...cur, ...patch })
  }

  // remove_nodes + 级联删边
  for (const id of delta.remove_nodes || []) {
    nodes.delete(id)
    for (const [u, e] of edges) {
      if (e.source === id || e.target === id) edges.delete(u)
    }
  }
  // remove_edges
  for (const u of delta.remove_edges || []) edges.delete(u)

  return { nodes: [...nodes.values()], edges: [...edges.values()] }
}
