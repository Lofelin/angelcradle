/**
 * [INPUT]: nodes (Map<id,node> | array), edges (array), fullscreen, onToggleFullscreen
 * [OUTPUT]: 力导向关系图（D3 SVG）
 * [POS]: 三页面（子宫/摇篮/世界）共用
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 *
 * 视觉参数：
 *   背景：#FAFAFA + 点阵 (#D0D0D0 1.5px, 24px)
 *   节点：r=10 + 白描边 2.5px，选中 #E91E63 4px，hover #333 3px
 *   边：  #C0C0C0 1.5px，高亮 #3498db 3px，自环圆弧，多边均匀曲率
 *   力：  charge -400, link 150+(cnt-1)*50, collide 50, center
 *
 * 2026-04-20 流式重构（SSE 增量渲染，取代一次性全量重建）：
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

// ── 节点配色板 ──────────────────────────────────────────
const PALETTE = [
  '#FF6B35', '#004E89', '#7B2D8E', '#1A936F', '#C5283D',
  '#E9724C', '#3498db', '#9b59b6', '#27ae60', '#f39c12',
]

// ── 组件内置 i18n（读 App 在 localStorage 存的 lang）──────
const I18N = {
  en: {
    title: 'Graph', toggle: 'Show Edge Labels', empty: 'Waiting for graph data',
    legend: 'Entity Types', nodeDetail: 'Node Details', edgeDetail: 'Relationship',
    name: 'Name', id: 'ID', group: 'Group', continuant: 'Continuant',
    stageSpan: 'Stage Span', properties: 'Properties', summary: 'Summary',
    scientific: 'Scientific', timeSeries: 'Time Series', samples: 'samples',
    labels: 'Labels', type: 'Type', fact: 'Fact', stage: 'Stage', phase: 'Phase',
    weight: 'Weight', level: 'Level', polarity: 'Polarity', exposure: 'Exposure',
    value: 'Value', unit: 'Unit', status: 'Status', created: 'Created',
    validFrom: 'Valid From', invalidFrom: 'Invalid From', related: 'RELATED_TO',
    selfRelations: 'Self Relations', items: 'items', unknown: 'Unknown',
  },
  zh: {
    title: '图谱', toggle: '显示边标签', empty: '等待图谱数据',
    legend: '实体类型', nodeDetail: '节点详情', edgeDetail: '关系',
    name: '名称', id: '标识', group: '分组', continuant: '持续体',
    stageSpan: '阶段跨度', properties: '属性', summary: '摘要',
    scientific: '科学描述', timeSeries: '时间序列', samples: '个采样点',
    labels: '标签', type: '类型', fact: '事实', stage: '阶段', phase: '时相',
    weight: '权重', level: '水平', polarity: '极性', exposure: '暴露',
    value: '数值', unit: '单位', status: '状态', created: '创建时间',
    validFrom: '有效自', invalidFrom: '失效自', related: '相关',
    selfRelations: '自环关系', items: '项', unknown: '未知',
  },
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

// ── 数据适配：lifegraph schema → 力导向渲染 shape ────────
function adaptNodes(nodes, lang = 'en') {
  const arr = nodes instanceof Map ? Array.from(nodes.values()) : (nodes || [])
  const langKey = lang === 'zh' ? 'zh_CN' : 'en'
  const fallbackKey = langKey === 'zh_CN' ? 'en' : 'zh_CN'
  const pickNarr = (prim) => prim?.[langKey] || prim?.[fallbackKey] || ''
  const continuantFallback = lang === 'zh'
    ? (id) => `跨阶段实体：${id}`
    : (id) => `Continuant entity: ${id}`
  return arr.map(n => ({
    uuid: n.id,
    name: n.label || 'Unnamed',
    labels: [n.group || 'Entity'],
    attributes: pickAttrs(n),
    summary: pickNarr(n.narrative?.primary)
      || pickNarr(n.narrative?.scientific)
      || (n.continuant_id ? continuantFallback(n.continuant_id) : ''),
    narrative: n.narrative || null,
    continuant_id: n.continuant_id || null,
    stage_span: n.stage_span || [],
    rawData: n,
  }))
}

function adaptEdges(edges) {
  return (edges || []).map(e => ({
    // 优先用后端 content-hash uuid (e_xxxxxxxxxx), 缺失时 fallback 到原规则
    uuid: e.uuid || `${e.source}->${e.target}:${e.type}`,
    source_node_uuid: e.source,
    target_node_uuid: e.target,
    fact_type: e.type || 'RELATED',
    name: e.type || 'RELATED',
    fact: e.description || '',
    weight: e.weight,
    stage_index: e.stage_index,
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
    nodes: adaptNodes(nodes, lang),
    edges: adaptEdges(edges),
  }), [nodes, edges, lang])

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

      // 2026-04-23 调参：cradle 图 v3 修复后 baby_this 入度骤增（~41），弱连接分量
      // （physical 链、progression 链）被主星系斥力甩出孤岛。先拉到 distance=60/charge=-120
      // 修复孤岛后，节点过挤、标签重叠——本轮回调到中间档：
      // distance 110 / charge -250 / collide 42 / forceX/Y 0.02，既保持主图连贯又有呼吸感。
      const sim = d3.forceSimulation([])
        .force('link', d3.forceLink([]).id(d => d.id).distance(d => {
          const base = 110
          const cnt = d.pairTotal || 1
          return base + (cnt - 1) * 25
        }).strength(d => {
          // 弱连接分量（BELONGS_TO 骨架）提高 strength 把它们拉回主图
          const cnt = d.pairTotal || 1
          return cnt > 1 ? 0.35 : 0.55
        }))
        .force('charge', d3.forceManyBody().strength(-250).distanceMax(700))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collide', d3.forceCollide(42))
        .force('x', d3.forceX(width / 2).strength(0.02))
        .force('y', d3.forceY(height / 2).strength(0.02))
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
        sim.force('x', d3.forceX(w / 2).strength(0.02))
        sim.force('y', d3.forceY(h / 2).strength(0.02))
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
                (() => {
                  const d = selectedItem.data
                  const raw = d.rawData || {}
                  const meta = raw.metadata || {}
                  // Properties: 所有简单标量字段 (排除已在其他区块展示的)
                  const HIDDEN_PROP = new Set([
                    'id', 'label', 'group', 'narrative', 'continuant_id', 'stage_span',
                    'kind', 'track', 'rawData',
                  ])
                  const propEntries = []
                  for (const [k, v] of Object.entries(meta)) {
                    if (HIDDEN_PROP.has(k)) continue
                    if (v == null || v === '') continue
                    if (typeof v === 'object' && !Array.isArray(v)) continue
                    propEntries.push([k, v])
                  }
                  // Labels: group + metadata.kind (如果有且不同)
                  const labels = []
                  if (d.labels?.[0]) labels.push(d.labels[0])
                  if (meta.kind && meta.kind !== d.labels?.[0]) labels.push(meta.kind)
                  // Track: 时间序列数据 (激素/营养/体征独有)
                  const track = Array.isArray(meta.track) ? meta.track : null

                  const fmtVal = (v) => {
                    if (Array.isArray(v)) return v.join(', ')
                    if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3).replace(/\.?0+$/, '')
                    return String(v)
                  }

                  return (
                    <div className="lg-detail-content">
                      <div className="lg-detail-row">
                        <span className="lg-detail-label">{t.name}:</span>
                        <span className="lg-detail-value">{d.name}</span>
                      </div>
                      <div className="lg-detail-row">
                        <span className="lg-detail-label">{t.id}:</span>
                        <span className="lg-detail-value lg-uuid-text">{d.uuid}</span>
                      </div>
                      {d.labels?.[0] && (
                        <div className="lg-detail-row">
                          <span className="lg-detail-label">{t.group}:</span>
                          <span className="lg-detail-value">{d.labels[0]}</span>
                        </div>
                      )}
                      {d.continuant_id && (
                        <div className="lg-detail-row">
                          <span className="lg-detail-label">{t.continuant}:</span>
                          <span className="lg-detail-value">{d.continuant_id}</span>
                        </div>
                      )}
                      {d.stage_span?.length > 0 && (
                        <div className="lg-detail-row">
                          <span className="lg-detail-label">{t.stageSpan}:</span>
                          <span className="lg-detail-value">{d.stage_span.join(' → ')}</span>
                        </div>
                      )}
                      {propEntries.length > 0 && (
                        <div className="lg-detail-section">
                          <div className="lg-section-title">{t.properties}:</div>
                          {propEntries.map(([k, v]) => (
                            <div className="lg-detail-row" key={k}>
                              <span className="lg-detail-label">{k.replace(/_/g, ' ')}:</span>
                              <span className="lg-detail-value">{fmtVal(v)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {d.summary && (
                        <div className="lg-detail-section">
                          <div className="lg-section-title">{t.summary}:</div>
                          <div className="lg-summary-text">{d.summary}</div>
                        </div>
                      )}
                      {(d.narrative?.scientific?.[lang === 'zh' ? 'zh_CN' : 'en'] || d.narrative?.scientific?.zh_CN || d.narrative?.scientific?.en) && (
                        <div className="lg-detail-section">
                          <div className="lg-section-title">{t.scientific}:</div>
                          <div className="lg-summary-text">{
                            d.narrative?.scientific?.[lang === 'zh' ? 'zh_CN' : 'en']
                            || d.narrative?.scientific?.zh_CN
                            || d.narrative?.scientific?.en
                          }</div>
                        </div>
                      )}
                      {track && track.length > 0 && (
                        <div className="lg-detail-section">
                          <div className="lg-section-title">{t.timeSeries} ({track.length} {t.samples}):</div>
                          {track.map((tr, i) => {
                            const { stage_index, ...rest } = tr
                            const cells = Object.entries(rest)
                              .filter(([, v]) => v != null && typeof v !== 'object')
                              .map(([k, v]) => `${k}=${fmtVal(v)}`)
                              .join(' · ')
                            return (
                              <div className="lg-detail-row" key={i}>
                                <span className="lg-detail-label">S{stage_index}:</span>
                                <span className="lg-detail-value">{cells}</span>
                              </div>
                            )
                          })}
                        </div>
                      )}
                      {labels.length > 1 && (
                        <div className="lg-detail-section">
                          <div className="lg-section-title">{t.labels}:</div>
                          <div className="lg-labels-row">
                            {labels.map((lbl, i) => (
                              <span key={i} className="lg-label-chip">{lbl}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })()
              ) : selectedItem.data.isSelfLoopGroup ? (
                <div className="lg-detail-content">
                  <div className="lg-edge-header lg-loop-header">
                    {selectedItem.data.source_name} - {t.selfRelations}
                    <span className="lg-loop-count">{selectedItem.data.selfLoopCount} {t.items}</span>
                  </div>
                  <div className="lg-loop-list">
                    {selectedItem.data.selfLoopEdges.map((loop, idx) => {
                      const key = loop.uuid || idx
                      const expanded = expandedLoops.has(key)
                      return (
                        <div key={key} className={`lg-loop-item ${expanded ? 'expanded' : ''}`}>
                          <div className="lg-loop-item-header" onClick={() => toggleLoop(key)}>
                            <span className="lg-loop-index">#{idx + 1}</span>
                            <span className="lg-loop-name">{loop.name || loop.fact_type || t.related}</span>
                            <span className="lg-loop-toggle">{expanded ? '−' : '+'}</span>
                          </div>
                          {expanded && (
                            <div className="lg-loop-item-content">
                              {loop.uuid && (
                                <div className="lg-detail-row">
                                  <span className="lg-detail-label">{t.id}:</span>
                                  <span className="lg-detail-value lg-uuid-text">{loop.uuid}</span>
                                </div>
                              )}
                              {loop.fact && (
                                <div className="lg-detail-row">
                                  <span className="lg-detail-label">{t.fact}:</span>
                                  <span className="lg-detail-value">{loop.fact}</span>
                                </div>
                              )}
                              {loop.fact_type && (
                                <div className="lg-detail-row">
                                  <span className="lg-detail-label">{t.type}:</span>
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
                (() => {
                  // 合并来源: 适配层字段 + 原始后端字段 (rawData)
                  const d = selectedItem.data
                  const raw = d.rawData || {}
                  const merged = { ...raw, ...d }
                  // 已渲染在 header / 单独行的字段, 不进入 Other 清单
                  const HIDDEN = new Set([
                    'uuid', 'source', 'target', 'source_node_uuid', 'target_node_uuid',
                    'source_name', 'target_name', 'type', 'fact_type', 'name',
                    'rawData', 'isSelfLoopGroup', 'selfLoopEdges', 'selfLoopCount',
                  ])
                  // 按此顺序优先渲染已知业务字段
                  const ORDERED = [
                    ['fact', t.fact],
                    ['description', t.fact],
                    ['stage_index', t.stage],
                    ['phase', t.phase],
                    ['weight', t.weight],
                    ['level_at', t.level],
                    ['level', t.level],
                    ['polarity', t.polarity],
                    ['exposure', t.exposure],
                    ['v', t.value],
                    ['unit', t.unit],
                    ['status', t.status],
                    ['created_at', t.created],
                    ['valid_at', t.validFrom],
                    ['invalid_at', t.invalidFrom],
                  ]
                  const rendered = new Set()
                  const fmt = (k, v) => {
                    if (k === 'created_at' || k === 'valid_at' || k === 'invalid_at') return formatDateTime(v)
                    if (k === 'stage_index') return `S${v}`
                    if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3).replace(/\.?0+$/, '')
                    return String(v)
                  }

                  return (
                    <div className="lg-detail-content">
                      <div className="lg-edge-header">
                        {d.source_name} → {d.name || t.related} → {d.target_name}
                      </div>
                      <div className="lg-detail-row">
                        <span className="lg-detail-label">{t.id}:</span>
                        <span className="lg-detail-value lg-uuid-text">{d.uuid}</span>
                      </div>
                      <div className="lg-detail-row">
                        <span className="lg-detail-label">{t.type}:</span>
                        <span className="lg-detail-value">{d.fact_type || d.type || t.unknown}</span>
                      </div>
                      {ORDERED.map(([k, label]) => {
                        const v = merged[k]
                        if (v == null || v === '' || rendered.has(k)) return null
                        // fact/description 互斥, 其中一个渲染后跳过另一个
                        if (k === 'fact' || k === 'description') {
                          if (rendered.has('fact') || rendered.has('description')) return null
                        }
                        rendered.add(k)
                        return (
                          <div className="lg-detail-row" key={k}>
                            <span className="lg-detail-label">{label}:</span>
                            <span className="lg-detail-value">{fmt(k, v)}</span>
                          </div>
                        )
                      })}
                      {/* 剩余业务字段 (未出现在 ORDERED 里) */}
                      {Object.keys(merged).map(k => {
                        if (HIDDEN.has(k) || rendered.has(k)) return null
                        const v = merged[k]
                        if (v == null || v === '' || typeof v === 'object') return null
                        return (
                          <div className="lg-detail-row" key={k}>
                            <span className="lg-detail-label">{k.replace(/_/g, ' ')}:</span>
                            <span className="lg-detail-value">{fmt(k, v)}</span>
                          </div>
                        )
                      })}
                    </div>
                  )
                })()
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
