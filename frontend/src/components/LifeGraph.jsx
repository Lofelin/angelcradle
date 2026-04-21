/**
 * [INPUT]: nodes (Map<id,node> | array), edges (array), fullscreen, onToggleFullscreen
 * [OUTPUT]: 力导向关系图（D3 SVG）—— 视觉沿用 MiroFish/GraphPanel.vue
 * [POS]: 三页面（子宫/摇篮/世界）共用
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 *
 * 视觉参数：
 *   背景：#FAFAFA + 点阵 (#D0D0D0 1.5px, 24px)
 *   节点：r=10 + 白描边 2.5px，选中 #E91E63 4px，hover #333 3px
 *   边：  #C0C0C0 1.5px，高亮 #3498db 3px，自环圆弧，多边均匀曲率
 *   力：  charge -400, link 150+(cnt-1)*50, collide 50, center
 *
 * 2026-04-20 流式重构（脱离 MiroFish 一次性渲染模式）：
 *   · mount 只建一次 svg/simulation，拒绝 svg.selectAll('*').remove() 循环重建
 *   · 数据更新走 D3 join（enter/update/exit），新节点预置中心附近位置
 *   · 长持有 simNode 对象，x/y/vx/vy/fx/fy 跨批次保留，避免冷启动抖动
 *   · alphaDecay 0.05 / velocityDecay 0.55，仿真快速收敛
 *   · 去掉 forceX/Y（与 forceCenter 冗余叠加导致节点振荡）
 *   · colorMap 追加式，旧 type 颜色稳定，新 type 顺序分配
 *   · ResizeObserver 仅更新 viewBox 和 center 力，不重建
 *
 * 数据适配：
 *   node: {id, group, label, narrative, metadata, ...}
 *     → {uuid, name, labels, summary, attributes, rawData}
 *   edge: {source, target, type, weight, description}
 *     → {source_node_uuid, target_node_uuid, fact_type, name, uuid, rawData}
 */
import { useEffect, useMemo, useRef, useState, memo } from 'react'
import * as d3 from 'd3'
import { Maximize2, Minimize2 } from 'lucide-react'
import './LifeGraph.css'

// ── MiroFish 调色板 ─────────────────────────────────────
const PALETTE = [
  '#FF6B35', '#004E89', '#7B2D8E', '#1A936F', '#C5283D',
  '#E9724C', '#3498db', '#9b59b6', '#27ae60', '#f39c12',
]

// ── 组件内置 i18n（读 App 在 localStorage 存的 lang）──────
const I18N = {
  en: { title: 'Graph', toggle: 'Show Edge Labels', empty: 'Waiting for graph data', legend: 'Entity Types', nodeDetail: 'Node Details', edgeDetail: 'Relationship' },
  zh: { title: '图谱', toggle: '显示边标签', empty: '等待图谱数据', legend: '实体类型', nodeDetail: '节点详情', edgeDetail: '关系' },
}
function useLang() {
  const [lang, setLang] = useState(() => {
    try { return localStorage.getItem('lang') || 'en' } catch { return 'en' }
  })
  useEffect(() => {
    const h = () => { try { setLang(localStorage.getItem('lang') || 'en') } catch { /* noop */ } }
    window.addEventListener('storage', h)
    return () => window.removeEventListener('storage', h)
  }, [])
  return lang
}

// ── 数据适配：lifegraph schema → MiroFish shape ──────────
function adaptNodes(nodes) {
  const arr = nodes instanceof Map ? Array.from(nodes.values()) : (nodes || [])
  return arr.map(n => ({
    uuid: n.id,
    name: n.label || 'Unnamed',
    labels: [n.group || 'Entity'],
    attributes: pickAttrs(n),
    summary: n.narrative?.primary?.zh_CN
      || n.narrative?.scientific?.zh_CN
      || (n.continuant_id ? `跨阶段实体：${n.continuant_id}` : ''),
    narrative: n.narrative || null,
    continuant_id: n.continuant_id || null,
    stage_span: n.stage_span || [],
    rawData: n,
  }))
}

function adaptEdges(edges) {
  return (edges || []).map(e => ({
    uuid: `${e.source}->${e.target}:${e.type}`,
    source_node_uuid: e.source,
    target_node_uuid: e.target,
    fact_type: e.type || 'RELATED',
    name: e.type || 'RELATED',
    fact: e.description || '',
    weight: e.weight,
    rawData: e,
  }))
}

function pickAttrs(n) {
  const skip = new Set([
    'id', 'group', 'label', 'narrative', 'metadata', 'rawData',
    'weight', 'layer', 'stage', 'stage_span', 'continuant_id',
  ])
  const out = {}
  for (const [k, v] of Object.entries(n)) {
    if (skip.has(k)) continue
    if (v == null || v === '') continue
    if (typeof v === 'object') continue
    out[k] = v
  }
  if (n.metadata && typeof n.metadata === 'object') {
    for (const [k, v] of Object.entries(n.metadata)) {
      if (v == null || v === '') continue
      if (typeof v === 'object') continue
      if (k in out) continue
      out[k] = v
    }
  }
  return out
}

function formatDateTime(s) {
  if (!s) return ''
  try {
    return new Date(s).toLocaleString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: 'numeric', minute: '2-digit', hour12: true,
    })
  } catch { return s }
}

// ── 纯函数：路径与中点 ─────────────────────────────────
function getLinkPath(d) {
  const sx = d.source.x, sy = d.source.y
  const tx = d.target.x, ty = d.target.y
  if (d.isSelfLoop) {
    const r = 30
    const x1 = sx + 8, y1 = sy - 4
    const x2 = sx + 8, y2 = sy + 4
    return `M${x1},${y1} A${r},${r} 0 1,1 ${x2},${y2}`
  }
  if (d.curvature === 0) return `M${sx},${sy} L${tx},${ty}`
  const dx = tx - sx, dy = ty - sy
  const dist = Math.sqrt(dx * dx + dy * dy) || 1
  const pairTotal = d.pairTotal || 1
  const ratio = 0.25 + pairTotal * 0.05
  const off = Math.max(35, dist * ratio)
  const ox = -dy / dist * d.curvature * off
  const oy = dx / dist * d.curvature * off
  const cx = (sx + tx) / 2 + ox
  const cy = (sy + ty) / 2 + oy
  return `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`
}

function getLinkMidpoint(d) {
  const sx = d.source.x, sy = d.source.y
  const tx = d.target.x, ty = d.target.y
  if (d.isSelfLoop) return { x: sx + 70, y: sy }
  if (d.curvature === 0) return { x: (sx + tx) / 2, y: (sy + ty) / 2 }
  const dx = tx - sx, dy = ty - sy
  const dist = Math.sqrt(dx * dx + dy * dy) || 1
  const pairTotal = d.pairTotal || 1
  const ratio = 0.25 + pairTotal * 0.05
  const off = Math.max(35, dist * ratio)
  const ox = -dy / dist * d.curvature * off
  const oy = dx / dist * d.curvature * off
  const cx = (sx + tx) / 2 + ox
  const cy = (sy + ty) / 2 + oy
  return {
    x: 0.25 * sx + 0.5 * cx + 0.25 * tx,
    y: 0.25 * sy + 0.5 * cy + 0.25 * ty,
  }
}

// ── 节点同步：复用 simNode 对象以保留 x/y/vx/vy ─────────
function syncSimNodes(dataNodes, nodesMap, width, height) {
  const incoming = new Set(dataNodes.map(n => n.uuid))
  for (const id of [...nodesMap.keys()]) {
    if (!incoming.has(id)) nodesMap.delete(id)
  }
  const cx = width / 2
  const cy = height / 2
  for (const n of dataNodes) {
    const type = n.labels?.find(l => l !== 'Entity') || 'Entity'
    const existing = nodesMap.get(n.uuid)
    if (existing) {
      existing.name = n.name
      existing.type = type
      existing.rawData = n
    } else {
      // 新节点：中心附近小范围随机，避免 (0,0) 冷启动弹跳
      const jitter = () => (Math.random() - 0.5) * 80
      nodesMap.set(n.uuid, {
        id: n.uuid,
        name: n.name,
        type,
        rawData: n,
        x: cx + jitter(),
        y: cy + jitter(),
      })
    }
  }
  return [...nodesMap.values()]
}

// ── 边预处理：自环合并 + 多边曲率 ───────────────────────
function buildSimEdges(dataEdges, nodesMap) {
  const edgePairCount = {}
  const selfLoopEdges = {}
  const nodeIds = nodesMap
  const tempEdges = dataEdges.filter(
    e => nodeIds.has(e.source_node_uuid) && nodeIds.has(e.target_node_uuid),
  )
  tempEdges.forEach(e => {
    if (e.source_node_uuid === e.target_node_uuid) {
      if (!selfLoopEdges[e.source_node_uuid]) selfLoopEdges[e.source_node_uuid] = []
      selfLoopEdges[e.source_node_uuid].push({
        ...e,
        source_name: nodesMap.get(e.source_node_uuid)?.name,
        target_name: nodesMap.get(e.target_node_uuid)?.name,
      })
    } else {
      const key = [e.source_node_uuid, e.target_node_uuid].sort().join('_')
      edgePairCount[key] = (edgePairCount[key] || 0) + 1
    }
  })

  const edgePairIndex = {}
  const processedLoops = new Set()
  const simEdges = []
  tempEdges.forEach(e => {
    const isLoop = e.source_node_uuid === e.target_node_uuid
    if (isLoop) {
      if (processedLoops.has(e.source_node_uuid)) return
      processedLoops.add(e.source_node_uuid)
      const loops = selfLoopEdges[e.source_node_uuid]
      const nodeName = nodesMap.get(e.source_node_uuid)?.name || 'Unknown'
      simEdges.push({
        uuid: `self_${e.source_node_uuid}`,
        source: e.source_node_uuid, target: e.target_node_uuid,
        type: 'SELF_LOOP', name: `Self Relations (${loops.length})`,
        curvature: 0, isSelfLoop: true,
        rawData: {
          isSelfLoopGroup: true,
          source_name: nodeName, target_name: nodeName,
          selfLoopCount: loops.length, selfLoopEdges: loops,
        },
      })
      return
    }
    const key = [e.source_node_uuid, e.target_node_uuid].sort().join('_')
    const total = edgePairCount[key]
    const idx = edgePairIndex[key] || 0
    edgePairIndex[key] = idx + 1
    const reversed = e.source_node_uuid > e.target_node_uuid
    let curvature = 0
    if (total > 1) {
      const range = Math.min(1.2, 0.6 + total * 0.15)
      curvature = ((idx / (total - 1)) - 0.5) * range * 2
      if (reversed) curvature = -curvature
    }
    simEdges.push({
      uuid: e.uuid,
      source: e.source_node_uuid, target: e.target_node_uuid,
      type: e.fact_type || e.name || 'RELATED',
      name: e.name || e.fact_type || 'RELATED',
      curvature, isSelfLoop: false,
      pairIndex: idx, pairTotal: total,
      rawData: {
        ...e,
        source_name: nodesMap.get(e.source_node_uuid)?.name,
        target_name: nodesMap.get(e.target_node_uuid)?.name,
      },
    })
  })
  return simEdges
}

// ── 主组件 ─────────────────────────────────────────────
const LifeGraph = memo(function LifeGraph({
  nodes,
  edges,
  fullscreen,
  onToggleFullscreen,
  // eslint-disable-next-line no-unused-vars
  filter, showLabels, highlight, stage, dispatch, onNodeClick,
}) {
  const containerRef = useRef(null)
  const svgRef = useRef(null)
  const simulationRef = useRef(null)
  const gRef = useRef(null)
  const linkGroupRef = useRef(null)
  const nodeGroupRef = useRef(null)
  const selRef = useRef({
    link: null, linkLabel: null, linkLabelBg: null, node: null, nodeLabel: null,
  })
  const nodesByIdRef = useRef(new Map())
  const initializedRef = useRef(false)
  const selectedItemRef = useRef(null)
  const colorMapRef = useRef({})

  const [selectedItem, setSelectedItem] = useState(null)
  const [showEdgeLabels, setShowEdgeLabels] = useState(true)
  const [expandedLoops, setExpandedLoops] = useState(new Set())
  const [colorMap, setColorMap] = useState({})
  const lang = useLang()
  const t = I18N[lang] || I18N.en

  useEffect(() => { selectedItemRef.current = selectedItem }, [selectedItem])
  useEffect(() => { colorMapRef.current = colorMap }, [colorMap])

  const graphData = useMemo(() => ({
    nodes: adaptNodes(nodes),
    edges: adaptEdges(edges),
  }), [nodes, edges])

  // ── colorMap 追加式：新 type 顺序分配，旧 type 颜色稳定 ──
  useEffect(() => {
    setColorMap(prev => {
      let n = Object.keys(prev).length
      let changed = false
      const next = { ...prev }
      for (const node of graphData.nodes) {
        const tp = node.labels?.find(l => l !== 'Entity') || 'Entity'
        if (!(tp in next)) {
          next[tp] = PALETTE[n++ % PALETTE.length]
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [graphData.nodes])

  const entityTypes = useMemo(
    () => Object.entries(colorMap).map(([name, color]) => ({ name, color })),
    [colorMap],
  )

  // ── 外部清空（nodes=0）时重置内部状态 ─────────────────
  useEffect(() => {
    if (graphData.nodes.length === 0 && nodesByIdRef.current.size > 0) {
      nodesByIdRef.current.clear()
      setSelectedItem(null)
    }
  }, [graphData.nodes.length])

  // ── 核心：初始化（一次）+ 数据同步（每次） ───────────
  useEffect(() => {
    if (!svgRef.current || !containerRef.current) return
    const container = containerRef.current
    const width = container.clientWidth
    const height = container.clientHeight
    if (width === 0 || height === 0) return

    const svg = d3.select(svgRef.current)
    const getColor = (type) => colorMapRef.current[type] || '#999'

    // ── Mount 阶段：只建一次 ──
    if (!initializedRef.current) {
      svg.attr('width', width).attr('height', height)
        .attr('viewBox', `0 0 ${width} ${height}`)
      svg.selectAll('*').remove()

      const g = svg.append('g')
      gRef.current = g
      linkGroupRef.current = g.append('g').attr('class', 'links')
      nodeGroupRef.current = g.append('g').attr('class', 'nodes')

      svg.call(
        d3.zoom()
          .extent([[0, 0], [width, height]])
          .scaleExtent([0.1, 4])
          .on('zoom', (event) => g.attr('transform', event.transform)),
      )

      const sim = d3.forceSimulation([])
        .force('link', d3.forceLink([]).id(d => d.id).distance(d => {
          const base = 150
          const cnt = d.pairTotal || 1
          return base + (cnt - 1) * 50
        }))
        .force('charge', d3.forceManyBody().strength(-400))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collide', d3.forceCollide(50))
        .alphaDecay(0.05)
        .velocityDecay(0.55)
      simulationRef.current = sim

      sim.on('tick', () => {
        const sel = selRef.current
        if (!sel.link || !sel.node) return
        sel.link.attr('d', getLinkPath)
        sel.linkLabel.each(function (d) {
          const m = getLinkMidpoint(d)
          d3.select(this).attr('x', m.x).attr('y', m.y)
        })
        sel.linkLabelBg.each(function (d, i) {
          const m = getLinkMidpoint(d)
          const lbl = sel.linkLabel.nodes()[i]
          if (!lbl) return
          const bb = lbl.getBBox()
          d3.select(this)
            .attr('x', m.x - bb.width / 2 - 4)
            .attr('y', m.y - bb.height / 2 - 2)
            .attr('width', bb.width + 8)
            .attr('height', bb.height + 4)
        })
        sel.node.attr('cx', d => d.x).attr('cy', d => d.y)
        sel.nodeLabel.attr('x', d => d.x).attr('y', d => d.y)
      })

      svg.on('click', () => {
        setSelectedItem(null)
        clearHighlights()
      })

      initializedRef.current = true
    }

    // ── 数据同步：D3 join + 温启动 ──
    const sim = simulationRef.current
    const simNodes = syncSimNodes(
      graphData.nodes, nodesByIdRef.current, width, height,
    )
    const simEdges = buildSimEdges(graphData.edges, nodesByIdRef.current)

    // link path
    selRef.current.link = linkGroupRef.current.selectAll('path')
      .data(simEdges, d => d.uuid)
      .join(
        enter => enter.append('path')
          .attr('stroke', '#C0C0C0')
          .attr('stroke-width', 1.5)
          .attr('fill', 'none')
          .style('cursor', 'pointer')
          .on('click', onLinkClick),
        update => update,
        exit => exit.remove(),
      )

    // link label 背景
    selRef.current.linkLabelBg = linkGroupRef.current.selectAll('rect')
      .data(simEdges, d => d.uuid)
      .join(
        enter => enter.append('rect')
          .attr('fill', 'rgba(255,255,255,0.95)')
          .attr('rx', 3).attr('ry', 3)
          .style('cursor', 'pointer')
          .style('pointer-events', 'all')
          .style('display', showEdgeLabels ? 'block' : 'none')
          .on('click', onLinkLabelBgClick),
        update => update,
        exit => exit.remove(),
      )

    // link label 文本
    selRef.current.linkLabel = linkGroupRef.current.selectAll('text')
      .data(simEdges, d => d.uuid)
      .join(
        enter => enter.append('text')
          .attr('font-size', '9px')
          .attr('fill', '#666')
          .attr('text-anchor', 'middle')
          .attr('dominant-baseline', 'middle')
          .style('cursor', 'pointer')
          .style('pointer-events', 'all')
          .style('font-family', 'system-ui, sans-serif')
          .style('display', showEdgeLabels ? 'block' : 'none')
          .on('click', onLinkLabelClick)
          .text(d => d.name),
        update => update.text(d => d.name),
        exit => exit.remove(),
      )

    // node
    selRef.current.node = nodeGroupRef.current.selectAll('circle')
      .data(simNodes, d => d.id)
      .join(
        enter => enter.append('circle')
          .attr('r', 10)
          .attr('fill', d => getColor(d.type))
          .attr('stroke', '#fff')
          .attr('stroke-width', 2.5)
          .style('cursor', 'pointer')
          .call(d3.drag()
            .on('start', onDragStart)
            .on('drag', onDrag)
            .on('end', onDragEnd))
          .on('click', onNodeClickD3)
          .on('mouseenter', onNodeEnter)
          .on('mouseleave', onNodeLeave),
        update => update.attr('fill', d => getColor(d.type)),
        exit => exit.remove(),
      )

    // node label
    selRef.current.nodeLabel = nodeGroupRef.current.selectAll('text')
      .data(simNodes, d => d.id)
      .join(
        enter => enter.append('text')
          .attr('font-size', '11px')
          .attr('fill', '#333')
          .attr('font-weight', '500')
          .attr('dx', 14).attr('dy', 4)
          .style('pointer-events', 'none')
          .style('font-family', 'system-ui, sans-serif')
          .text(d => d.name.length > 8 ? d.name.substring(0, 8) + '…' : d.name),
        update => update.text(d => d.name.length > 8 ? d.name.substring(0, 8) + '…' : d.name),
        exit => exit.remove(),
      )

    sim.nodes(simNodes)
    sim.force('link').links(simEdges)
    // 温启动：有新内容才扰动，避免静止图被无故晃
    if (simNodes.length > 0) sim.alpha(0.3).restart()

    // ── 事件回调（闭包访问 sim/sel/setSelectedItem） ──
    function clearHighlights() {
      selRef.current.node?.attr('stroke', '#fff').attr('stroke-width', 2.5)
      selRef.current.link?.attr('stroke', '#C0C0C0').attr('stroke-width', 1.5)
      selRef.current.linkLabelBg?.attr('fill', 'rgba(255,255,255,0.95)')
      selRef.current.linkLabel?.attr('fill', '#666')
    }
    function onLinkClick(event, d) {
      event.stopPropagation()
      clearHighlights()
      d3.select(event.currentTarget).attr('stroke', '#3498db').attr('stroke-width', 3)
      setSelectedItem({ type: 'edge', data: d.rawData })
    }
    function onLinkLabelBgClick(event, d) {
      event.stopPropagation()
      clearHighlights()
      selRef.current.link.filter(l => l === d).attr('stroke', '#3498db').attr('stroke-width', 3)
      d3.select(event.currentTarget).attr('fill', 'rgba(52,152,219,0.1)')
      setSelectedItem({ type: 'edge', data: d.rawData })
    }
    function onLinkLabelClick(event, d) {
      event.stopPropagation()
      clearHighlights()
      selRef.current.link.filter(l => l === d).attr('stroke', '#3498db').attr('stroke-width', 3)
      d3.select(event.currentTarget).attr('fill', '#3498db')
      setSelectedItem({ type: 'edge', data: d.rawData })
    }
    function onNodeClickD3(event, d) {
      event.stopPropagation()
      clearHighlights()
      d3.select(event.currentTarget).attr('stroke', '#E91E63').attr('stroke-width', 4)
      selRef.current.link
        .filter(l => l.source.id === d.id || l.target.id === d.id)
        .attr('stroke', '#E91E63').attr('stroke-width', 2.5)
      setSelectedItem({
        type: 'node', data: d.rawData,
        entityType: d.type, color: getColor(d.type),
      })
    }
    function onNodeEnter(event, d) {
      const sel = d3.select(event.currentTarget)
      const sItem = selectedItemRef.current
      if (!sItem || sItem.data?.uuid !== d.rawData.uuid) {
        sel.attr('stroke', '#333').attr('stroke-width', 3)
      }
    }
    function onNodeLeave(event, d) {
      const sel = d3.select(event.currentTarget)
      const sItem = selectedItemRef.current
      if (!sItem || sItem.data?.uuid !== d.rawData.uuid) {
        sel.attr('stroke', '#fff').attr('stroke-width', 2.5)
      }
    }
    function onDragStart(event, d) {
      d.fx = d.x; d.fy = d.y
      d._dragStartX = event.x; d._dragStartY = event.y
      d._isDragging = false
    }
    function onDrag(event, d) {
      const dx = event.x - d._dragStartX
      const dy = event.y - d._dragStartY
      if (!d._isDragging && Math.sqrt(dx * dx + dy * dy) > 3) {
        d._isDragging = true
        sim.alphaTarget(0.3).restart()
      }
      if (d._isDragging) { d.fx = event.x; d.fy = event.y }
    }
    function onDragEnd(event, d) {
      if (d._isDragging) sim.alphaTarget(0)
      d.fx = null; d.fy = null; d._isDragging = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphData, colorMap])

  // ── 边标签显隐 ──
  useEffect(() => {
    selRef.current.linkLabel?.style('display', showEdgeLabels ? 'block' : 'none')
    selRef.current.linkLabelBg?.style('display', showEdgeLabels ? 'block' : 'none')
  }, [showEdgeLabels])

  // ── ResizeObserver：仅更新 viewBox 与 center 力 ──
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const ro = new ResizeObserver(() => {
      const w = container.clientWidth
      const h = container.clientHeight
      if (w === 0 || h === 0) return
      if (svgRef.current) {
        d3.select(svgRef.current)
          .attr('width', w).attr('height', h)
          .attr('viewBox', `0 0 ${w} ${h}`)
      }
      const sim = simulationRef.current
      if (sim) {
        sim.force('center', d3.forceCenter(w / 2, h / 2))
        sim.alpha(0.1).restart()
      }
    })
    ro.observe(container)
    return () => ro.disconnect()
  }, [])

  // ── 卸载清理 ──
  useEffect(() => {
    return () => {
      if (simulationRef.current) simulationRef.current.stop()
    }
  }, [])

  // ── 详情面板：自环项展开 ──
  const toggleLoop = (id) => {
    setExpandedLoops(prev => {
      const s = new Set(prev)
      if (s.has(id)) s.delete(id); else s.add(id)
      return s
    })
  }

  const closeDetail = () => {
    setSelectedItem(null)
    setExpandedLoops(new Set())
  }

  // ── 渲染 ──
  return (
    <div className={`lg-panel ${fullscreen ? 'lg-fullscreen' : ''}`}>
      <div className="lg-header">
        <span className="lg-title">{t.title}</span>
        <div className="lg-header-tools">
          {graphData.nodes.length > 0 && (
            <div className="lg-labels-toggle">
              <label className="lg-switch">
                <input
                  type="checkbox"
                  checked={showEdgeLabels}
                  onChange={e => setShowEdgeLabels(e.target.checked)}
                />
                <span className="lg-slider" />
              </label>
              <span className="lg-toggle-label">{t.toggle}</span>
            </div>
          )}
          {onToggleFullscreen && (
            <button className="lg-tool-btn" onClick={onToggleFullscreen} title={fullscreen ? '退出全屏' : '全屏'}>
              {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
          )}
        </div>
      </div>

      <div className="lg-container" ref={containerRef}>
        <div className="lg-view">
          {/* svg 永远挂载，避免空态 → 数据态切换时 DOM 被销毁重建 */}
          <svg ref={svgRef} className="lg-svg" />

          {graphData.nodes.length === 0 && (
            <div className="lg-state">
              <div className="lg-empty-icon">❖</div>
              <p>{t.empty}</p>
            </div>
          )}

          {selectedItem && (
            <div className="lg-detail-panel">
              <div className="lg-detail-header">
                <span className="lg-detail-title">
                  {selectedItem.type === 'node' ? t.nodeDetail : t.edgeDetail}
                </span>
                {selectedItem.type === 'node' && (
                  <span
                    className="lg-detail-badge"
                    style={{ background: selectedItem.color, color: '#fff' }}
                  >
                    {selectedItem.entityType}
                  </span>
                )}
                <button className="lg-detail-close" onClick={closeDetail}>×</button>
              </div>

              {selectedItem.type === 'node' ? (
                <div className="lg-detail-content">
                  <div className="lg-detail-row">
                    <span className="lg-detail-label">Name:</span>
                    <span className="lg-detail-value">{selectedItem.data.name}</span>
                  </div>
                  <div className="lg-detail-row">
                    <span className="lg-detail-label">ID:</span>
                    <span className="lg-detail-value lg-uuid-text">{selectedItem.data.uuid}</span>
                  </div>
                  {selectedItem.data.labels?.[0] && (
                    <div className="lg-detail-row">
                      <span className="lg-detail-label">Group:</span>
                      <span className="lg-detail-value">{selectedItem.data.labels[0]}</span>
                    </div>
                  )}
                  {selectedItem.data.continuant_id && (
                    <div className="lg-detail-row">
                      <span className="lg-detail-label">Continuant:</span>
                      <span className="lg-detail-value">{selectedItem.data.continuant_id}</span>
                    </div>
                  )}
                  {selectedItem.data.stage_span?.length > 0 && (
                    <div className="lg-detail-row">
                      <span className="lg-detail-label">Stage Span:</span>
                      <span className="lg-detail-value">{selectedItem.data.stage_span.join(' → ')}</span>
                    </div>
                  )}
                  {selectedItem.data.summary && (
                    <div className="lg-detail-section">
                      <div className="lg-section-title">Summary:</div>
                      <div className="lg-summary-text">{selectedItem.data.summary}</div>
                    </div>
                  )}
                  {selectedItem.data.narrative?.scientific?.zh_CN && (
                    <div className="lg-detail-section">
                      <div className="lg-section-title">Scientific:</div>
                      <div className="lg-summary-text">{selectedItem.data.narrative.scientific.zh_CN}</div>
                    </div>
                  )}
                </div>
              ) : selectedItem.data.isSelfLoopGroup ? (
                <div className="lg-detail-content">
                  <div className="lg-edge-header lg-loop-header">
                    {selectedItem.data.source_name} - Self Relations
                    <span className="lg-loop-count">{selectedItem.data.selfLoopCount} items</span>
                  </div>
                  <div className="lg-loop-list">
                    {selectedItem.data.selfLoopEdges.map((loop, idx) => {
                      const key = loop.uuid || idx
                      const expanded = expandedLoops.has(key)
                      return (
                        <div key={key} className={`lg-loop-item ${expanded ? 'expanded' : ''}`}>
                          <div className="lg-loop-item-header" onClick={() => toggleLoop(key)}>
                            <span className="lg-loop-index">#{idx + 1}</span>
                            <span className="lg-loop-name">{loop.name || loop.fact_type || 'RELATED'}</span>
                            <span className="lg-loop-toggle">{expanded ? '−' : '+'}</span>
                          </div>
                          {expanded && (
                            <div className="lg-loop-item-content">
                              {loop.uuid && (
                                <div className="lg-detail-row">
                                  <span className="lg-detail-label">UUID:</span>
                                  <span className="lg-detail-value lg-uuid-text">{loop.uuid}</span>
                                </div>
                              )}
                              {loop.fact && (
                                <div className="lg-detail-row">
                                  <span className="lg-detail-label">Fact:</span>
                                  <span className="lg-detail-value">{loop.fact}</span>
                                </div>
                              )}
                              {loop.fact_type && (
                                <div className="lg-detail-row">
                                  <span className="lg-detail-label">Type:</span>
                                  <span className="lg-detail-value">{loop.fact_type}</span>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              ) : (
                <div className="lg-detail-content">
                  <div className="lg-edge-header">
                    {selectedItem.data.source_name} → {selectedItem.data.name || 'RELATED_TO'} → {selectedItem.data.target_name}
                  </div>
                  <div className="lg-detail-row">
                    <span className="lg-detail-label">ID:</span>
                    <span className="lg-detail-value lg-uuid-text">{selectedItem.data.uuid}</span>
                  </div>
                  <div className="lg-detail-row">
                    <span className="lg-detail-label">Type:</span>
                    <span className="lg-detail-value">{selectedItem.data.fact_type || 'Unknown'}</span>
                  </div>
                  {selectedItem.data.fact && (
                    <div className="lg-detail-row">
                      <span className="lg-detail-label">Fact:</span>
                      <span className="lg-detail-value">{selectedItem.data.fact}</span>
                    </div>
                  )}
                  {selectedItem.data.created_at && (
                    <div className="lg-detail-row">
                      <span className="lg-detail-label">Created:</span>
                      <span className="lg-detail-value">{formatDateTime(selectedItem.data.created_at)}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {graphData.nodes.length > 0 && entityTypes.length > 0 && (
        <div className="lg-legend">
          <span className="lg-legend-title">{t.legend}</span>
          <div className="lg-legend-items">
            {entityTypes.map(et => (
              <div key={et.name} className="lg-legend-item">
                <span className="lg-legend-dot" style={{ background: et.color }} />
                <span className="lg-legend-label">{et.name}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
})

export default LifeGraph
