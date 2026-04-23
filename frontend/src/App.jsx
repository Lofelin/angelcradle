/**
 * [INPUT]: react, ./i18n, shadcn/ui (Button, Select, ToggleGroup, Card)
 * [OUTPUT]: App 根组件 — Angel Cradle 主界面
 * [POS]: 应用入口视图，消费 SSE 流驱动孕育模拟
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */
import { useState, useEffect, useRef, useReducer, useCallback, memo } from 'react'
import { Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom'
import messages, { translateKey } from './i18n'
import CITY_ZH from './data/cityZh'
import COUNTRY_ZH from './data/countryZh'
import { Button } from '@/components/ui/button'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Select as SelectPrimitive } from 'radix-ui'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { cn } from '@/lib/utils'
import { ArrowLeftRight, Maximize2, Minimize2, Scale, Ruler, Droplet, Activity, Heart, Wind, ChevronDown, Dna, Gauge, LayoutDashboard, Baby, Globe, Loader2 } from 'lucide-react'
import ConsolePanel from '@/components/ConsolePanel'
import WorldMap from '@/components/WorldMap'
import LifeGraph from '@/components/LifeGraph'
import { graphReducer, GRAPH_INITIAL, useCausalGraph } from '@/hooks/useCausalGraph'
import { useWombGraph } from '@/hooks/useWombGraph'
import Cradle from './Cradle'

const API = 'http://localhost:8000'
const WOMB_SESSION_KEY = 'wombSession'

const SPECIES_ICONS = { human: '\u{1F476}', dog: '\u{1F415}', cat: '\u{1F408}' }

const AGE_LABELS = {
  en: { very_young: '<20', optimal: '20-29', moderate: '30-34', advanced: '35-39', very_advanced: '40+' },
  zh: { very_young: '<20\u5C81', optimal: '20-29\u5C81', moderate: '30-34\u5C81', advanced: '35-39\u5C81', very_advanced: '40+\u5C81' },
}

const EMPTY_BLUEPRINT = { phenotype_key: 'race', phenotypes: [], gestation_days: 0, offspring: {}, miscarriage_rate: 0, stillbirth_rate: 0, defects: {}, stages: [] }

function getTime() {
  const now = new Date()
  return now.toLocaleTimeString('en-US', { hour12: false }) + '.' + String(now.getMilliseconds()).padStart(3, '0')
}

function flattenToLogs(obj, time, stageName = '') {
  if (!obj || typeof obj !== 'object') return []
  const prefix = stageName ? stageName.toUpperCase().replace(/_/g, ' ') : ''
  const entries = []
  for (const [k, v] of Object.entries(obj)) {
    if (k.startsWith('_')) continue
    if (Array.isArray(v)) {
      v.forEach((item, i) => {
        const text = typeof item === 'object' ? JSON.stringify(item) : String(item)
        entries.push({ time, type: 'stage_data', tag: prefix, text: `${k.replace(/_/g, ' ')} [${i}]: ${text}` })
      })
    } else if (v && typeof v === 'object') {
      for (const [k2, v2] of Object.entries(v)) {
        entries.push({ time, type: 'stage_data', tag: prefix, text: `${k.replace(/_/g, ' ')}.${k2.replace(/_/g, ' ')}: ${String(v2)}` })
      }
    } else {
      entries.push({ time, type: 'stage_data', tag: prefix, text: `${k.replace(/_/g, ' ')}: ${String(v)}` })
    }
  }
  return entries
}


function wombReducer(state, action) {
  switch (action.type) {
    case 'RESET':
      return { logs: [], stageProgress: {}, maternalProgress: {}, currentStage: '', statusText: '', babyState: null, environment: null, parentGenomes: null, vitals: null, running: true, startedAt: Date.now(), elapsed: null, stageTimings: {} }
    case 'SSE_EVENT': {
      const { data, ts, t, lang } = action
      // thinking heartbeat: overwrite last log of same type (no spam), keep console alive
      if (data.event === 'stage' && (data.status === 'thinking' || data.status === 'maternal_thinking')) {
        const log = { time: ts, type: data.event, data }
        const last = state.logs[state.logs.length - 1]
        const logs = (last && last.data?.status === data.status)
          ? [...state.logs.slice(0, -1), log]
          : [...state.logs, log]
        return { ...state, logs }
      }
      const newLogs = [...state.logs, { time: ts, type: data.event || 'data', data }]
      let { stageProgress, maternalProgress, currentStage, statusText, babyState, environment, parentGenomes, vitals, running, stageTimings } = state

      if (data.event === 'stage' && data.status === 'done' && data.response && typeof data.response === 'object') {
        newLogs.push(...flattenToLogs(data.response, ts, data.stage))
      }
      if (data.event === 'stage' && data.status === 'maternal_response_done' && data.maternal_response && typeof data.maternal_response === 'object') {
        newLogs.push(...flattenToLogs(data.maternal_response, ts, 'MATERNAL'))
      }

      if (data.event === 'birthplace') {
        // 记录出生地信息，后续可用于地图展示
      } else if (data.event === 'environment') {
        environment = data.result
      } else if (data.event === 'parent_genomes') {
        parentGenomes = data.result
      } else if (data.event === 'offspring_fate') {
        babyState = { sex: data.sex, phenotype: data.phenotype, defects: data.defects, stillborn: data.stillborn, stages: {} }
      } else if (data.event === 'stage') {
        if (data.status === 'in_progress') {
          currentStage = data.stage
          statusText = t.developing(data.stage, data.gestation_day)
          stageProgress = { ...stageProgress, [data.stage]: 'active' }
          stageTimings = { ...stageTimings, [data.stage]: { startedAt: Date.now() } }
        } else if (data.status === 'vitals') {
          vitals = data.vitals
        } else if (data.status === 'hormones' || data.status === 'nutrients' || data.status === 'placenta' || data.status === 'immunity') {
          // 增量收集中间数据到阶段卡片，有什么就展示什么
          if (babyState && data.stage) {
            const prev = babyState.stages?.[data.stage] || {}
            const patch = {}
            if (data.status === 'hormones') patch.hormones = data.hormone_effects || {}
            if (data.status === 'nutrients') {
              patch.nutrients = data.nutrient_effects || {}
              if (data.teratogen_risk != null) patch.teratogen_risk = data.teratogen_risk
            }
            if (data.status === 'placenta') patch.placenta_efficiency = data.placenta_efficiency
            if (data.status === 'immunity') patch.immune_risks = data.immune_risks || {}
            babyState = { ...babyState, stages: { ...babyState.stages, [data.stage]: { ...prev, ...patch } } }
          }
        } else if (data.status === 'done') {
          stageProgress = { ...stageProgress, [data.stage]: 'done' }
          statusText = t.done(data.stage)
          if (babyState && data.response && typeof data.response === 'object') {
            const prev = babyState.stages?.[data.stage] || {}
            babyState = { ...babyState, stages: { ...babyState.stages, [data.stage]: { ...prev, ...data.response } } }
          }
          const prev = stageTimings[data.stage] || {}
          stageTimings = { ...stageTimings, [data.stage]: { ...prev, doneAt: Date.now() } }
        } else if (data.status === 'maternal_response') {
          statusText = t.maternal_responding
          maternalProgress = { ...maternalProgress, [data.stage]: 'active' }
          const prev = stageTimings[data.stage] || {}
          stageTimings = { ...stageTimings, [data.stage]: { ...prev, maternalStartedAt: Date.now() } }
        } else if (data.status === 'maternal_response_done') {
          maternalProgress = { ...maternalProgress, [data.stage]: 'done' }
          const prev = stageTimings[data.stage] || {}
          stageTimings = { ...stageTimings, [data.stage]: { ...prev, maternalDoneAt: Date.now() } }
        } else if (data.status === 'failed') {
          stageProgress = { ...stageProgress, [data.stage]: 'failed' }
        }
      } else if (data.event === 'born') {
        if (babyState) {
          babyState = { ...babyState, id: data.baby.id, alive: data.alive, first_cry: data.baby.first_cry, tendencies: data.baby.genes?.expression, birthplace: data.baby.birthplace }
        }
        statusText = data.alive ? `${t.born}!` : t.stillborn_label
      } else if (data.event === 'complete') {
        const elapsed = state.startedAt ? ((Date.now() - state.startedAt) / 1000).toFixed(1) : null
        statusText = `${t.complete} — ${t.alive}: ${data.total_alive}/${data.total_conceived}`
        return { ...state, logs: newLogs, stageProgress, maternalProgress, currentStage, statusText, babyState, environment, parentGenomes, vitals, running, elapsed }
      } else if (data.event === 'miscarriage') {
        if (data.stage) {
          // 逐阶段流产（human）
          const rate = `${((data.adjusted_rate || 0) * 100).toFixed(1)}%`
          statusText = t.miscarriage_stage(data.stage, data.cause || 'unknown', rate)
        } else {
          // 旧格式流产（非 human）
          statusText = t.miscarriage(data.message)
        }
      }

      return { ...state, logs: newLogs, stageProgress, maternalProgress, currentStage, statusText, babyState, environment, parentGenomes, vitals, running, stageTimings }
    }
    case 'CLOSE':
      return { ...state, running: false, logs: [...state.logs, { time: getTime(), type: 'system', text: action.text }] }
    case 'CLEAR_PROGRESS':
      return { ...state, stageProgress: {}, maternalProgress: {}, statusText: '', babyState: null, environment: null, parentGenomes: null, vitals: null, stageTimings: {} }
    default:
      return state
  }
}

const INIT_STATE = { logs: [], stageProgress: {}, maternalProgress: {}, currentStage: '', statusText: '', babyState: null, environment: null, parentGenomes: null, vitals: null, running: false, startedAt: null, elapsed: null, stageTimings: {} }

// 模块级单例：保证 time-scale 与后端同步每个页面会话只执行一次。
// App 组件可能因路由切换/HMR/StrictMode 多次 mount——不做这个 latch，
// 每次 mount 都会发一次 PATCH 导致风暴（见 backend 日志 "turbo → turbo" 刷屏）。
let _timeScaleSynced = false

// 批量出生列表项：用 shadcn/ui 的 Card + Avatar 组件化
// memo 避免 SSE 每来一只 baby 导致全量 N 个 item 重渲染
const BatchBabyListItem = memo(function BatchBabyListItem({ baby, selected, lang, title, onClick }) {
  const loc = baby.birthplace?.city
    ? `${baby.birthplace.city}, ${baby.birthplace.name}`
    : (baby.birthplace?.name || '')
  return (
    <Card
      size="sm"
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() } }}
      title={title}
      className={cn(
        "flex-row items-center gap-3 px-3 py-2.5 cursor-pointer transition-colors select-none",
        selected
          ? "bg-primary/10 ring-primary"
          : "hover:bg-muted/60",
      )}
    >
      <Avatar size="sm" className="shrink-0">
        <AvatarFallback className="text-sm">
          {baby.sex === 'male' ? '\u{1F466}' : '\u{1F467}'}
        </AvatarFallback>
      </Avatar>
      <span className="font-heading font-semibold tabular-nums shrink-0 text-foreground">
        {baby.id.slice(-8)}
      </span>
      {loc && <span className="text-muted-foreground shrink-0 truncate max-w-[45%]">{loc}</span>}
      <span className="flex-1 min-w-0 truncate text-muted-foreground">{baby.first_cry}</span>
    </Card>
  )
})

function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const tab = location.pathname.split('/')[1] || 'womb'

  const [lang, setLang] = useState(() => localStorage.getItem('lang') || 'en')
  const [timeScale, setTimeScale] = useState(() => localStorage.getItem('timeScale') || 'normal')
  const [species, setSpecies] = useState('human')
  const [speciesList, setSpeciesList] = useState([])
  const [selectedSex, setSelectedSex] = useState('random')
  const [selectedPhenotype, setSelectedPhenotype] = useState('random')
  const [selectedNutrition, setSelectedNutrition] = useState('random')
  const [selectedStress, setSelectedStress] = useState('random')
  const [selectedToxin, setSelectedToxin] = useState('random')
  const [selectedAge, setSelectedAge] = useState('random')
  const [selectedOffspring, setSelectedOffspring] = useState('random')
  const [blueprint, setBlueprint] = useState(EMPTY_BLUEPRINT)
  const [blueprintReady, setBlueprintReady] = useState(false)
  // 孕育模式：single（SSE 单个）/ batch（SSE 批量）
  const [conceiveMode, setConceiveMode] = useState('single')
  const [batchCount, setBatchCount] = useState(10)
  const [batchConcurrency, setBatchConcurrency] = useState(4)
  const [batchRunning, setBatchRunning] = useState(false)
  const [batchResult, setBatchResult] = useState(null)
  // 批量实时进度：{done, total, conceived, miscarriages, failed, elapsed_sec}
  const [batchProgress, setBatchProgress] = useState(null)
  // 最近 5 只 baby 滚动展示
  const [batchRecentBabies, setBatchRecentBabies] = useState([])
  // 批量 SSE 日志：供控制台展示（上限 2000 条防内存泄漏）
  const [batchLogs, setBatchLogs] = useState([])
  // 选中的 baby（点击左侧列表，在右下显示详情）
  const [batchSelectedBaby, setBatchSelectedBaby] = useState(null)
  // 完整 baby 数据（懒加载，从 /baby/{id} fetch gestation_log 用于渲染阶段卡）
  const [batchSelectedFull, setBatchSelectedFull] = useState(null)
  const [batchSelectedLoading, setBatchSelectedLoading] = useState(false)
  // 按需缓存：点过的 baby full data 存在这里，再次切回时秒开（上限 100 条）
  const batchFullCacheRef = useRef(new Map())
  // 进入养育按钮：admit 请求 loading 态
  const [batchAdmitLoading, setBatchAdmitLoading] = useState(false)
  // 批量页面用户是否手动选过（手动选后不再自动跟随最新）
  const batchUserPickedRef = useRef(false)
  // 批量页面阶段卡展开的 tag（类似单个孕育的 expandedTag）
  const [batchExpandedTag, setBatchExpandedTag] = useState(null)
  const batchEventSourceRef = useRef(null)
  const batchConsoleRef = useRef(null)
  const [state, dispatch] = useReducer(wombReducer, INIT_STATE)
  const [graphState, graphDispatch] = useReducer(graphReducer, GRAPH_INITIAL)
  const graphStateRef = useRef(graphState)
  graphStateRef.current = graphState
  const causalGraph = useCausalGraph(graphState, graphDispatch)
  // 子宫实时图谱: 从 SSE graph_delta 事件增量构建
  const wombGraph = useWombGraph()
  const consoleRef = useRef(null)
  const leftPanelRef = useRef(null)
  const stageCardsRef = useRef(null)
  const [expandedTag, setExpandedTag] = useState(null)
  const [consoleFullscreen, setConsoleFullscreen] = useState(false)
  const [showGeneticPopover, setShowGeneticPopover] = useState(false)
  const [viewMode, setViewMode] = useState('split')
  // 布局态由 viewMode 单向派生：'graph' → 左图谱全屏；'workbench' → 右工作区全屏；'split' → 双栏。
  const graphFullscreen = viewMode === 'graph'
  const workbenchFullscreen = viewMode === 'workbench'
  const toggleGraphFullscreen = () => setViewMode(v => v === 'graph' ? 'split' : 'graph')
  const [headerScrolled, setHeaderScrolled] = useState(false)
  // 二级页面（如 /cradle/:babyId）：顶部导航永久显示下方边框，不依赖滚动
  const isSecondaryPage = !!location.pathname.split('/')[2]
  const contentScrollRef = useRef(null)
  const [admittingToCradle, setAdmittingToCradle] = useState(false)

  const t = messages[lang]

  // 捕获右侧内容区内"主内容滚动容器"的滚动事件（scroll 不冒泡，用 capture 捕获）
  // 仅当被滚动元素标记了 data-scroll-root="true" 才触发阴影切换，避免聊天框、
  // 控制台、子面板等内部滚动都误触发（如宝宝详情页只有 chat 滚动时不该出阴影）。
  useEffect(() => {
    const el = contentScrollRef.current
    if (!el) return
    const onScroll = (e) => {
      if (e.target?.dataset?.scrollRoot !== 'true') return
      const top = e.target.scrollTop ?? 0
      setHeaderScrolled(top > 2)
    }
    el.addEventListener('scroll', onScroll, true)
    return () => el.removeEventListener('scroll', onScroll, true)
  }, [])

  // 路由切换时重置 headerScrolled：
  // 短页面不触发 scroll 事件，state 会保留上一页的 true 值，导致"一级页面"也带着上一页的阴影。
  useEffect(() => { setHeaderScrolled(false) }, [location.pathname])

  useEffect(() => {
    fetch(`${API}/species`)
      .then(r => r.json())
      .then(data => setSpeciesList(data.species))
      .catch(() => setSpeciesList(['human', 'dog', 'cat']))
    // 速率同步：localStorage 优先，服务器重启后自动恢复用户偏好。
    // 先 GET 拿服务端当前值；值已对齐则零成本 return，值不一致再 PATCH——
    // 避免每次 remount 都盲发 PATCH。_timeScaleSynced 守门单页会话只跑一次。
    if (_timeScaleSynced) return
    _timeScaleSynced = true
    const savedTs = localStorage.getItem('timeScale')
    const isValid = savedTs && ['slow', 'normal', 'fast', 'turbo'].includes(savedTs)
    fetch(`${API}/system/time-scale`)
      .then(r => r.json())
      .then(data => {
        const serverTs = data.time_scale
        if (isValid && savedTs !== serverTs) {
          return fetch(`${API}/system/time-scale`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ time_scale: savedTs }),
          }).then(r => r.ok && setTimeScale(savedTs))
        }
        localStorage.setItem('timeScale', serverTs)
        setTimeScale(serverTs)
      })
      .catch(() => { _timeScaleSynced = false /* 网络失败允许下次重试 */ })
  }, [])

  useEffect(() => {
    setSelectedSex('random')
    setSelectedPhenotype('random')
    setSelectedNutrition('random')
    setSelectedStress('random')
    setSelectedToxin('random')
    setSelectedAge('random')
    setSelectedOffspring('random')
    setBlueprintReady(false)
    fetch(`${API}/species/${species}/blueprint`)
      .then(r => r.json())
      .then(bp => { setBlueprint(bp); setBlueprintReady(true) })
      .catch(() => { setBlueprint(EMPTY_BLUEPRINT); setBlueprintReady(true) })
  }, [species])


  useEffect(() => {
    if (consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight
    }
  }, [state.logs.length])

  // 批量控制台自动滚底：新日志追加时保持最新可见
  useEffect(() => {
    if (batchConsoleRef.current) {
      batchConsoleRef.current.scrollTop = batchConsoleRef.current.scrollHeight
    }
  }, [batchLogs.length])

  // 批量出生列表自动滚底：新 baby 追加到末尾，滚到底展示最新
  // ScrollArea 是 radix 封装，真正的滚动容器是 [data-slot="scroll-area-viewport"]，
  // 通过容器 id 向下定位到 viewport
  useEffect(() => {
    const root = document.getElementById('batch-baby-scroll')
    if (!root) return
    const viewport = root.querySelector('[data-slot="scroll-area-viewport"]')
    if (viewport) viewport.scrollTop = viewport.scrollHeight
  }, [batchRecentBabies.length])

  // 列表点击 handler 工厂：返回带 baby 捕获的稳定引用，配合 memo 减少重渲染
  const handleBatchItemClick = useCallback((baby) => () => {
    batchUserPickedRef.current = true
    setBatchSelectedBaby(baby)
  }, [])

  // 进入养育：先请求 /cradle/admit 落库到摇篮系统，成功后再跳转
  const handleBatchAdmit = useCallback(async (babyId) => {
    if (!babyId || batchAdmitLoading) return
    setBatchAdmitLoading(true)
    try {
      const resp = await fetch(`${API}/cradle/admit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ baby_id: babyId }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await resp.json().catch(() => null)  // consume body but don't block on parse errors
      navigate(`/cradle/${babyId}`)
    } catch (e) {
      console.error('[admit] failed:', e)
      // 失败依然跳转（admit 幂等；若后端真有问题，摇篮页会再报错兜底）
      navigate(`/cradle/${babyId}`)
    } finally {
      setBatchAdmitLoading(false)
    }
  }, [batchAdmitLoading, navigate])

  // 批量：首次出现第一只 baby 时自动选中，之后不再自动跟随（避免持续切换导致卡顿）
  useEffect(() => {
    if (batchUserPickedRef.current) return
    if (batchSelectedBaby) return  // 已选中则不再自动切
    if (batchRecentBabies.length === 0) return
    setBatchSelectedBaby(batchRecentBabies[0])
  }, [batchRecentBabies, batchSelectedBaby])

  // 选中变化时懒加载 full baby data（含 gestation_log），命中缓存秒开
  useEffect(() => {
    const id = batchSelectedBaby?.id
    if (!id) {
      setBatchSelectedFull(null)
      return
    }
    if (batchSelectedFull?.id === id) return
    setBatchExpandedTag(null)
    // 命中缓存：立即填充，无需 fetch
    const cached = batchFullCacheRef.current.get(id)
    if (cached) {
      setBatchSelectedFull(cached)
      setBatchSelectedLoading(false)
      return
    }
    // 未命中：fetch 后写入缓存（LRU 上限 100 条，超限移除最早）
    setBatchSelectedLoading(true)
    setBatchSelectedFull(null)
    let cancelled = false
    fetch(`${API}/baby/${encodeURIComponent(id)}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (cancelled) return
        if (data) {
          const cache = batchFullCacheRef.current
          cache.set(id, data)
          // 简易 LRU：先进先出裁剪到 100
          if (cache.size > 100) {
            const firstKey = cache.keys().next().value
            cache.delete(firstKey)
          }
        }
        setBatchSelectedFull(data || null)
      })
      .catch(() => { if (!cancelled) setBatchSelectedFull(null) })
      .finally(() => { if (!cancelled) setBatchSelectedLoading(false) })
    return () => { cancelled = true }
  }, [batchSelectedBaby?.id, batchSelectedFull?.id])

  // 子宫图谱节流 fetch：关键事件后从后端 lifegraph 拉取最新图谱
  const wombGraphBabyIdRef = useRef(null)
  const wombGraphFetchTimerRef = useRef(null)

  const fetchWombGraph = useCallback(() => {
    // 进入宝宝详情（/cradle/*）后，图谱由 Cradle 自行加载，子宫侧停止覆盖
    if (window.location.pathname.startsWith('/cradle')) return
    const babyId = wombGraphBabyIdRef.current
    if (!babyId) return
    // 拉取后端已落库的 womb_graph 快照 (archive/{id}/womb_graph.json)
    // 历史孕育的图谱在此恢复; 正在孕育的由 SSE graph_delta 事件增量构建
    fetch(`${API}/baby/${babyId}/womb-graph`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data?.nodes?.length > 0) {
          wombGraph.loadSnapshot(data)
        }
      })
      .catch(() => { /* ignore */ })
  }, [wombGraph])

  const scheduleWombGraphFetch = useCallback(() => {
    if (wombGraphFetchTimerRef.current) clearTimeout(wombGraphFetchTimerRef.current)
    wombGraphFetchTimerRef.current = setTimeout(fetchWombGraph, 300)
  }, [fetchWombGraph])

  // 把一条 SSE URL 绑到 EventSource 上，统一处理 session 识别 / 事件分发 / 关闭清理。
  // 会话结束（complete/error/miscarriage 前置终止）后清掉 localStorage，避免刷新复活死会话。
  const attachSessionStream = useCallback((url) => {
    const source = new EventSource(url)
    source.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.event === 'session') {
          if (data.session_id && data.status === 'running') {
            localStorage.setItem(WOMB_SESSION_KEY, JSON.stringify({ id: data.session_id, ts: Date.now() }))
          }
          return
        }
        if (data.event === 'complete' || data.event === 'error') {
          localStorage.removeItem(WOMB_SESSION_KEY)
        }
        dispatch({ type: 'SSE_EVENT', data, ts: getTime(), t, lang })

        // 子宫实时图谱：消费 graph_delta 事件增量合并
        wombGraph.applyEvent(data)

        // 子宫图谱：从 SSE 事件抓 baby_id，关键事件后节流 fetch 后端 lifegraph
        if (data.baby_id && !wombGraphBabyIdRef.current) {
          wombGraphBabyIdRef.current = data.baby_id  // 取第一个 baby（多胎暂只展示首个）
        }
        if (data.event === 'offspring_fate' || data.event === 'born' || data.event === 'complete'
            || (data.event === 'stage' && data.status === 'done')) {
          scheduleWombGraphFetch()
        }
      } catch { /* ignore */ }
    }
    source.onerror = () => {
      dispatch({ type: 'CLOSE', text: t.closed })
      source.close()
    }
    return source
  }, [t, lang, scheduleWombGraphFetch])

  const conceive = useCallback(() => {
    dispatch({ type: 'RESET' })
    graphDispatch({ type: 'CLEAR_GRAPH' })
    wombGraph.reset()  // 清空实时图谱, 每次新孕育从零开始生长
    wombGraphBabyIdRef.current = null  // 重置子宫图谱 baby 标识
    const params = new URLSearchParams({ species, lang })
    if (selectedSex !== 'random') params.set('sex', selectedSex)
    if (selectedPhenotype !== 'random') params.set('phenotype', selectedPhenotype)
    if (selectedNutrition !== 'random') params.set('nutrition', selectedNutrition)
    if (selectedStress !== 'random') params.set('stress', selectedStress)
    if (selectedToxin !== 'random') params.set('toxin_exposure', selectedToxin)
    if (selectedAge !== 'random') params.set('maternal_age_factor', selectedAge)
    if (selectedOffspring !== 'random') params.set('offspring_count', selectedOffspring)

    attachSessionStream(`${API}/conceive/stream?${params}`)
  }, [species, lang, selectedSex, selectedPhenotype, selectedNutrition, selectedStress, selectedToxin, selectedAge, selectedOffspring, attachSessionStream])

  // 批量孕育：GET /conceive/batch/stream，通过 EventSource 订阅实时进度
  const batchConceive = useCallback(() => {
    if (batchRunning) return
    // 关掉上一个连接（如果有残留）
    if (batchEventSourceRef.current) {
      try { batchEventSourceRef.current.close() } catch { /* ignore */ }
      batchEventSourceRef.current = null
    }
    setBatchRunning(true)
    setBatchResult(null)
    setBatchProgress({ done: 0, total: batchCount, conceived: 0, miscarriages: 0, failed: 0, elapsed_sec: 0 })
    setBatchRecentBabies([])
    setBatchLogs([])
    setBatchSelectedBaby(null)
    setBatchSelectedFull(null)
    setBatchExpandedTag(null)
    batchUserPickedRef.current = false  // 复位：新批次重新自动跟随最新
    batchFullCacheRef.current.clear()   // 清缓存：不同批次的 baby id 可能重复（虽然 UUID 不会，但 id 语义边界换了）
    // 跳转到批量孕育中页面（二级路由）
    navigate('/womb/batch')

    // 自动选引擎：大批量（> 2000）用进程绕 GIL；小批量用线程启动快
    const autoEngine = batchCount > 2000 ? 'process' : 'thread'
    const params = new URLSearchParams({
      species, lang,
      count: String(batchCount),
      concurrency: String(batchConcurrency),
      mode: autoEngine,
    })
    if (selectedNutrition !== 'random') params.set('nutrition', selectedNutrition)
    if (selectedStress !== 'random') params.set('stress', selectedStress)
    if (selectedToxin !== 'random') params.set('toxin_exposure', selectedToxin)
    if (selectedAge !== 'random') params.set('maternal_age_factor', selectedAge)

    const source = new EventSource(`${API}/conceive/batch/stream?${params}`)
    batchEventSourceRef.current = source

    const cleanup = () => {
      try { source.close() } catch { /* ignore */ }
      batchEventSourceRef.current = null
      setBatchRunning(false)
    }

    // 事件 → 日志项的格式化器（控制台展示用）
    const appendLog = (entry) => {
      setBatchLogs(prev => {
        const next = [...prev, { ts: Date.now(), ...entry }]
        return next.length > 2000 ? next.slice(-2000) : next
      })
    }

    source.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        switch (data.event) {
          case 'start':
            setBatchProgress(p => ({ ...(p || {}), done: 0, total: data.total, conceived: 0, miscarriages: 0, failed: 0, elapsed_sec: 0 }))
            appendLog({
              kind: 'system',
              text: `${lang === 'zh' ? '批量启动' : 'Batch started'}: total=${data.total}, concurrency=${data.concurrency}, mode=${data.mode}`,
            })
            break
          case 'progress':
            setBatchProgress({
              done: data.done, total: data.total,
              conceived: data.conceived, miscarriages: data.miscarriages,
              failed: data.failed, elapsed_sec: data.elapsed_sec,
            })
            appendLog({
              kind: 'progress',
              text: `${lang === 'zh' ? '进度' : 'progress'}: ${data.done}/${data.total} · ${lang === 'zh' ? '成功' : 'ok'}=${data.conceived} · ${lang === 'zh' ? '流产' : 'mis'}=${data.miscarriages} · ${lang === 'zh' ? '失败' : 'fail'}=${data.failed} · ${data.elapsed_sec}s`,
            })
            break
          case 'baby':
            if (data.baby) {
              // 由下到上：新 baby 追加到末尾，容器自动滚到底展示最新
              setBatchRecentBabies(prev => {
                const next = [...prev, data.baby]
                return next.length > 1000 ? next.slice(-1000) : next
              })
              const b = data.baby
              const loc = b.birthplace?.city ? `${b.birthplace.city}, ${b.birthplace.name}` : (b.birthplace?.name || '')
              appendLog({
                kind: 'baby',
                text: `${lang === 'zh' ? '出生' : 'born'} [${data.done}/${data.total}] ${b.sex === 'male' ? '\u{1F466}' : '\u{1F467}'} ${b.id.slice(-8)} ${loc ? '· ' + loc : ''} · ${b.first_cry}`,
              })
            }
            setBatchProgress(p => p ? { ...p, done: data.done, conceived: (p.conceived || 0) + 1 } : p)
            break
          case 'miscarriage':
            setBatchProgress(p => p ? { ...p, done: data.done, miscarriages: (p.miscarriages || 0) + 1 } : p)
            appendLog({
              kind: 'miscarriage',
              text: `${lang === 'zh' ? '流产' : 'miscarriage'} [${data.done}/${data.total}]`,
            })
            break
          case 'baby_failed':
            setBatchProgress(p => p ? { ...p, done: data.done, failed: (p.failed || 0) + 1 } : p)
            appendLog({
              kind: 'error',
              text: `${lang === 'zh' ? '失败' : 'failed'} [${data.done}/${data.total}]: ${data.error || 'unknown'}`,
            })
            break
          case 'complete':
            setBatchResult({
              conceived: data.conceived,
              miscarriages: data.miscarriages,
              failed: data.failed,
              elapsed_sec: data.elapsed_sec,
              throughput_per_sec: data.throughput_per_sec,
            })
            appendLog({
              kind: 'complete',
              text: `${lang === 'zh' ? '批量完成' : 'Batch complete'}: ${lang === 'zh' ? '成功' : 'ok'}=${data.conceived} · ${lang === 'zh' ? '流产' : 'mis'}=${data.miscarriages} · ${lang === 'zh' ? '失败' : 'fail'}=${data.failed} · ${data.elapsed_sec}s · ${data.throughput_per_sec}${t.batch_per_sec}`,
            })
            cleanup()
            break
          default:
            break
        }
      } catch { /* ignore malformed events */ }
    }
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        setBatchRunning(false)
        batchEventSourceRef.current = null
      } else {
        appendLog({ kind: 'error', text: lang === 'zh' ? '连接中断' : 'Connection lost' })
        setBatchResult({
          conceived: 0, miscarriages: 0, failed: batchCount,
          elapsed_sec: 0, throughput_per_sec: 0,
          error: 'Connection lost',
        })
        cleanup()
      }
    }
  }, [batchRunning, species, lang, batchCount, batchConcurrency, selectedNutrition, selectedStress, selectedToxin, selectedAge, navigate])

  // 组件卸载时清理 EventSource
  useEffect(() => () => {
    if (batchEventSourceRef.current) {
      try { batchEventSourceRef.current.close() } catch { /* ignore */ }
    }
  }, [])

  // 刷新后恢复进行中的孕育：读 localStorage → 探针 /sessions/{id} → 订阅同一 session 回放事件。
  // 仅在组件挂载时执行一次；失效会话会被清理。
  const resumedRef = useRef(false)
  useEffect(() => {
    if (resumedRef.current) return
    resumedRef.current = true
    const raw = localStorage.getItem(WOMB_SESSION_KEY)
    if (!raw) return
    let saved
    try { saved = JSON.parse(raw) } catch {
      localStorage.removeItem(WOMB_SESSION_KEY)
      return
    }
    if (!saved?.id) return
    fetch(`${API}/conceive/sessions/${saved.id}`)
      .then(r => {
        if (!r.ok) {
          localStorage.removeItem(WOMB_SESSION_KEY)
          return null
        }
        return r.json()
      })
      .then(info => {
        if (!info) return
        dispatch({ type: 'RESET' })
        attachSessionStream(`${API}/conceive/stream?session_id=${encodeURIComponent(saved.id)}`)
      })
      .catch(() => localStorage.removeItem(WOMB_SESSION_KEY))
  }, [attachSessionStream])

  const { logs, stageProgress, maternalProgress, statusText, babyState, running, stageTimings } = state
  const environment = state.environment
  const tk = (v) => translateKey(v, lang)
  const isConceiving = running || Object.keys(stageProgress).length > 0

  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [running])

  // 孕育过程中左屏内容变化时，自动滑到底部
  useEffect(() => {
    if (isConceiving && leftPanelRef.current) {
      requestAnimationFrame(() => {
        leftPanelRef.current?.scrollTo({ top: leftPanelRef.current.scrollHeight, behavior: 'smooth' })
      })
    }
  }, [isConceiving, babyState, environment, state.vitals, stageProgress])

  // 阶段卡片自动滚底（running 变化时按钮出现/消失，需要再滚一次）
  // 多时间点重试：rAF + 150ms + 400ms，兼容重入时 animate-in / 异步布局导致的 scrollHeight 晚到
  useEffect(() => {
    if (!isConceiving) return
    const el = stageCardsRef.current
    if (!el) return
    const toBottom = () => el.scrollTo({ top: el.scrollHeight, behavior: 'auto' })
    const raf = requestAnimationFrame(toBottom)
    const t1 = setTimeout(toBottom, 150)
    const t2 = setTimeout(toBottom, 400)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [isConceiving, stageProgress, maternalProgress, running])

  // ── Log renderer ──
  const renderLog = (entry, i) => {
    const { type, data, text, time } = entry

    if (type === 'system') {
      return <div key={i} className="log-system"><span className="time">{time}</span> {text}</div>
    }
    if (type === 'stage_data') {
      const tag = entry.tag ? tk(entry.tag) : ''
      const colonIdx = text.indexOf(':')
      if (colonIdx > -1) {
        const rawKey = text.slice(0, colonIdx)
        const value = text.slice(colonIdx + 1)
        const translatedKey = rawKey.includes('.')
          ? rawKey.split('.').map(part => tk(part.trim())).join('.')
          : tk(rawKey)
        return (
          <div key={i} className="log-stage-done">
            <span className="time">{time}</span>
            {tag && <span className="tag">{tag}</span>}
            <span className="text-primary">{translatedKey}:</span>
            <span style={{ color: '#aaa' }}>{value}</span>
          </div>
        )
      }
      return <div key={i} className="log-stage-done"><span className="time">{time}</span>{tag && <span className="tag">{tag}</span>} {text}</div>
    }
    if (type === 'raw') {
      return <div key={i} className="log-raw"><span className="time">{time}</span> {text}</div>
    }

    const event = data?.event || type

    if (event === 'parent_genomes') {
      return (
        <div key={i} className="log-env">
          <span className="time">{time}</span>
          <span className="tag">{lang === 'zh' ? '基因组' : 'GENOME'}</span>
          {lang === 'zh' ? '父母基因组已生成' : 'Parent genomes generated'}
        </div>
      )
    }

    if (event === 'fate_roll') {
      const rollType = data.type
      const result = data.result
      if (rollType === 'miscarriage') {
        const rate = `${((result.adjusted_rate || 0) * 100).toFixed(1)}%`
        return (
          <div key={i} className={`log-fate ${result.miscarriage ? 'log-error' : ''}`}>
            <span className="time">{time}</span>
            <span className="tag">{t.fate}</span>
            {t.miscarriage_roll(result.miscarriage, rate)}
          </div>
        )
      }
      return (
        <div key={i} className="log-fate">
          <span className="time">{time}</span>
          <span className="tag">{t.fate}</span>
          {t.offspring_count(result)}
        </div>
      )
    }

    if (event === 'birthplace') {
      const bp = data.result
      if (bp) {
        return (
          <div key={i} className="log-env">
            <span className="time">{time}</span>
            <span className="tag">{t.birthplace_label}</span>
            {t.birthplace_info(
              lang === 'zh' && bp.code && COUNTRY_ZH[bp.code] ? COUNTRY_ZH[bp.code] : bp.name,
              bp.code,
              bp.coordinates.lat,
              bp.coordinates.lng,
              lang === 'zh' && bp.city ? (CITY_ZH[bp.city] || bp.city) : bp.city,
            )}
            {` [${t.birthplace_method[data.method] || data.method}]`}
          </div>
        )
      }
      return null
    }

    if (event === 'miscarriage') {
      if (data.stage) {
        const rate = `${((data.adjusted_rate || 0) * 100).toFixed(1)}%`
        return (
          <div key={i} className="log-error">
            <span className="time">{time}</span>
            <span className="tag">{t.fate}</span>
            {t.miscarriage_stage(tk(data.stage), tk(data.cause || 'unknown'), rate)}
          </div>
        )
      }
      return <div key={i} className="log-error"><span className="time">{time}</span> {t.miscarriage(data.message)}</div>
    }

    if (event === 'environment') {
      const env = data.result
      return (
        <div key={i} className="log-env">
          <span className="time">{time}</span>
          <span className="tag">{t.env}</span>
          {t.nutrition}: {tk(env.nutrition)} | {t.stress}: {tk(env.stress)} | {t.toxin}: {tk(env.toxin_exposure)} | {t.age}: {tk(env.maternal_age_factor)}
          {env.modifiers && ` | ${t.budget}: ${(env.modifiers.budget_multiplier * 100).toFixed(0)}% | ${t.risk}: ${env.modifiers.defect_risk_multiplier.toFixed(1)}x`}
        </div>
      )
    }

    if (event === 'offspring_fate') {
      return (
        <div key={i} className="log-fate">
          <span className="time">{time}</span>
          <span className="tag">{t.offspring} #{data.index}</span>
          {t.sex}: {tk(data.sex)} | {Object.entries(data.phenotype).map(([k, v]) => `${k}: ${tk(v)}`).join(' | ')}
          {data.defects.length > 0 && <span className="log-warn"> | {t.defects}: {data.defects.map(d => typeof d === 'object' ? tk((d.defect || '').replace(/_/g, ' ')) : tk(d.replace(/_/g, ' '))).join(', ')}</span>}
          {data.stillborn && <span className="log-error"> | {t.stillborn_label}</span>}
          {data.preterm?.preterm && <span className="log-warn"> | {lang === 'zh' ? '早产' : 'Preterm'}: {data.preterm.severity || ''} ({data.preterm.weeks}w)</span>}
        </div>
      )
    }

    if (event === 'stage') {
      if (data.status === 'in_progress') {
        return (
          <div key={i} className="log-stage-start">
            <span className="time">{time}</span>
            <span className="tag">{t.stage} {data.stage_num}/7</span>
            {t.developing(tk(data.stage), data.gestation_day)}
          </div>
        )
      }
      if (data.status === 'failed') {
        return (
          <div key={i} className="log-error">
            <span className="time">{time}</span>
            <span className="tag">{t.stage} {data.stage_num || '?'}/7</span>
            {tk(data.stage)} — {lang === 'zh' ? '失败' : 'FAILED'}{data.error ? `: ${data.error}` : data.message ? `: ${data.message}` : ''}
          </div>
        )
      }
      if (data.status === 'done') {
        return (
          <div key={i} className="log-stage-done">
            <span className="time">{time}</span>
            {'\u2713'} <span className="tag">{t.stage} {data.stage_num}/7</span>
            {t.done(tk(data.stage))}
            {data.budget_enforced && <span className="log-warn"> {t.budget_enforced}</span>}
          </div>
        )
      }
      if (data.status === 'maternal_response') {
        return <div key={i} className="log-maternal"><span className="time">{time}</span><span className="tag">{t.maternal}</span> {t.maternal_responding}</div>
      }
      if (data.status === 'maternal_response_done') {
        return (
          <div key={i} className="log-maternal">
            <span className="time">{time}</span>
            {'\u2713'} <span className="tag">{t.maternal}</span>
            {t.done(tk('feedback'))}
          </div>
        )
      }
      if (data.status === 'vitals') {
        const v = data.vitals || {}
        const parts = [v.heart_rate, v.weight, v.length].filter(Boolean)
        return (
          <div key={i} className="log-stage-start" style={{ color: '#8ab' }}>
            <span className="time">{time}</span>
            <span className="tag">{lang === 'zh' ? '体征' : 'VITALS'}</span>
            {parts.join(' | ')}
          </div>
        )
      }
      if (data.status === 'hormones') {
        const fx = data.hormone_effects || {}
        const parts = []
        if (fx.budget_penalty) parts.push(`${lang === 'zh' ? '预算惩罚' : 'budget penalty'}: ${(fx.budget_penalty * 100).toFixed(0)}%`)
        if (fx.risk_modifier) parts.push(`${lang === 'zh' ? '风险修正' : 'risk mod'}: ${fx.risk_modifier.toFixed(2)}x`)
        return (
          <div key={i} className="log-stage-start" style={{ color: '#a8b' }}>
            <span className="time">{time}</span>
            <span className="tag">{lang === 'zh' ? '激素' : 'HORMONES'}</span>
            {parts.length > 0 ? parts.join(' | ') : (lang === 'zh' ? '正常' : 'normal')}
          </div>
        )
      }
      if (data.status === 'nutrients') {
        const ne = data.nutrient_effects || {}
        const parts = []
        if (ne.budget_penalty) parts.push(`${lang === 'zh' ? '预算惩罚' : 'budget penalty'}: ${(ne.budget_penalty * 100).toFixed(0)}%`)
        if (ne.defect_risk_modifier) parts.push(`${lang === 'zh' ? '缺陷风险' : 'defect risk'}: ${ne.defect_risk_modifier.toFixed(2)}x`)
        if (data.teratogen_risk) parts.push(`${lang === 'zh' ? '致畸风险' : 'teratogen'}: ${data.teratogen_risk.toFixed(2)}x`)
        return (
          <div key={i} className="log-stage-start" style={{ color: '#ab8' }}>
            <span className="time">{time}</span>
            <span className="tag">{t.nutrients_label}</span>
            {parts.length > 0 ? parts.join(' | ') : (lang === 'zh' ? '正常' : 'normal')}
          </div>
        )
      }
      if (data.status === 'placenta') {
        return (
          <div key={i} className="log-stage-start" style={{ color: '#b8a' }}>
            <span className="time">{time}</span>
            <span className="tag">{t.placenta_label}</span>
            {lang === 'zh' ? '效率' : 'efficiency'}: {data.placenta_efficiency != null ? `${(data.placenta_efficiency * 100).toFixed(0)}%` : '-'}
          </div>
        )
      }
      if (data.status === 'immunity') {
        const risks = data.immune_risks || {}
        const parts = Object.entries(risks).map(([k, v]) => `${tk(k.replace(/_/g, ' '))}: ${typeof v === 'number' ? v.toFixed(2) : v}`)
        return (
          <div key={i} className="log-stage-start" style={{ color: '#8ba' }}>
            <span className="time">{time}</span>
            <span className="tag">{t.immunity_label}</span>
            {parts.join(' | ') || (lang === 'zh' ? '正常' : 'normal')}
          </div>
        )
      }
      if (data.status === 'developing') {
        return (
          <div key={i} className="log-stage-start" style={{ color: '#999' }}>
            <span className="time">{time}</span>
            <span className="tag">{t.stage} {data.stage_num}/7</span>
            {data.message || (lang === 'zh' ? '发育中...' : 'Developing...')}
          </div>
        )
      }
      if (data.status === 'thinking') {
        return (
          <div key={i} className="log-stage-start" style={{ color: '#999' }}>
            <span className="time">{time}</span>
            <span className="tag">{t.stage} {data.stage_num}/7</span>
            {tk(data.stage)} — {lang === 'zh' ? '发育中' : 'developing'}... {data.elapsed}s
          </div>
        )
      }
      if (data.status === 'maternal_thinking') {
        return (
          <div key={i} className="log-maternal">
            <span className="time">{time}</span>
            <span className="tag">{t.maternal}</span>
            {lang === 'zh' ? '反馈中' : 'responding'}... {data.elapsed}s
          </div>
        )
      }
      if (data.status === 'env_change') {
        return (
          <div key={i} className="log-env">
            <span className="time">{time}</span>
            <span className="tag">{lang === 'zh' ? '环境变化' : 'ENV CHANGE'}</span>
            {typeof data.event === 'string' ? data.event : JSON.stringify(data.event)}
          </div>
        )
      }
    }

    if (event === 'development_failed') {
      return (
        <div key={i} className="log-error">
          <span className="time">{time}</span>
          <span className="tag">{lang === 'zh' ? '发育失败' : 'DEV FAILED'}</span>
          #{data.index} {data.stage ? tk(data.stage) : ''} {data.error || data.message || ''}
        </div>
      )
    }

    if (event === 'offspring_lost') {
      return (
        <div key={i} className="log-error">
          <span className="time">{time}</span>
          <span className="tag">{lang === 'zh' ? '胎儿丢失' : 'LOST'}</span>
          #{data.index} — {data.cause ? tk(data.cause.replace(/_/g, ' ')) : ''}
        </div>
      )
    }

    if (event === 'born') {
      const baby = data.baby
      return (
        <div key={i} className={`log-born ${data.alive ? '' : 'log-error'}`}>
          <span className="time">{time}</span>
          <span className="tag">{data.alive ? t.born : t.stillborn_label}</span>
          {t.id}: {baby.id} | {tk(baby.species)} | {tk(baby.sex)}
          {baby.first_cry && <div className="first-cry">{baby.first_cry}</div>}
        </div>
      )
    }

    if (event === 'complete') {
      return (
        <div key={i} className="log-complete">
          <span className="time">{time}</span>
          <span className="tag">{t.complete}</span>
          {t.conceived}: {data.total_conceived} | {t.born_count}: {data.total_born} | {t.alive}: {data.total_alive}
          {state.elapsed && <span className="text-[#666]"> | {state.elapsed}s</span>}
        </div>
      )
    }

    return null
  }

  // 后代数量文本
  const offspringText = (() => {
    const o = blueprint.offspring
    if (!o || Object.keys(o).length === 0) return '\u2014'
    if (o.typical) return String(o.typical)
    if (o.min != null) return `${o.min}-${o.max}`
    if (o.average != null) return `~${o.average}`
    return '\u2014'
  })()

  // ── 蓝图面板 (孕育前) ──
  const renderBlueprintHeader = () => (
    <div className="flex items-center gap-3.5 px-2">
        <span className="text-[40px] leading-none">{SPECIES_ICONS[species] || '\u{1F9EC}'}</span>
        <div className="flex-1">
          <h1 className="font-heading text-xl font-semibold capitalize">{tk(species)}</h1>
        </div>
        <Select value={species} onValueChange={setSpecies}>
          <SelectTrigger size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {speciesList.map(s => (
              <SelectItem key={s} value={s}>{tk(s)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
    </div>
  )

  const WORKFLOW_STEPS = [
    { name: 'zygote', en: 'Zygote', zh: '受精卵', desc_en: 'Fertilization & initial cell division, establishing the genetic blueprint', desc_zh: '受精与初始细胞分裂，建立遗传蓝图' },
    { name: 'early_organogenesis', en: 'Early Organogenesis', zh: '早期器官发生', desc_en: 'Formation of major organ systems, neural tube closure & heart development', desc_zh: '主要器官系统形成，神经管闭合与心脏发育' },
    { name: 'late_organogenesis', en: 'Late Organogenesis', zh: '晚期器官发生', desc_en: 'Refinement of organ structures, limb patterning & facial features', desc_zh: '器官结构精细化，四肢与面部特征塑造' },
    { name: 'early_neurological', en: 'Early Neural', zh: '早期神经发育', desc_en: 'Brain regionalization, synapse formation & sensory pathway wiring', desc_zh: '大脑区域分化，突触形成与感觉通路连接' },
    { name: 'late_neurological', en: 'Late Neural', zh: '晚期神经发育', desc_en: 'Cortical folding, myelination & higher cognitive circuit assembly', desc_zh: '皮层折叠，髓鞘化与高级认知回路组装' },
    { name: 'fetal_movement', en: 'Fetal Movement', zh: '胎动', desc_en: 'Motor pattern development, breathing practice & sleep-wake cycles', desc_zh: '运动模式发育，呼吸练习与睡眠-觉醒周期' },
    { name: 'birth', en: 'Birth', zh: '出生', desc_en: 'Final maturation, immune transfer & preparation for extrauterine life', desc_zh: '最终成熟，免疫转移与子宫外生存准备' },
  ]

  // 左侧面板：系统就绪 + 发育流程；批量模式下叠加进度条 / 实时 baby 列表 / 完成摘要
  const renderBlueprint = () => (
    <div className="flex flex-col gap-6 px-1">
      {/* 系统就绪 */}
      <div>
        <div className="text-[11px] text-muted-foreground tracking-wider mb-2 flex items-center gap-1.5"><span className="inline-block w-1.5 h-1.5 rounded-full step-dot-running" />{lang === 'zh' ? '系统状态' : 'System Status'}</div>
        <h2 className="font-heading text-3xl font-bold tracking-tight leading-tight">{lang === 'zh' ? '准备就绪' : 'System Ready'}</h2>
        <p className="text-sm text-muted-foreground mt-1.5">{lang === 'zh' ? '系统已准备好模拟生命孕育' : 'System is ready to simulate life conception'}</p>
      </div>

      {/* 发育阶段流程 */}
      <div>
        <div className="text-[11px] text-muted-foreground tracking-wider mb-4">{lang === 'zh' ? '发育流程' : 'Workflow Steps'}</div>
        <div className="flex flex-col">
          {WORKFLOW_STEPS.map((step, i) => (
            <div key={step.name} className="flex gap-4 py-4 first:pt-0">
              <span className="text-2xl font-heading font-bold text-primary/70 w-8 shrink-0 tabular-nums pt-0.5">{String(i + 1).padStart(2, '0')}</span>
              <div className="flex-1 min-w-0">
                <div className="font-heading font-semibold text-[13px]">{lang === 'zh' ? step.zh : step.en}</div>
                <div className="text-xs text-muted-foreground/60 mt-1 leading-relaxed">{lang === 'zh' ? step.desc_zh : step.desc_en}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

    </div>
  )

  // ── 右侧参数面板 (孕育前) ──
  const renderParams = () => {
    const isBatch = conceiveMode === 'batch'
    return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto border border-border p-5 flex flex-col gap-6">
        {/* 模式选择（顶部） */}
        <div>
          <div className="text-[11px] text-muted-foreground tracking-wider mb-3">{lang === 'zh' ? '模式' : 'Mode'}</div>
          <ToggleGroup type="single" variant="outline" value={conceiveMode} onValueChange={(v) => { if (v) setConceiveMode(v) }} className="w-full">
            <ToggleGroupItem value="single" className="flex-1">{t.mode_single}</ToggleGroupItem>
            <ToggleGroupItem value="batch" className="flex-1">{t.mode_batch}</ToggleGroupItem>
          </ToggleGroup>
        </div>

        {/* 区域 01 — 基因蓝图（批量模式不显示；批量每个 baby 随机化 sex/phenotype/offspring） */}
        {!isBatch && (
          <div>
            <div className="text-[11px] text-muted-foreground tracking-wider mb-3">01 / {t.blueprint}</div>
            <div className="rounded-lg bg-muted/50 p-4 flex flex-col gap-4">
              <div>
                <div className="font-heading font-semibold text-foreground mb-2 text-sm capitalize">{t.sex}</div>
                <ToggleGroup type="single" variant="outline" value={selectedSex} onValueChange={(v) => { if (v) setSelectedSex(v) }} className="w-full">
                  {['random', 'male', 'female'].map(v => (
                    <ToggleGroupItem key={v} value={v} className="flex-1 capitalize">
                      {v === 'random' ? t.sex_random : v === 'male' ? t.sex_male : t.sex_female}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="font-heading font-semibold text-foreground mb-2 text-sm capitalize">{tk(blueprint.phenotype_key)}</div>
                  <Select value={selectedPhenotype} onValueChange={setSelectedPhenotype}>
                    <SelectTrigger className="w-full capitalize"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="random">{t.phenotype_random}</SelectItem>
                      {blueprint.phenotypes.map(p => <SelectItem key={p} value={p}>{tk(p)}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <div className="font-heading font-semibold text-foreground mb-2 text-sm capitalize">{t.offspring_label}</div>
                  <Select value={selectedOffspring} onValueChange={setSelectedOffspring}>
                    <SelectTrigger className="w-full capitalize"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="random">{t.sex_random}</SelectItem>
                      {[1,2,3,4,5,6].map(v => <SelectItem key={v} value={String(v)}>{v}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 分隔线 */}
        <div className="flex items-center gap-3">
          <div className="flex-1 border-t border-border" />
          <span className="text-[11px] text-muted-foreground tracking-wider">{lang === 'zh' ? '输入参数' : 'Input Parameters'}</span>
          <div className="flex-1 border-t border-border" />
        </div>

        {/* 区域 02 — 母体环境 */}
        <div>
          <div className="text-[11px] text-muted-foreground tracking-wider mb-3">{isBatch ? '01' : '02'} / {t.env_conditions}</div>
          <div className="rounded-lg bg-muted/50 p-4 flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="font-heading font-semibold text-foreground mb-2 text-sm capitalize">{t.nutrition}</div>
                <Select value={selectedNutrition} onValueChange={setSelectedNutrition}>
                  <SelectTrigger className="w-full capitalize"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="random">{t.sex_random}</SelectItem>
                    {['excellent', 'adequate', 'moderate_deficiency', 'severe_deficiency'].map(v => <SelectItem key={v} value={v}>{tk(v)}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <div className="font-heading font-semibold text-foreground mb-2 text-sm capitalize">{t.stress}</div>
                <Select value={selectedStress} onValueChange={setSelectedStress}>
                  <SelectTrigger className="w-full capitalize"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="random">{t.sex_random}</SelectItem>
                    {['minimal', 'mild', 'moderate', 'severe'].map(v => <SelectItem key={v} value={v}>{tk(v)}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="font-heading font-semibold text-foreground mb-2 text-sm capitalize">{t.toxin}</div>
                <Select value={selectedToxin} onValueChange={setSelectedToxin}>
                  <SelectTrigger className="w-full capitalize"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="random">{t.sex_random}</SelectItem>
                    {['none', 'mild', 'moderate', 'severe'].map(v => <SelectItem key={v} value={v}>{tk(v)}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <div className="font-heading font-semibold text-foreground mb-2 text-sm capitalize">{t.age}</div>
                <Select value={selectedAge} onValueChange={setSelectedAge}>
                  <SelectTrigger className="w-full capitalize"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="random">{t.sex_random}</SelectItem>
                    {Object.entries(AGE_LABELS[lang] || AGE_LABELS.en).map(([v, label]) => <SelectItem key={v} value={v}>{label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        </div>

        {/* 批量配置区（仅批量模式） */}
        {isBatch && (
          <div>
            <div className="text-[11px] text-muted-foreground tracking-wider mb-3">02 / {t.mode_batch}</div>
            <div className="rounded-lg bg-muted/50 p-4 flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="font-heading font-semibold text-foreground mb-2 text-sm">{t.batch_count}</div>
                  <input
                    type="number" min={1} max={10000} step={10}
                    value={batchCount}
                    onChange={(e) => setBatchCount(Math.max(1, Math.min(10000, Number(e.target.value) || 1)))}
                    className="w-full h-9 px-3 rounded-md bg-background border border-input text-sm tabular-nums"
                  />
                </div>
                <div>
                  <div className="font-heading font-semibold text-foreground mb-2 text-sm">{t.batch_concurrency}</div>
                  <Select value={String(batchConcurrency)} onValueChange={(v) => setBatchConcurrency(Number(v))}>
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {[1,2,4,8,16].map(v => <SelectItem key={v} value={String(v)}>{v}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 孕育按钮 */}
        <button
          className={cn(
            "w-full flex items-center justify-between px-5 py-3.5 text-base font-heading font-semibold text-primary bg-rose-50 border border-border transition-colors mt-auto",
            (isBatch && batchRunning) ? "opacity-60 cursor-not-allowed" : "hover:bg-rose-100 cursor-pointer",
          )}
          onClick={isBatch ? batchConceive : conceive}
          disabled={isBatch && batchRunning}
        >
          {isBatch ? (batchRunning ? t.batch_running : t.batch_conceive) : t.conceive}
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M17 8l4 4m0 0l-4 4m4-4H3" /></svg>
        </button>
      </div>
    </div>
    )
  }

  // ── 发育监视器 (孕育后) ──
  // 遗传特征卡片内容（inline 与 popover 共用）
  const renderGeneticTraitsCard = () => {
    if (!babyState) return null
    const pheno = Object.entries(babyState.phenotype || {})
    const hasDefects = babyState.defects?.length > 0
    const defectText = hasDefects
      ? babyState.defects.map(d => typeof d === 'object' ? tk((d.defect || '').replace(/_/g, ' ')) : tk(d.replace(/_/g, ' '))).join(', ')
      : t.no_defects
    const stability = Math.max(0, 100 - (babyState.defects?.length || 0) * 2.5).toFixed(1)
    return (
      <div className="relative bg-card ring-1 ring-border rounded-2xl p-5">
        {/* 右上角稳定性徽章 */}
        <div className="absolute top-4 right-4">
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-bold tracking-wider bg-primary/15 text-primary uppercase">
            {stability}% {lang === 'zh' ? '稳定性' : 'Stability'}
          </span>
        </div>
        {/* 3 列网格 */}
        <div className="grid grid-cols-3 gap-x-4 gap-y-5 pt-8">
          {pheno.map(([k, v]) => (
            <div key={k} className="min-w-0">
              <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider truncate">{tk(k.replace(/_/g, ' '))}</div>
              <div className="text-base font-semibold text-foreground capitalize truncate mt-1">{tk(v)}</div>
            </div>
          ))}
          <div className="min-w-0">
            <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">{t.defects}</div>
            <div className={cn(
              "text-base font-semibold capitalize mt-1 break-words",
              hasDefects ? "text-destructive" : "text-primary"
            )}>{defectText}</div>
          </div>
        </div>
        {/* 底部校验线：真实标记数 + baby ID */}
        <div className="mt-6 pt-4 border-t border-dashed border-border text-center text-[10px] font-semibold text-muted-foreground/60 tracking-[0.22em] uppercase font-mono">
          {pheno.length} {lang === 'zh' ? '个标记' : 'Markers'}
          {babyState.id && <> · {String(babyState.id).slice(0, 8)}</>}
          {' · '}{lang === 'zh' ? '已校验' : 'Verified'}
        </div>
      </div>
    )
  }

  const renderMonitorHeader = () => (
    babyState ? (
      <div className="flex items-center gap-2 px-2 capitalize flex-wrap">
        <h1 className="font-heading text-xl font-semibold">{tk(species)}</h1>
        <span className="text-muted-foreground">/</span>
        <span className="text-sm text-muted-foreground">{tk(babyState.sex)}</span>
        {/* 遗传特征标签：点击切换浮层 */}
        <button
          type="button"
          onClick={() => setShowGeneticPopover(v => !v)}
          className={cn(
            "ml-1 inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-semibold uppercase tracking-wider transition-colors normal-case",
            showGeneticPopover
              ? "bg-primary/15 text-primary ring-1 ring-primary/30"
              : "bg-muted text-muted-foreground hover:bg-muted/80"
          )}
          title={lang === 'zh' ? '遗传特征' : 'Genetic Traits'}
        >
          <Dna className="size-3" />
          <span className="uppercase tracking-wider">{lang === 'zh' ? '遗传特征' : 'Genetic Traits'}</span>
          <ChevronDown className={cn("size-3 transition-transform", showGeneticPopover && "rotate-180")} />
        </button>
        {babyState.id && <span className="ml-auto text-[10px] text-muted-foreground font-mono normal-case">{babyState.id}</span>}
      </div>
    ) : null
  )

  const renderMonitor = () => (
    <>

      {/* 母体环境 */}
      {environment && (() => {
        const fmt = (v) => {
          if (v === null || v === undefined) return '-'
          if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2)
          if (typeof v === 'boolean') return v ? (lang === 'zh' ? '是' : 'Yes') : (lang === 'zh' ? '否' : 'No')
          if (Array.isArray(v)) return v.length ? v.map(x => typeof x === 'object' ? JSON.stringify(x) : tk(String(x).replace(/_/g, ' '))).join(', ') : '-'
          if (typeof v === 'object') return null
          return tk(String(v).replace(/_/g, ' '))
        }

        // ── 汇总所有核心指标：横向滑动显示 ──
        const nutrientsDict = environment.nutrients || null
        const nutritionPct = nutrientsDict
          ? Math.round((Object.values(nutrientsDict).reduce((a, b) => a + (Number(b) || 0), 0) / Math.max(1, Object.keys(nutrientsDict).length)) * 100)
          : null
        const placentaEff = environment.placenta?.efficiency != null ? Math.round(environment.placenta.efficiency * 100) : null
        const stressMap = { low: 15, moderate: 45, high: 75, extreme: 95 }
        const stressPct = stressMap[environment.stress] ?? 50
        const toxinMap = { none: 5, low: 30, moderate: 60, high: 85 }
        const toxinPct = toxinMap[environment.toxin_exposure] ?? 50
        const ageMap = { very_young: 55, optimal: 100, moderate: 80, advanced: 55, very_advanced: 30 }
        const agePct = ageMap[environment.maternal_age_factor] ?? 70

        const GRADIENTS = {
          cyan: 'linear-gradient(90deg, #22d3ee, #06b6d4)',
          purple: 'linear-gradient(90deg, #7c3aed, #8b5cf6)',
          teal: 'linear-gradient(90deg, #0f766e, #14b8a6)',
          amber: 'linear-gradient(90deg, #f59e0b, #f97316)',
          rose: 'linear-gradient(90deg, #f43f5e, #ec4899)',
          emerald: 'linear-gradient(90deg, #10b981, #059669)',
          indigo: 'linear-gradient(90deg, #6366f1, #4f46e5)',
          sky: 'linear-gradient(90deg, #0ea5e9, #0284c7)',
          lime: 'linear-gradient(90deg, #84cc16, #65a30d)',
        }

        // 指标卡数据：label / value / pct(0-100) / color
        const metrics = [
          { label: t.nutrition, value: nutritionPct != null ? `${nutritionPct}%` : tk(environment.nutrition), pct: nutritionPct ?? 60, color: GRADIENTS.cyan },
          { label: t.placenta_label, value: placentaEff != null ? `${placentaEff}%` : '—', pct: placentaEff ?? 0, color: GRADIENTS.purple },
          { label: t.stress, value: tk(environment.stress), pct: 100 - stressPct, color: GRADIENTS.teal },
          { label: t.toxin, value: tk(environment.toxin_exposure), pct: 100 - toxinPct, color: GRADIENTS.rose, sub: environment.toxin_types?.length > 0 ? environment.toxin_types.map(x => tk(String(x).replace(/_/g, ' '))).join(', ') : null },
          { label: t.age, value: (AGE_LABELS[lang] || AGE_LABELS.en)[environment.maternal_age_factor] || tk(environment.maternal_age_factor), pct: agePct, color: GRADIENTS.amber },
        ]
        if (environment.modifiers) {
          metrics.push({
            label: t.budget,
            value: `${(environment.modifiers.budget_multiplier * 100).toFixed(0)}%`,
            pct: Math.min(100, environment.modifiers.budget_multiplier * 100),
            color: GRADIENTS.emerald,
          })
          const riskMul = environment.modifiers.defect_risk_multiplier
          metrics.push({
            label: t.risk,
            value: `${riskMul.toFixed(1)}x`,
            pct: Math.max(0, Math.min(100, (2 - riskMul) * 50)),
            color: GRADIENTS.indigo,
          })
        }
        // 免疫：由 rh 不兼容 + TORCH 感染数计算健康度
        if (environment.immunity) {
          const imm = environment.immunity
          const rhPenalty = imm.rh_incompatible ? 30 : 0
          const infCount = Array.isArray(imm.torch_infections) ? imm.torch_infections.length : 0
          const immPct = Math.max(0, 100 - rhPenalty - infCount * 15)
          metrics.push({
            label: t.immunity_label,
            value: `${immPct}%`,
            pct: immPct,
            color: GRADIENTS.rose,
          })
        }

        // 追加 5 种营养素
        if (nutrientsDict) {
          const nutrientColors = [GRADIENTS.sky, GRADIENTS.lime, GRADIENTS.amber, GRADIENTS.purple, GRADIENTS.emerald]
          Object.entries(nutrientsDict).forEach(([k, v], i) => {
            const pct = Math.round((Number(v) || 0) * 100)
            metrics.push({
              label: tk(k.replace(/_/g, ' ')),
              value: `${pct}%`,
              pct,
              color: nutrientColors[i % nutrientColors.length],
            })
          })
        }

        const renderBox = (title, items) => (
          <div className="bg-muted rounded-2xl p-4">
            {title && <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-3">{title}</div>}
            <div className="flex flex-col divide-y divide-border text-sm capitalize">
              {items.map(([label, val], i) => (
                <div key={i} className="flex justify-between py-2.5 first:pt-0 last:pb-0">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="font-medium">{val}</span>
                </div>
              ))}
            </div>
          </div>
        )

        return (
          <div className="px-1">
            <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-3">{t.env_conditions}</div>
            {/* 横向滑动的指标卡 */}
            <div className="-mx-1 overflow-x-auto scrollbar-thin">
              <div className="flex gap-3 px-1 pb-1 snap-x snap-mandatory">
                {metrics.map((m, i) => (
                  <div
                    key={i}
                    className="bg-muted rounded-2xl px-4 py-3.5 flex flex-col gap-2 w-[calc((100%-1.5rem)/3)] min-w-[140px] shrink-0 snap-start"
                  >
                    <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider truncate">{m.label}</div>
                    <div className="text-2xl font-heading font-semibold text-primary truncate capitalize">{m.value}</div>
                    {m.sub && <div className="text-[10px] text-muted-foreground truncate capitalize">{m.sub}</div>}
                    <div className="h-1.5 w-full rounded-full bg-foreground/10 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${Math.max(0, Math.min(100, m.pct ?? 0))}%`, background: m.color }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )
      })()}

      {/* 胎儿生命体征 */}
      {state.vitals && (() => {
        // 解析 "142 BPM" / "2.3 kg" / "120/80 mmHg" 形式的值为主数值 + 单位
        const splitValue = (raw) => {
          if (raw == null || raw === '') return { main: '—', unit: '' }
          const s = String(raw).trim()
          const m = s.match(/^([\d./-]+)\s*(.*)$/)
          if (m) return { main: m[1], unit: m[2] }
          return { main: s, unit: '' }
        }
        const v = state.vitals

        // 随机但稳定的 sparkline 条形：基于标签做伪随机，保证同 key 高度一致
        const sparkBars = (seed) => {
          const heights = []
          let h = 0
          for (let i = 0; i < 7; i++) {
            h = (seed.charCodeAt(i % seed.length) * (i + 3)) % 100
            heights.push(30 + (h % 60))
          }
          return heights
        }

        const cards = [
          { key: 'weight', label: lang === 'zh' ? '体重' : 'Weight', raw: v.weight, Icon: Scale, color: 'text-cyan-500', barColor: 'bg-cyan-500' },
          { key: 'length', label: lang === 'zh' ? '身长' : 'Length', raw: v.length, Icon: Ruler, color: 'text-emerald-500', barColor: 'bg-emerald-500' },
          { key: 'blood_pressure', label: lang === 'zh' ? '血压' : 'Blood Pressure', raw: v.blood_pressure, Icon: Heart, color: 'text-rose-500', barColor: 'bg-rose-500' },
          { key: 'oxygen', label: lang === 'zh' ? '血氧' : 'Oxygen', raw: v.oxygen, Icon: Wind, color: 'text-sky-500', barColor: 'bg-sky-500' },
          { key: 'movement', label: lang === 'zh' ? '胎动' : 'Movement', raw: v.movement, Icon: Activity, color: 'text-violet-500', barColor: 'bg-violet-500' },
          { key: 'amniotic_fluid', label: lang === 'zh' ? '羊水' : 'Amniotic Fluid', raw: v.amniotic_fluid, Icon: Droplet, color: 'text-indigo-500', barColor: 'bg-indigo-500' },
        ].filter(c => c.raw != null && c.raw !== '')

        return (
          <div className="px-1">
            <div className="flex items-center gap-2 mb-3">
              <Activity className="size-4 text-primary" />
              <div className="text-[13px] font-semibold text-foreground">
                {lang === 'zh' ? '生命体征' : 'Vital Signs'}
              </div>
              {v.status && (
                <span className="text-[10px] text-muted-foreground font-mono normal-case ml-1">{v.status}</span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              {cards.map(({ key, label, raw, Icon, color, barColor }) => {
                const { main, unit } = splitValue(raw)
                const bars = sparkBars(key)
                return (
                  <div
                    key={key}
                    className="relative bg-card ring-1 ring-border rounded-2xl p-5 overflow-hidden min-w-0 h-[140px]"
                  >
                    {/* 右侧大号水印图标 */}
                    <Icon
                      className={cn("absolute -right-4 top-1/2 -translate-y-1/2 size-28 opacity-[0.12] pointer-events-none", color)}
                      strokeWidth={1.5}
                      fill="currentColor"
                    />
                    {/* 内容层 */}
                    <div className="relative flex flex-col justify-between h-full min-w-0">
                      <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.12em]">
                        {label}
                      </div>
                      <div className="flex items-baseline gap-1.5 min-w-0">
                        <span className="text-[2.25rem] leading-none font-heading font-bold text-primary truncate">{main}</span>
                        {unit && (
                          <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide truncate">{unit}</span>
                        )}
                      </div>
                      {/* 底部装饰条形图 */}
                      <div className="flex items-end gap-0.5 h-5">
                        {bars.map((h, i) => (
                          <div
                            key={i}
                            className={cn("w-1 rounded-sm opacity-80", barColor)}
                            style={{ height: `${h}%` }}
                          />
                        ))}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
            {v.alerts?.length > 0 && (
              <div className="mt-3 bg-destructive/10 rounded-2xl p-4 text-sm text-destructive">
                {v.alerts.map((a, i) => <div key={i}>{a}</div>)}
              </div>
            )}
          </div>
        )
      })()}

      {/* 先天倾向 */}
      {babyState?.tendencies?.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t.tendencies_label}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-4">
              {babyState.tendencies.map((tend, i) => (
                <div key={i} className="flex items-start gap-3">
                  <span className="mt-1.5 w-5 h-5 rounded-full bg-primary/15 flex items-center justify-center shrink-0">
                    <span className="w-2 h-2 rounded-full bg-primary" />
                  </span>
                  <span className="text-sm text-foreground leading-relaxed">{typeof tend === 'object' ? (tend.description || tend.name || JSON.stringify(tend)) : tend}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* 初声 */}
      {babyState?.first_cry && (
        <Card>
          <CardHeader>
            <CardTitle>{t.first_cry_label}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="bg-muted rounded-2xl p-4 text-sm text-foreground leading-relaxed italic">{babyState.first_cry}</div>
          </CardContent>
        </Card>
      )}

    </>
  )

  // ── 格式化阶段数据值 ──
  const formatStageValue = (v) => {
    if (v === null || v === undefined) return '—'
    if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2)
    if (typeof v === 'boolean') return v ? (lang === 'zh' ? '是' : 'Yes') : (lang === 'zh' ? '否' : 'No')
    if (typeof v === 'string') return v
    if (Array.isArray(v)) return v.map(item => typeof item === 'object' ? JSON.stringify(item) : String(item)).join(', ') || '—'
    if (typeof v === 'object') return Object.entries(v).map(([k2, v2]) => `${tk(k2.replace(/_/g, ' '))}: ${typeof v2 === 'number' ? (Number.isInteger(v2) ? v2 : v2.toFixed(2)) : v2}`).join(', ')
    return String(v)
  }

  const formatElapsed = (ms) => {
    const s = Math.floor(ms / 1000)
    return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s`
  }

  const getStageElapsed = (stageName) => {
    const timing = stageTimings[stageName]
    if (!timing?.startedAt) return null
    const now = Date.now()
    const endAt = timing.maternalDoneAt || timing.doneAt || now
    return formatElapsed(endAt - timing.startedAt)
  }

  // ── 阶段卡片视图 (右面板) ──
  const renderStageCards = () => {
    const visibleStages = blueprint.stages.filter(stg => stageProgress[stg.name])
    return (
      <div ref={stageCardsRef} className="flex flex-col gap-4 overflow-y-auto h-full px-1 py-1">
        {visibleStages.map((stg, i) => {
          const status = stageProgress[stg.name] || ''
          const mStatus = maternalProgress[stg.name] || ''
          const stageData = babyState?.stages?.[stg.name]
          const isActive = status === 'active'
          const isBirthStage = i === blueprint.stages.length - 1
          const isDone = status === 'done'
          const isFailed = status === 'failed'
          const isMaternal = mStatus === 'active'
          const entries = stageData ? Object.entries(stageData).filter(([k]) => !k.startsWith('_') && k !== 'budget_enforced' && k !== 'budget_remaining') : []
          const explicitTag = expandedTag?.startsWith(stg.name + ':') ? expandedTag.split(':')[1] : null
          const defaultTag = isBirthStage && entries.some(([k]) => k === 'first_cry') ? 'first_cry' : (entries.length > 0 ? entries[0][0] : null)
          const tagKey = explicitTag ?? defaultTag
          return (
            <div key={stg.name} className={cn(
              "rounded-lg ring-1 ring-foreground/10 bg-card transition-all duration-300 animate-in fade-in slide-in-from-bottom-2 h-[350px] shrink-0 flex flex-col overflow-hidden",
              isActive && !isMaternal && "stage-card-running",
              isMaternal && "stage-card-maternal",
            )}>
              {/* 标题行 — 固定 */}
              <div className="shrink-0 flex items-center justify-between px-5 pt-5 pb-2">
                <div className="flex items-center gap-2.5">
                  <span className="text-2xl font-heading font-bold text-primary/70">{String(i + 1).padStart(2, '0')}</span>
                  <span className="text-base font-heading font-semibold capitalize">{tk(stg.name.replace(/_/g, ' '))}</span>
                  {(isActive || isDone || isMaternal) && getStageElapsed(stg.name) && (
                    <span className="text-[11px] font-mono text-muted-foreground tabular-nums">{getStageElapsed(stg.name)}</span>
                  )}
                </div>
                {isMaternal ? (
                  <span className="text-[10px] font-mono font-semibold tracking-wider bg-[color:var(--color-maternal)] text-white px-2.5 py-1 rounded animate-pulse">{lang === 'zh' ? '母体反应中' : 'MATERNAL'}</span>
                ) : isDone ? (
                  <span className={cn("text-[10px] font-mono font-semibold tracking-wider px-2.5 py-1 rounded", isBirthStage ? "bg-emerald-500 text-white" : "bg-primary text-primary-foreground")}>{lang === 'zh' ? '完成' : 'COMPLETE'}</span>
                ) : isActive ? (
                  <span className="text-[10px] font-mono font-semibold tracking-wider bg-emerald-500 text-white px-2.5 py-1 rounded animate-pulse">{lang === 'zh' ? '进行中' : 'RUNNING'}</span>
                ) : isFailed ? (
                  <span className="text-[10px] font-mono font-semibold tracking-wider bg-destructive text-white px-2.5 py-1 rounded">{lang === 'zh' ? '失败' : 'FAILED'}</span>
                ) : null}
              </div>
              {/* 描述 — 固定 */}
              <div className="shrink-0 text-xs text-muted-foreground px-5 pb-3">
                {stg.duration}{t.days} · {lang === 'zh' ? '预算' : 'Budget'} {stg.budget}
              </div>
              {/* 标签 + 展开区域 — 可滚动 */}
              {(isDone || isActive) && entries.length > 0 && (
                <div className="border-t border-border px-5 py-4 flex-1 overflow-y-auto min-h-0">
                  <div className="flex flex-wrap gap-1.5 mb-1">
                    {entries.map(([k]) => (
                      <button
                        key={k}
                        onClick={() => setExpandedTag(expandedTag === `${stg.name}:${k}` ? null : `${stg.name}:${k}`)}
                        className={cn(
                          "px-2 py-0.5 rounded text-[10px] font-mono font-medium tracking-wide transition-colors cursor-pointer capitalize",
                          tagKey === k
                            ? (isBirthStage ? "bg-emerald-500 text-white" : "bg-primary text-primary-foreground")
                            : "bg-muted text-muted-foreground hover:bg-muted-foreground/10"
                        )}
                      >
                        {tk(k.replace(/_/g, ' '))}
                      </button>
                    ))}
                  </div>
                  {tagKey && (() => {
                    const val = stageData[tagKey]
                    return (
                      <div className="mt-3 rounded-lg border border-border bg-muted/30 overflow-hidden animate-in fade-in slide-in-from-top-1 duration-200">
                        {!isBirthStage && (
                          <div className="flex items-center justify-between px-4 py-2 border-b border-border">
                            <div className="flex items-center gap-2">
                              <span className="px-1.5 py-0.5 rounded bg-primary text-primary-foreground text-[9px] font-mono font-semibold uppercase">{typeof val === 'object' ? (Array.isArray(val) ? 'array' : 'object') : typeof val}</span>
                              <span className="font-heading font-semibold text-sm capitalize">{tk(tagKey.replace(/_/g, ' '))}</span>
                            </div>
                          </div>
                        )}
                        <div className={cn(
                          "px-4 py-3 text-xs leading-relaxed whitespace-pre-wrap break-words",
                          isBirthStage && "italic text-emerald-400"
                        )}>
                          {typeof val === 'object' ? (
                            Array.isArray(val) ? (
                              <div className="flex flex-col gap-2">
                                {val.map((item, j) => (
                                  item && typeof item === 'object' ? (
                                    <div key={j} className="rounded-md border border-border/60 bg-background/40 px-3 py-2 flex flex-col gap-1">
                                      {Object.entries(item).map(([ik, iv]) => (
                                        <div key={ik} className="flex gap-2 text-xs">
                                          <span className="font-mono font-semibold shrink-0 capitalize text-foreground/80">{tk(ik.replace(/_/g, ' '))}</span>
                                          <span className="text-muted-foreground break-words min-w-0">{
                                            iv == null ? '—'
                                            : typeof iv === 'object' ? JSON.stringify(iv)
                                            : typeof iv === 'number' ? (Number.isInteger(iv) ? iv : iv.toFixed(2))
                                            : String(iv)
                                          }</span>
                                        </div>
                                      ))}
                                    </div>
                                  ) : (
                                    <div key={j} className="flex gap-2">
                                      <span className="text-muted-foreground shrink-0">•</span>
                                      <span>{String(item)}</span>
                                    </div>
                                  )
                                ))}
                              </div>
                            ) : (
                              <div className="flex flex-col gap-1.5">
                                {Object.entries(val).map(([k2, v2]) => (
                                  <div key={k2} className="flex gap-3 py-1 border-b border-dashed border-border last:border-0">
                                    <span className="font-mono font-semibold shrink-0 capitalize">{tk(k2.replace(/_/g, ' '))}</span>
                                    <span className="text-muted-foreground">{typeof v2 === 'number' ? (Number.isInteger(v2) ? v2 : v2.toFixed(2)) : String(v2)}</span>
                                  </div>
                                ))}
                              </div>
                            )
                          ) : (
                            <span>{formatStageValue(val)}</span>
                          )}
                        </div>
                      </div>
                    )
                  })()}
                </div>
              )}
              {/* 进行中占位：仅在尚无数据时显示 */}
              {isActive && !isDone && entries.length === 0 && (
                <div className="border-t border-border bg-muted/30 px-5 py-4 flex-1 flex items-center justify-center">
                  <span className="text-xs text-muted-foreground">{lang === 'zh' ? '发育数据生成中...' : 'Generating development data...'}</span>
                </div>
              )}
            </div>
          )
        })}
        {visibleStages.length === 0 && (
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
            {lang === 'zh' ? '等待发育开始...' : 'Waiting for development...'}
          </div>
        )}
        {/* 操作按钮 */}
        {!running && babyState && (
          <div className="flex gap-3 shrink-0 py-2">
            {babyState.alive && babyState.id && (
              <Button
                size="lg"
                className="flex-1"
                disabled={admittingToCradle}
                onClick={() => {
                  const babyId = babyState.id
                  if (admittingToCradle) return
                  setAdmittingToCradle(true)
                  // 直接在当前页完成 admit：不跳转，等 SSE 'admitted' 后再 navigate。
                  // lastSeq 持久化是为了避免 Cradle 挂载后 lifeline?after_seq=0 重放 admit 事件。
                  const source = new EventSource(`${API}/cradle/admit/stream?baby_id=${encodeURIComponent(babyId)}`)
                  const finish = (ok) => {
                    source.close()
                    setAdmittingToCradle(false)
                    if (ok) {
                      dispatch({ type: 'CLEAR_PROGRESS' })
                      // justAdmitted=1 通知 Cradle 刷新 cradleBabies / babyStatus，
                      // 避免本地 state 陈旧导致详情页仍显示"未入篮"。
                      navigate(`/cradle/${babyId}?justAdmitted=1`)
                    }
                  }
                  source.onmessage = (e) => {
                    try {
                      const data = JSON.parse(e.data)
                      if (data.seq) {
                        localStorage.setItem(`lastSeq_${babyId}`, String(data.seq))
                      }
                      if (data.event === 'admitted') finish(true)
                      else if (data.event === 'error') finish(false)
                    } catch { /* ignore */ }
                  }
                  source.onerror = () => finish(false)
                }}
              >
                {admittingToCradle ? (
                  <>
                    <Loader2 className="size-4 animate-spin mr-2" />
                    {lang === 'zh' ? '放入中...' : 'Admitting...'}
                  </>
                ) : (
                  <>{lang === 'zh' ? '放入摇篮' : 'To Cradle'} →</>
                )}
              </Button>
            )}
            <Button size="lg" variant="outline" onClick={() => dispatch({ type: 'CLEAR_PROGRESS' })}>
              {t.conceive_again}
            </Button>
          </div>
        )}
      </div>
    )
  }

  // ── 控制台组件 ──
  const renderConsole = () => {
    const doneCount = Object.values(stageProgress).filter(s => s === 'done').length + (Object.values(stageProgress).some(s => s === 'active') ? 1 : 0)
    const failedCount = Object.values(stageProgress).filter(s => s === 'failed').length
    const currentStageName = state.currentStage ? tk(state.currentStage) : ''
    const allDone = doneCount === 7
    const hasFailed = failedCount > 0
    const hasStarted = doneCount > 0 || running
    const isMaternalNow = state.currentStage && maternalProgress[state.currentStage] === 'active'
    return (
      <ConsolePanel
        ref={consoleRef}
        className="h-full"
        headerRight={
          <button
            type="button"
            onClick={() => setConsoleFullscreen(v => !v)}
            className="flex items-center justify-center w-6 h-6 rounded text-[#999] hover:text-white hover:bg-white/10 transition-colors"
            title={consoleFullscreen
              ? (lang === 'zh' ? '缩小' : 'Minimize')
              : (lang === 'zh' ? '全屏' : 'Fullscreen')}
          >
            {consoleFullscreen ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
          </button>
        }
        header={
          <div className="flex items-center gap-2.5 text-[11px]">
            <span className="text-[#666]">Step {doneCount}/7</span>
            <span className="w-px h-3 bg-[#444]" />
            <span className={cn("font-medium", isMaternalNow ? "text-[color:var(--color-maternal)]" : running ? "text-emerald-400" : "text-primary")}>{currentStageName || t.console}</span>
            <span className="w-px h-3 bg-[#444]" />
            <div className="flex items-center gap-[5px]">
              <span className={cn(
                "w-1.5 h-1.5 rounded-full",
                hasFailed ? "bg-[#FF5F57]" :
                allDone ? "bg-[#28C840]" :
                isMaternalNow ? "step-dot-maternal" :
                running ? "step-dot-running" :
                "bg-[#555]"
              )} />
              <span className="text-[#666] text-[11px]">
                {!hasStarted ? t.step_ready : hasFailed ? t.step_failed : allDone ? t.step_done : running ? t.step_running : t.step_idle}
              </span>
            </div>
            {allDone && state.elapsed && <>
              <span className="w-px h-3 bg-[#444]" />
              <span className="text-[#555]">{state.elapsed}s</span>
            </>}
          </div>
        }
      >
        {logs.length === 0 && <div className="log-system"><span className="blink-dot" />{t.ready}</div>}
        {logs.map(renderLog)}
      </ConsolePanel>
    )
  }

  // ── 孕育前单页布局 ──
  const renderPreConceive = () => (
    <div className="flex-1 overflow-y-auto" data-scroll-root="true">
      <div className="max-w-5xl mx-auto px-8 min-h-full flex items-center gap-8">
        {/* 左列 — 固定内容，立即显示 */}
        <div className="w-1/2">
          {renderBlueprint()}
        </div>
        {/* 右列 — 等数据就绪后淡入 */}
        <div className={cn("w-1/2 pt-16 transition-opacity duration-300", blueprintReady ? "opacity-100" : "opacity-0")}>
          {renderParams()}
        </div>
      </div>
    </div>
  )

  // ── 孕育中分屏布局 ──
  const renderConceiving = () => (
    <div className="flex flex-1 overflow-hidden">
      {/* 左面板：力导向因果图谱
          graph→w-full；workbench→w-0（折叠但保留过渡动画）；split→w-1/2 */}
      <div className={cn(
        "left-panel bg-background flex flex-col shrink-0 overflow-hidden transition-all duration-300",
        graphFullscreen
          ? "w-full border-r-0"
          : workbenchFullscreen
          ? "w-0 border-r-0"
          : "w-1/2 border-r border-border"
      )}>
        <LifeGraph
          nodes={wombGraph.nodes.length ? wombGraph.nodes : graphState.nodes}
          edges={wombGraph.edges.length ? wombGraph.edges : graphState.edges}
          filter={graphState.filter}
          showLabels={graphState.showLabels}
          highlight={graphState.highlight}
          stage="womb"
          dispatch={graphDispatch}
          fullscreen={graphFullscreen}
        />
      </div>
      {/* 右面板：阶段卡片 + 控制台
          graph→w-0（折叠）；workbench→w-full；split→w-1/2（和左面板对称）*/}
      <div className={cn(
        "flex flex-col overflow-hidden relative shrink-0 transition-all duration-300",
        graphFullscreen
          ? "w-0"
          : workbenchFullscreen
          ? "w-full"
          : "w-1/2"
      )}>
        {/* 阶段卡片 */}
        <div className={cn(
          "flex flex-col p-5 overflow-hidden",
          consoleFullscreen ? "hidden" : "flex-1"
        )}>
          {renderStageCards()}
        </div>
        {/* 控制台：非全屏时占据右侧底部，全屏时覆盖整个右侧 */}
        <div className={cn(
          "overflow-hidden",
          consoleFullscreen
            ? "flex-1 pt-2 pr-2"
            : "border-t border-border pt-2 pr-2 shrink-0"
        )}
        style={consoleFullscreen ? undefined : { height: '30%', minHeight: '160px' }}
        >
          <div className="h-full flex flex-col">
            {renderConsole()}
          </div>
        </div>
      </div>
    </div>
  )

  // 批量 SSE 控制台：复用 ConsolePanel 组件 + 统一日志渲染
  const renderBatchConsole = () => {
    const logCount = batchLogs.length
    const babyCount = batchLogs.filter(l => l.kind === 'baby').length
    const errorCount = batchLogs.filter(l => l.kind === 'error').length
    return (
      <ConsolePanel
        ref={batchConsoleRef}
        className="h-full"
        header={
          <div className="flex items-center gap-2.5 text-[11px]">
            <span className="text-[#666]">Events {logCount}</span>
            <span className="w-px h-3 bg-[#444]" />
            <span className={cn(
              "font-medium",
              errorCount > 0 ? "text-[#FF5F57]" :
              batchRunning ? "text-emerald-400" :
              "text-primary",
            )}>
              {lang === 'zh' ? 'SSE 事件流' : 'SSE Stream'}
            </span>
            <span className="w-px h-3 bg-[#444]" />
            <div className="flex items-center gap-[5px]">
              <span className={cn(
                "w-1.5 h-1.5 rounded-full",
                errorCount > 0 ? "bg-[#FF5F57]" :
                !batchRunning && batchResult ? "bg-[#28C840]" :
                batchRunning ? "step-dot-running" :
                "bg-[#555]",
              )} />
              <span className="text-[#666] text-[11px]">
                {!batchRunning && batchResult
                  ? t.batch_done
                  : batchRunning
                    ? t.batch_running
                    : t.step_idle}
              </span>
            </div>
            {babyCount > 0 && <>
              <span className="w-px h-3 bg-[#444]" />
              <span className="text-[#555]">{babyCount} births</span>
            </>}
          </div>
        }
      >
        {logCount === 0 && (
          <div className="log-system"><span className="blink-dot" />{lang === 'zh' ? '等待批量孕育事件...' : 'Waiting for batch events...'}</div>
        )}
        {batchLogs.map((entry, i) => {
          const clsMap = {
            system: 'log-system',
            progress: 'log-system text-[#888]',
            baby: 'text-emerald-400',
            miscarriage: 'text-[#FFBD2E]',
            error: 'text-[#FF5F57]',
            complete: 'text-primary',
          }
          const cls = clsMap[entry.kind] || 'text-[#aaa]'
          const time = new Date(entry.ts).toTimeString().slice(0, 8)
          return (
            <div key={i} className={cn('text-[11px] font-mono leading-relaxed', cls)}>
              <span className="text-[#555] mr-2">{time}</span>
              {entry.text}
            </div>
          )
        })}
      </ConsolePanel>
    )
  }

  // 批量孕育页面：左 = 实时出生列表，右 = 进度卡片 + 控制台
  const renderBatchConceiving = () => {
    const pct = batchProgress && batchProgress.total > 0 ? (batchProgress.done / batchProgress.total) * 100 : 0
    const throughput = batchProgress && batchProgress.elapsed_sec > 0
      ? (batchProgress.conceived / batchProgress.elapsed_sec).toFixed(1) : '0'
    return (
      <div className="flex flex-1 overflow-hidden">
        {/* 左分屏：最新出生滚动列表 */}
        <div className="w-1/2 min-w-0 flex flex-col overflow-hidden bg-background border-r border-border">
          <div className="px-6 pt-6 pb-3 flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[11px] text-muted-foreground tracking-wider mb-1">
                {lang === 'zh' ? '最新出生' : 'Latest Arrivals'}
              </div>
              <div className="text-sm text-muted-foreground/70">
                {batchRecentBabies.length}{lang === 'zh' ? ' 位婴儿已出生' : ' babies born'}
              </div>
            </div>
            {/* 右上角指标：成功/流产/失败 + 用时/吞吐（进行中显示实时值，完成后显示终值） */}
            {batchProgress && (
              <div className="flex items-start gap-5 shrink-0 pt-0.5">
                <div className="text-right">
                  <div className="text-[10px] text-muted-foreground tracking-wider mb-0.5">{t.batch_conceived}</div>
                  <div className="font-heading text-base font-semibold tabular-nums text-emerald-600">{batchProgress.conceived}</div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-muted-foreground tracking-wider mb-0.5">{t.batch_miscarriages}</div>
                  <div className="font-heading text-base font-semibold tabular-nums">{batchProgress.miscarriages}</div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-muted-foreground tracking-wider mb-0.5">{t.batch_failed}</div>
                  <div className="font-heading text-base font-semibold tabular-nums">{batchProgress.failed}</div>
                </div>
                <div className="w-px h-10 bg-border self-center" />
                <div className="text-right">
                  <div className="text-[10px] text-muted-foreground tracking-wider mb-0.5">{t.batch_elapsed}</div>
                  <div className="font-heading text-base font-semibold tabular-nums">
                    {(batchResult?.elapsed_sec ?? batchProgress.elapsed_sec)}{t.batch_sec}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-muted-foreground tracking-wider mb-0.5">{t.batch_throughput}</div>
                  <div className="font-heading text-base font-semibold tabular-nums">
                    {batchResult?.throughput_per_sec ?? throughput}<span className="text-xs text-muted-foreground ml-0.5">{t.batch_per_sec}</span>
                  </div>
                </div>
              </div>
            )}
          </div>
          {/* 进度条：左分屏 header 与列表之间 */}
          {batchProgress && (
            <div className="px-6 pb-3 shrink-0 flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "inline-block w-2 h-2 rounded-full",
                    batchRunning ? "step-dot-running animate-pulse" : "bg-[#28C840]",
                  )} />
                  <span className="text-xs font-medium">
                    {batchRunning ? t.batch_running : t.batch_done}
                  </span>
                </div>
                <span className="text-xs font-heading tabular-nums text-muted-foreground">
                  {batchProgress.done}/{batchProgress.total}
                </span>
              </div>
              <div className="h-2 bg-muted/60 rounded overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-300"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          )}
          <ScrollArea
            id="batch-baby-scroll"
            className={cn(
              "flex-1 min-h-0 w-full",
              // Radix viewport 内部自动包一层 <div>（非 block 默认），强制 w-full + block 约束其宽度
              "[&_[data-slot=scroll-area-viewport]>div]:!block [&_[data-slot=scroll-area-viewport]>div]:!w-full",
            )}
          >
            <div className="px-6 pt-2 pb-6 w-full min-w-0">
              {batchRecentBabies.length === 0 && (
                <div className="text-sm text-muted-foreground/60 italic mt-6">
                  {lang === 'zh' ? '等待第一个婴儿出生...' : 'Waiting for first arrival...'}
                </div>
              )}
              <div className="flex flex-col gap-2 w-full min-w-0">
                {batchRecentBabies.map((b) => (
                  <BatchBabyListItem
                    key={b.id}
                    baby={b}
                    selected={batchSelectedBaby?.id === b.id}
                    lang={lang}
                    title={lang === 'zh' ? '点击查看详情' : 'Click to view details'}
                    onClick={handleBatchItemClick(b)}
                  />
                ))}
              </div>
            </div>
          </ScrollArea>
        </div>

        {/* 右分屏：上半=详情卡片，下半=控制台 */}
        <div className="w-1/2 min-w-0 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto px-8 pt-6 pb-8 gap-6 flex flex-col min-h-0">
          {/* 批量失败错误提示（只在连接中断等明确失败时显示一行） */}
          {batchResult?.error && !batchRunning && (
            <div className="text-xs text-destructive">{batchResult.error}</div>
          )}
          {/* 婴儿详情：采用单个孕育"阶段卡"样式，展示 7 阶段 gestation_log */}
          {batchSelectedBaby && (
            <div className="flex flex-col gap-4">
              {/* 概要行：头像 + 性别 + 出生地 + 进入养育按钮 */}
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center shrink-0 text-2xl">
                  {batchSelectedBaby.sex === 'male' ? '\u{1F466}' : '\u{1F467}'}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-heading text-base font-semibold">
                      {batchSelectedBaby.sex === 'male' ? (lang === 'zh' ? '男性' : 'Male') : (lang === 'zh' ? '女性' : 'Female')}
                    </span>
                    <span className={cn(
                      "text-[10px] px-2 py-0.5 rounded-full font-medium tracking-wider",
                      batchSelectedBaby.alive
                        ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                        : "bg-muted text-muted-foreground border border-border",
                    )}>
                      {batchSelectedBaby.alive ? (lang === 'zh' ? '存活' : 'ALIVE') : (lang === 'zh' ? '未存活' : 'LOST')}
                    </span>
                    {batchSelectedBaby.birthplace?.city && (
                      <span className="text-xs text-muted-foreground truncate">
                        · {batchSelectedBaby.birthplace.city}, {batchSelectedBaby.birthplace.name}
                      </span>
                    )}
                  </div>
                  <div className="font-mono text-[11px] text-muted-foreground/80 tabular-nums truncate mt-0.5">
                    {batchSelectedBaby.id}
                  </div>
                </div>
                <button
                  disabled={batchAdmitLoading}
                  className={cn(
                    "px-3 py-2 text-xs font-heading font-semibold text-primary bg-rose-50 border border-border transition-colors whitespace-nowrap flex items-center gap-1.5",
                    batchAdmitLoading ? "opacity-60 cursor-not-allowed" : "hover:bg-rose-100",
                  )}
                  onClick={() => handleBatchAdmit(batchSelectedBaby.id)}
                >
                  {batchAdmitLoading
                    ? (lang === 'zh' ? '接收中...' : 'Admitting...')
                    : (lang === 'zh' ? '进入养育' : 'Raise in Cradle')}
                  {batchAdmitLoading
                    ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    : <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M17 8l4 4m0 0l-4 4m4-4H3" /></svg>}
                </button>
              </div>

              {/* 7 个阶段卡：复用单个孕育样式，数据来自 gestation_log */}
              {batchSelectedLoading && (
                <div className="rounded-lg ring-1 ring-foreground/10 bg-card p-5 text-xs text-muted-foreground">
                  {lang === 'zh' ? '加载孕育数据...' : 'Loading gestation data...'}
                </div>
              )}
              {!batchSelectedLoading && batchSelectedFull?.gestation_log?.slice().reverse().map((entry, reversedIdx) => {
                const total = batchSelectedFull.gestation_log.length
                const i = total - 1 - reversedIdx  // 真实索引（从 0 开始）
                const stageName = entry.stage
                const isBirthStage = i === total - 1
                const response = entry.response
                const entries = response && typeof response === 'object'
                  ? Object.entries(response).filter(([k]) => !k.startsWith('_') && k !== 'budget_enforced' && k !== 'budget_remaining' && k !== 'gestation_log' && k !== 'total_gestation_days')
                  : []
                const tagId = `${stageName}:${i}`
                const explicitTag = batchExpandedTag?.startsWith(tagId + '|') ? batchExpandedTag.slice(tagId.length + 1) : null
                const defaultTag = isBirthStage && entries.some(([k]) => k === 'first_cry') ? 'first_cry' : (entries.length > 0 ? entries[0][0] : null)
                const tagKey = explicitTag ?? defaultTag
                const val = tagKey && response ? response[tagKey] : null
                return (
                  <div key={`${stageName}-${i}`} className="rounded-lg ring-1 ring-foreground/10 bg-card overflow-hidden flex flex-col">
                    {/* 标题行 */}
                    <div className="shrink-0 flex items-center justify-between px-5 pt-4 pb-2">
                      <div className="flex items-center gap-2.5">
                        <span className="text-2xl font-heading font-bold text-primary/70">{String(i + 1).padStart(2, '0')}</span>
                        <span className="text-base font-heading font-semibold capitalize">{tk(stageName.replace(/_/g, ' '))}</span>
                      </div>
                      <span className={cn("text-[10px] font-mono font-semibold tracking-wider px-2.5 py-1 rounded", isBirthStage ? "bg-emerald-500 text-white" : "bg-primary text-primary-foreground")}>
                        {lang === 'zh' ? '完成' : 'COMPLETE'}
                      </span>
                    </div>
                    {/* 描述 */}
                    <div className="shrink-0 text-xs text-muted-foreground px-5 pb-3">
                      {entry.duration_days}{t.days} · {lang === 'zh' ? '孕育日' : 'Gestation Day'} {entry.gestation_day}
                    </div>
                    {/* 标签 + 展开区域 */}
                    {entries.length > 0 && (
                      <div className="border-t border-border px-5 py-4">
                        <div className="flex flex-wrap gap-1.5 mb-1">
                          {entries.map(([k]) => (
                            <button
                              key={k}
                              onClick={() => setBatchExpandedTag(batchExpandedTag === `${tagId}|${k}` ? null : `${tagId}|${k}`)}
                              className={cn(
                                "px-2 py-0.5 rounded text-[10px] font-mono font-medium tracking-wide transition-colors cursor-pointer capitalize",
                                tagKey === k
                                  ? (isBirthStage ? "bg-emerald-500 text-white" : "bg-primary text-primary-foreground")
                                  : "bg-muted text-muted-foreground hover:bg-muted-foreground/10",
                              )}
                            >
                              {tk(k.replace(/_/g, ' '))}
                            </button>
                          ))}
                        </div>
                        {tagKey && (
                          <div className="mt-3 rounded-lg border border-border bg-muted/30 overflow-hidden animate-in fade-in slide-in-from-top-1 duration-200">
                            {!isBirthStage && (
                              <div className="flex items-center justify-between px-4 py-2 border-b border-border">
                                <div className="flex items-center gap-2">
                                  <span className="px-1.5 py-0.5 rounded bg-primary text-primary-foreground text-[9px] font-mono font-semibold uppercase">
                                    {typeof val === 'object' ? (Array.isArray(val) ? 'array' : 'object') : typeof val}
                                  </span>
                                  <span className="font-heading font-semibold text-sm capitalize">{tk(tagKey.replace(/_/g, ' '))}</span>
                                </div>
                              </div>
                            )}
                            <div className={cn("px-4 py-3 text-xs leading-relaxed whitespace-pre-wrap break-words", isBirthStage && "italic text-emerald-600")}>
                              {typeof val === 'object' && val !== null ? (
                                Array.isArray(val) ? (
                                  <div className="flex flex-col gap-2">
                                    {val.map((item, j) => (
                                      item && typeof item === 'object' ? (
                                        <div key={j} className="rounded-md border border-border/60 bg-background/40 px-3 py-2 flex flex-col gap-1">
                                          {Object.entries(item).map(([ik, iv]) => (
                                            <div key={ik} className="flex gap-2 text-xs">
                                              <span className="font-mono font-semibold shrink-0 capitalize text-foreground/80">{tk(ik.replace(/_/g, ' '))}</span>
                                              <span className="text-muted-foreground break-words min-w-0">{
                                                iv == null ? '—'
                                                : typeof iv === 'object' ? JSON.stringify(iv)
                                                : typeof iv === 'number' ? (Number.isInteger(iv) ? iv : iv.toFixed(2))
                                                : String(iv)
                                              }</span>
                                            </div>
                                          ))}
                                        </div>
                                      ) : (
                                        <div key={j} className="flex gap-2">
                                          <span className="text-muted-foreground shrink-0">•</span>
                                          <span>{String(item)}</span>
                                        </div>
                                      )
                                    ))}
                                  </div>
                                ) : (
                                  <div className="flex flex-col gap-1.5">
                                    {Object.entries(val).map(([k2, v2]) => (
                                      <div key={k2} className="flex gap-3 py-1 border-b border-dashed border-border last:border-0">
                                        <span className="font-mono font-semibold shrink-0 capitalize">{tk(k2.replace(/_/g, ' '))}</span>
                                        <span className="text-muted-foreground">{typeof v2 === 'number' ? (Number.isInteger(v2) ? v2 : v2.toFixed(2)) : String(v2)}</span>
                                      </div>
                                    ))}
                                  </div>
                                )
                              ) : (
                                <span>{val == null ? '—' : String(val)}</span>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
          </div>
          {/* 下半：SSE 控制台 —— 高度规则对齐单个孕育控制台（30% / minHeight 160px） */}
          <div
            className="overflow-hidden border-t border-border pt-2 pr-2 shrink-0"
            style={{ height: '30%', minHeight: '160px' }}
          >
            <div className="h-full flex flex-col">
              {renderBatchConsole()}
            </div>
          </div>
        </div>
      </div>
    )
  }

  const renderWomb = () => isConceiving ? renderConceiving() : renderPreConceive()

  const renderPlaceholder = (name) => (
    <div className="flex flex-1 overflow-hidden">
      <div className="flex-1 flex items-center justify-center text-foreground text-2xl">
        {name}
      </div>
    </div>
  )

  // 左侧侧边栏导航项 —— 顺序即视觉顺序（上→下）
  const SIDEBAR_ITEMS = [
    { key: 'workbench', icon: LayoutDashboard, path: '/workbench' },
    { key: 'womb', icon: Dna, path: '/womb' },
    { key: 'cradle', icon: Baby, path: null },
    { key: 'world', icon: Globe, path: '/world' },
  ]

  const TIME_SCALE_OPTS = [
    { value: 'slow', label: '1x', hint: '~60h' },
    { value: 'normal', label: '7x', hint: '~8h' },
    { value: 'fast', label: '30x', hint: '~2h' },
    { value: 'turbo', label: 'T', hint: '~10min' },
  ]

  const renderSidebar = () => (
    <aside className="w-16 shrink-0 bg-card border-r border-border flex flex-col py-3 gap-3">
      {/* 导航项 —— 工作台后插入分隔线 */}
      {SIDEBAR_ITEMS.map(({ key, icon: Icon, path }, idx) => {
        const active = tab === key
        return (
          <div key={key} className="contents">
            <button
              onClick={() => {
                if (key === 'cradle') {
                  const last = localStorage.getItem('cradle:lastBabyId')
                  navigate(last ? `/cradle/${last}` : '/cradle')
                } else {
                  navigate(path)
                }
              }}
              className={cn(
                "relative mx-1.5 flex flex-col items-center gap-0.5 py-2 rounded-md text-[10px] transition-colors cursor-pointer bg-transparent border-none font-[inherit]",
                active
                  ? "text-primary bg-primary/10 before:content-[''] before:absolute before:left-0 before:top-2 before:bottom-2 before:w-0.5 before:bg-primary before:rounded-r"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted"
              )}
            >
              <Icon className="size-[18px]" strokeWidth={active ? 2.25 : 1.75} />
              <span>{t.tabs[key]}</span>
            </button>
            {idx === 0 && <div className="mx-3 my-5 border-t border-border" />}
          </div>
        )
      })}
      {/* 底部：速率选择器（贴合侧边栏图标栈样式，用 Radix 原语保证点击可触发）*/}
      <div className="mt-auto pb-1 flex justify-center">
        <SelectPrimitive.Root
          value={timeScale}
          onValueChange={async (value) => {
            if (value === timeScale) return  // 选了同值直接跳过，避免无谓 PATCH
            try {
              const r = await fetch(`${API}/system/time-scale`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ time_scale: value }),
              })
              if (r.ok) { localStorage.setItem('timeScale', value); setTimeScale(value) }
            } catch { /* ignore */ }
          }}
        >
          <SelectPrimitive.Trigger asChild>
            <button
              type="button"
              aria-label={lang === 'zh' ? '速率' : 'Speed'}
              className={cn(
                "relative flex flex-col items-center justify-center gap-0.5 px-2 py-2 rounded-md bg-transparent border-none cursor-pointer transition-colors font-[inherit]",
                "outline-none focus:outline-none focus-visible:outline-none focus:ring-0 focus-visible:ring-0",
                "text-muted-foreground hover:text-foreground hover:bg-muted",
                "data-[state=open]:text-primary data-[state=open]:bg-primary/10",
                "data-[state=open]:before:content-[''] data-[state=open]:before:absolute data-[state=open]:before:left-0 data-[state=open]:before:top-2 data-[state=open]:before:bottom-2 data-[state=open]:before:w-0.5 data-[state=open]:before:bg-primary data-[state=open]:before:rounded-r"
              )}
            >
              <Gauge className="size-[18px]" strokeWidth={1.75} />
              <span className="text-[10px] font-medium leading-none tabular-nums">
                {TIME_SCALE_OPTS.find(o => o.value === timeScale)?.label}
              </span>
            </button>
          </SelectPrimitive.Trigger>
          <SelectContent position="popper" side="right" align="end" sideOffset={8}>
            {TIME_SCALE_OPTS.map(opt => (
              <SelectItem key={opt.value} value={opt.value} className="text-xs">
                <span className="font-medium mr-1.5 tabular-nums">{opt.label}</span>
                <span className="text-muted-foreground text-[10px]">{opt.hint}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </SelectPrimitive.Root>
      </div>
    </aside>
  )

  return (
    <div className="flex h-screen">
      {/* 左侧侧边栏（全高，覆盖原顶部导航位置）*/}
      {renderSidebar()}
      {/* 右侧内容区 */}
      <div ref={contentScrollRef} className={cn(
        "flex flex-col flex-1 min-w-0 overflow-hidden",
        tab === 'world' ? "relative bg-transparent" : "bg-[#FDFDFB]"
      )}>
        {/* 顶部导航栏 —— 左：当前页图标+标题；中：视图切换 tag；右：语言 + GitHub
            world 模块下：absolute 浮于地图之上（父级 relative 约束定位范围，保证不影响侧边栏）+ 透明背景 + 永不阴影 */}
        <header
          className={cn(
            "h-14 shrink-0 flex items-center justify-between px-6 transition-[box-shadow,border-color] duration-200",
            tab === 'world'
              ? "absolute inset-x-0 top-0 z-20 bg-transparent border-b border-transparent shadow-none"
              : cn(
                  "relative border-b z-10 bg-[#FDFDFB]",
                  (headerScrolled || isSecondaryPage)
                    ? "border-border/60 shadow-[0_2px_6px_rgba(0,0,0,0.06)]"
                    : "border-transparent shadow-none",
                )
          )}
        >
          <div className="flex items-center gap-2 text-foreground text-sm font-medium">
            {(() => {
              const current = SIDEBAR_ITEMS.find(it => it.key === tab)
              if (!current) return null
              const CurrentIcon = current.icon
              // 宝宝详情页：breadcrumb [摇篮] > [完整 babyId]
              const babyId = tab === 'cradle' ? location.pathname.split('/')[2] : null
              if (babyId) {
                return (
                  <>
                    <CurrentIcon className="size-4 text-muted-foreground" strokeWidth={1.75} />
                    <button
                      type="button"
                      onClick={() => { try { localStorage.removeItem('cradle:lastBabyId') } catch { /* ignore */ } navigate('/cradle') }}
                      className="bg-transparent border-none cursor-pointer font-[inherit] text-inherit p-0 hover:text-primary transition-colors"
                    >
                      {t.tabs[current.key]}
                    </button>
                    <ChevronDown className="size-3 -rotate-90 text-muted-foreground/60" />
                    <span className="font-mono text-xs text-foreground">{babyId}</span>
                  </>
                )
              }
              return (
                <>
                  <CurrentIcon className="size-4 text-muted-foreground" strokeWidth={1.75} />
                  <span>{t.tabs[current.key]}</span>
                </>
              )
            })()}
          </div>
          {/* 中间视图切换：图谱 / 双栏 / 工作台（仅在孕育中、宝宝详情页显示）*/}
          {((tab === 'womb' && isConceiving) || (tab === 'cradle' && !!location.pathname.split('/')[2])) && (
            <div className="absolute left-1/2 -translate-x-1/2 flex items-center gap-1 bg-[#F5F5F5] rounded-md p-1">
              {[
                { value: 'graph', label: lang === 'zh' ? '图谱' : 'Graph' },
                { value: 'split', label: lang === 'zh' ? '双栏' : 'Split' },
                { value: 'workbench', label: lang === 'zh' ? '工作台' : 'Workbench' },
              ].map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setViewMode(opt.value)}
                  className={cn(
                    "border-none px-4 py-1.5 text-xs font-semibold rounded cursor-pointer transition-colors font-[inherit] min-w-[88px] text-center",
                    viewMode === opt.value
                      ? "bg-white text-black shadow-[0_2px_4px_rgba(0,0,0,0.05)]"
                      : "bg-transparent text-[#666] hover:text-black"
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              className="h-7 px-2.5 text-xs gap-1.5 bg-white hover:bg-white"
              onClick={() => { const next = lang === 'en' ? 'zh' : 'en'; localStorage.setItem('lang', next); setLang(next) }}
            >
              <span className="flex items-baseline leading-none">
                <span className={cn(lang === 'en' ? "text-primary font-semibold text-[13px]" : "text-muted-foreground text-[10px]")}>EN</span>
                <span className="text-muted-foreground/60 text-[10px] mx-px">/</span>
                <span className={cn(lang === 'zh' ? "text-primary font-semibold text-[13px]" : "text-muted-foreground text-[10px]")}>中</span>
              </span>
              <ArrowLeftRight className="size-3" />
            </Button>
            <a href="https://github.com/Lofelin/angelcradle" target="_blank" rel="noopener noreferrer">
              <Button size="sm" className="h-7 px-2.5 text-xs gap-1.5 bg-black text-white hover:bg-neutral-800 border-none">
                <svg viewBox="0 0 16 16" fill="currentColor" className="size-3.5"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" /></svg>
                GitHub
              </Button>
            </a>
          </div>
        </header>
        <Routes>
          <Route path="/workbench" element={renderPlaceholder(t.tabs.workbench)} />
          <Route path="/womb" element={renderWomb()} />
          <Route path="/womb/batch" element={renderBatchConceiving()} />
          <Route path="/cradle" element={null} />
          <Route path="/cradle/:babyId" element={null} />
          <Route path="/world" element={
            <div className="flex flex-1 overflow-hidden">
              <WorldMap lang={lang} />
            </div>
          } />
          <Route path="*" element={<Navigate to="/womb" replace />} />
        </Routes>
        {/* Cradle 常驻挂载，避免 tab 切换时丢失内部状态/SSE/滚动位置 */}
        <div className={cn("flex-1 min-h-0", tab === 'cradle' ? 'flex flex-col' : 'hidden')}>
          <Cradle lang={lang} graphState={graphState} graphDispatch={graphDispatch} graphFullscreen={graphFullscreen} workbenchFullscreen={workbenchFullscreen} onToggleGraphFullscreen={toggleGraphFullscreen} />
        </div>
      </div>
    </div>
  )
}

export default App
