/**
 * [INPUT]: react, react-router-dom, ../i18n, shadcn/ui (Button, Card), ../lib/utils
 * [OUTPUT]: Cradle 组件 — 摇篮养育界面
 * [POS]: 摇篮 tab 页面，通过 lifeline SSE（日志读取器模式）接收所有生命事件。后端 scheduler 批量推进阶段，前端仅为观察窗口。客户端 localStorage.lastSeq_{id} 游标实现断点续传。
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */
import { useState, useEffect, useLayoutEffect, useRef, useReducer, useCallback, memo } from 'react'
import { useMatch, useNavigate, useSearchParams } from 'react-router-dom'
import { translateKey } from './i18n'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Avatar, AvatarImage, AvatarFallback, AvatarGroup } from '@/components/ui/avatar'
import { Input } from '@/components/ui/input'
import ConsolePanel from '@/components/ConsolePanel'
import LifeGraph from '@/components/LifeGraph'
import ChatPanel from '@/components/ChatPanel'
import GroupChatPanel from '@/components/GroupChatPanel'
import { createConversation } from './hooks/useConversation'
import { cn } from '@/lib/utils'
import { MessageCircle, Users, ChevronDown, Send, Hand, Bell } from 'lucide-react'

const API = 'http://localhost:8000'

// 触发生命图谱刷新的 SSE 事件白名单——对应后端 engine.record 的调用点
// cradle/nanny.py: scene / psychosocial / stress / capabilities / milestones / critical / caregiver / phase
// scheduler/handlers.py: psychosocial / scene / stress / capabilities / milestones
// cradle/__init__.py: admission（admitted）
const GRAPH_REFRESH_EVENTS = new Set([
  'admitted',
  'phase_start',
  'phase_completed',
  'scene',
  'capabilities_unlocked',
  'milestones',
  'stress_regression',
  'regression_recovery',
  'phase_critical_event',
  'critical_event',
  'autonomous_routine',
  'autonomous_event',
])

// 从 baby_id 提取短标识（取最后一段数字）
const shortId = (id) => id ? (id.split('-').pop() || '?') : '?'

const AVATAR_PALETTES = [
  { bg: 'bg-rose-100 dark:bg-rose-900/40', text: 'text-rose-700 dark:text-rose-300' },
  { bg: 'bg-sky-100 dark:bg-sky-900/40', text: 'text-sky-700 dark:text-sky-300' },
  { bg: 'bg-amber-100 dark:bg-amber-900/40', text: 'text-amber-700 dark:text-amber-300' },
  { bg: 'bg-emerald-100 dark:bg-emerald-900/40', text: 'text-emerald-700 dark:text-emerald-300' },
  { bg: 'bg-violet-100 dark:bg-violet-900/40', text: 'text-violet-700 dark:text-violet-300' },
  { bg: 'bg-teal-100 dark:bg-teal-900/40', text: 'text-teal-700 dark:text-teal-300' },
  { bg: 'bg-pink-100 dark:bg-pink-900/40', text: 'text-pink-700 dark:text-pink-300' },
  { bg: 'bg-indigo-100 dark:bg-indigo-900/40', text: 'text-indigo-700 dark:text-indigo-300' },
]
const avatarPalette = (id) => {
  if (!id) return AVATAR_PALETTES[0]
  let h = 0
  for (let i = 0; i < id.length; i++) h = ((h << 5) - h + id.charCodeAt(i)) | 0
  return AVATAR_PALETTES[Math.abs(h) % AVATAR_PALETTES.length]
}

// Portrait URL helper（支持 cache-busting 版本号）
const portraitUrl = (id, v) => `${API}/cradle/baby/${encodeURIComponent(id)}/portrait${v ? `?v=${v}` : ''}`

// 头像状态缓存——只持久化 'loaded'，'failed' 每次刷新重试（后台可能已生成）
const _portraitCache = (() => { try { return JSON.parse(localStorage.getItem('cradle:portraitCache') || '{}') } catch { return {} } })()
const _setPortrait = (id, v) => {
  _portraitCache[id] = v
  // 只存 loaded，不存 failed——下次刷新会重新尝试加载
  const toSave = {}
  for (const [k, s] of Object.entries(_portraitCache)) { if (s === 'loaded') toSave[k] = s }
  try { localStorage.setItem('cradle:portraitCache', JSON.stringify(toSave)) } catch {}
}

// 宝宝网格卡片
const BabyCard = memo(function BabyCard({ baby, isZh, tk, navigate, setReadiness, getGrowthStatus }) {
  // 只信任 'loaded' 缓存，其余都重新加载
  const cached = _portraitCache[baby.id] === 'loaded' ? 'loaded' : undefined
  const [imgState, setImgState] = useState(cached || 'loading')
  const gs = baby.inCradle ? getGrowthStatus(baby.cradleInfo) : null
  const ageDays = baby.cradleInfo?.age_days ?? 0
  const imgSrc = portraitUrl(baby.id)

  const onLoad = useCallback(() => { _setPortrait(baby.id, 'loaded'); setImgState('loaded') }, [baby.id])
  const onError = useCallback(() => { _setPortrait(baby.id, 'failed'); setImgState('failed') }, [baby.id])

  return (
    <button
      className={cn(
        "relative aspect-square flex flex-col items-center justify-end p-2 rounded-lg border border-border overflow-hidden transition-all duration-200",
        "hover:border-primary/50 hover:shadow-md hover:scale-[1.02] cursor-pointer",
        imgState === 'loaded' && "has-portrait",
        imgState !== 'loaded' && "no-portrait",
      )}
      onClick={() => { navigate(`/cradle/${baby.id}`); setReadiness(null) }}
    >
      {/* 背景头像 + 模糊 */}
      {imgState !== 'failed' && (
        <div className="absolute inset-0">
          <img src={imgSrc} alt="" className="w-full h-full object-cover" onLoad={onLoad} onError={onError} />
          {imgState === 'loaded' && (
            <div className="absolute inset-0 backdrop-blur-[2px] bg-gradient-to-t from-black/80 via-black/40 to-black/10" />
          )}
        </div>
      )}
      {/* 生长状态指示点 */}
      {gs && (
        <span
          className={cn(
            "absolute top-1.5 right-1.5 w-2 h-2 rounded-full",
            gs === 'active' ? 'dot-lifeline' : 'bg-yellow-500',
          )}
          title={gs === 'active' ? (isZh ? '正在生长' : 'Growing') : (isZh ? '生长可能停滞' : 'May be stalled')}
        />
      )}
      {/* 底部文字层 */}
      <div className="relative z-10 text-center min-w-0 w-full flex flex-col gap-1 baby-card-text">
        <div className="font-bold text-xs capitalize truncate baby-card-name">{baby.cradleInfo?.name || tk(baby.species)}</div>
        <div className="text-[10px] capitalize truncate baby-card-sub">
          {[baby.birthplace?.name, tk(baby.sex)].filter(Boolean).join(' · ')}
        </div>
        {baby.inCradle && (
          <div className="flex flex-col items-center gap-0.5 mt-0.5">
            <span className="text-[10px] px-1.5 py-0 rounded-full baby-card-badge">
              {baby.cradleInfo ? `${isZh ? '阶段' : 'P'} ${(baby.cradleInfo.current_phase || 0) + 1}/${PHASES_DATA.length}` : (isZh ? '已入篮' : 'In Cradle')}
              {ageDays > 0 && <span className="ml-0.5 baby-card-badge-dim">· {isZh ? `${ageDays}天` : `D${ageDays}`}</span>}
            </span>
            {gs === 'stale' && (
              <span className="text-[10px] text-yellow-400">{isZh ? '停滞' : 'Stalled'}</span>
            )}
          </div>
        )}
        {baby.born_at && (
          <div className="text-[9px] truncate mt-0.5 baby-card-dim">
            {(() => { const d = new Date(baby.born_at); const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` })()}
          </div>
        )}
      </div>
    </button>
  )
})

const PHASES_DATA = [
  { name: 'neonatal', age: '0-1个月', desc_zh: '只有反射，只会哭泣，完全依赖照护者', desc_en: 'Only reflexes, can only cry, completely dependent on caregiver.' },
  { name: 'sensory_awakening', age: '1-3个月', desc_zh: '开始追踪声光，社交微笑出现', desc_en: 'Begins tracking sounds and light, social smile appears.' },
  { name: 'body_discovery', age: '3-6个月', desc_zh: '发现自己的手，能抓握物体，学会翻身', desc_en: 'Discovers own hands, can grasp objects, learns to roll over.' },
  { name: 'object_permanence', age: '6-9个月', desc_zh: '理解物体消失后仍存在，出现陌生人焦虑', desc_en: 'Understands objects still exist after disappearing. Stranger anxiety.' },
  { name: 'locomotion', age: '9-12个月', desc_zh: '爬行探索世界，指物要求关注', desc_en: 'Crawls to explore the world, points at objects to request attention.' },
  { name: 'first_word', age: '12-18个月', desc_zh: '语言萌芽，开始使用工具，第一个有意义的词诞生', desc_en: 'Language sprouts, begins using tools. The first meaningful word.' },
  { name: 'language_explosion', age: '18-24个月', desc_zh: '双词短语出现，假装游戏，认出镜中的自己', desc_en: 'Two-word phrases emerge, pretend play appears, recognizes self in mirror.' },
  { name: 'why_phase', age: '2-3岁', desc_zh: '完整句子，无穷的"为什么"，频繁的情绪风暴', desc_en: 'Full sentences, endless "why" questions, frequent emotional storms.' },
  { name: 'social_budding', age: '3-4岁', desc_zh: '意识到同龄人，角色扮演游戏，道德感萌芽', desc_en: 'Becomes aware of peers, role-play games, moral sense sprouts.' },
]
const PHASE_NAMES = PHASES_DATA.map(p => p.name)

function getTime() {
  const now = new Date()
  return now.toLocaleTimeString('en-US', { hour12: false }) + '.' + String(now.getMilliseconds()).padStart(3, '0')
}

// ── Reducer ──
const INIT = {
  logs: [],
  phase: null,
  criticals: [],
  running: false,
  intervening: null,
  paused: false,       // grow/stream 因关键事件暂停
  growComplete: false,  // 全部阶段完成
  startedAt: null,
  interacting: false,  // 正在发送对话
  lifelineActive: false, // 生命线 SSE 连接活跃
  simDay: null,          // 当前模拟日（从自主生命事件更新）
  simHour: null,         // 当前模拟小时
  lastActivity: null,    // 上次活动名称
  lastActivityTs: null,  // 上次活动时间戳（wall clock）
  activeNeed: null,      // 当前待响应的宝宝需求 { need_id, trigger, urgency, timeout_sec, expression, ts }
  worldSnapshot: null,   // 最新世界快照 { weather, family_arc, mood }
}

// 从日志中推导 activeNeed：找最后一条 baby_need，如果其后无对应 need_responded 则为 pending
const deriveActiveNeed = (logs) => {
  for (let i = logs.length - 1; i >= 0; i--) {
    const entry = logs[i]
    if (entry.event === 'need_responded') return null  // 最近的需求已响应
    if (entry.event === 'baby_need') {
      const d = entry.data
      return {
        need_id: d.need_id,
        trigger: d.trigger,
        urgency: d.urgency,
        timeout_sec: d.timeout_sec,
        expression: d.expression,
        behavior_type: d.behavior_type,
        parent_hint: d.parent_hint,
        ts: Date.now(),
      }
    }
  }
  return null
}

// sim_tick 是"此刻安静"的活指示器，一旦有真实事件到来就应该消失，
// 而不是作为历史记录留在日志里——否则每两条事件之间都会沉淀一行"安静地生活着..."。
const stripTrailingTick = (logs) => (
  logs.length > 0 && logs[logs.length - 1].event === 'sim_tick'
    ? logs.slice(0, -1)
    : logs
)

function cradleReducer(state, action) {
  switch (action.type) {
    case 'RESET':
      return { ...INIT }
    case 'LIFELINE_CONNECTED':
      return { ...state, lifelineActive: true }
    case 'LIFELINE_DISCONNECTED':
      return { ...state, lifelineActive: false }
    case 'LOAD_HISTORY': {
      // sim_tick 不被后端持久化，刷新时从 state 里保留一条最后的 tick，避免从日志流里凭空消失
      const newLogs = action.logs
      // 从历史日志恢复关键状态，避免刷新后闪烁
      const reversed = [...newLogs].reverse()
      const lastSnap = reversed.find(l => l.event === 'world_snapshot')
      const restoredSnapshot = lastSnap ? { weather: lastSnap.data?.weather, family_arc: lastSnap.data?.family_arc, mood: lastSnap.data?.mood } : state.worldSnapshot
      const activityEvents = new Set(['autonomous_routine', 'autonomous_event', 'autonomous_catchup', 'day_summary'])
      const lastAct = reversed.find(l => activityEvents.has(l.event))
      const restoredSimDay = lastAct?.data?.sim_day ?? lastAct?.data?.to_day ?? state.simDay
      const restoredSimHour = lastAct?.data?.sim_hour ?? state.simHour
      const restoredLastActivity = lastAct?.data?.display_name || lastAct?.data?.event_name || state.lastActivity
      // 有历史日志时预设 lifelineActive，避免尾部指示器闪烁（SSE 连上/断开后会覆盖）
      const restoredNeed = deriveActiveNeed(newLogs)
      const restored = { worldSnapshot: restoredSnapshot, simDay: restoredSimDay, simHour: restoredSimHour, lastActivity: restoredLastActivity, lifelineActive: newLogs.length > 0, activeNeed: restoredNeed }
      const newLastIsTick = newLogs.length > 0 && newLogs[newLogs.length - 1].event === 'sim_tick'
      if (newLastIsTick) return { ...state, logs: newLogs, ...restored }
      const existingTick = [...state.logs].reverse().find(l => l.event === 'sim_tick')
      return { ...state, logs: existingTick ? [...newLogs, existingTick] : newLogs, ...restored }
    }
    case 'RESTORE_CRITICALS': {
      // 从后端 status 恢复待响应的关键事件（页面重进时）
      const restored = (action.criticals || []).filter(
        c => !state.criticals.some(e => e.event_name === c.event_name)
      )
      if (restored.length === 0) return state
      return { ...state, criticals: [...state.criticals, ...restored] }
    }
    case 'START_GROW':
      return { ...INIT, running: true, startedAt: state.startedAt || Date.now() }
    case 'RESUME_GROW':
      return { ...state, logs: [], criticals: [], running: true, paused: false }
    case 'SSE': {
      const { data, ts } = action
      const log = { time: ts, event: data.event, data }
      let logs
      // 心跳事件：只要最后一条也是心跳类型就替换（避免交替刷屏）
      const heartbeatEvents = ['narrating', 'compiling', 'assembling', 'phase_completing']
      const baseLogs = stripTrailingTick(state.logs)
      const lastEvent = baseLogs.length > 0 ? baseLogs[baseLogs.length - 1].event : null
      if (heartbeatEvents.includes(data.event) && data.elapsed && heartbeatEvents.includes(lastEvent)) {
        logs = [...baseLogs.slice(0, -1), log]
      } else {
        logs = [...baseLogs, log]
      }
      let { phase, criticals, worldSnapshot } = state

      if (data.event === 'phase_start') {
        phase = { index: data.phase_index, name: data.phase_name, display: data.phase_display, age_range: data.age_range, description: data.description, expression_mode: data.expression_mode }
      } else if (data.event === 'critical_event') {
        if (!criticals.some(e => e.event_name === data.event_name)) {
          criticals = [...criticals, data]
        }
      } else if (data.event === 'world_snapshot') {
        worldSnapshot = { weather: data.weather, family_arc: data.family_arc, mood: data.mood }
      }
      return { ...state, logs, phase, criticals, worldSnapshot }
    }
    case 'STREAM_END':
      return { ...state, running: false }
    case 'PAUSED':
      return { ...state, running: false, paused: true }
    case 'GROW_COMPLETE':
      return { ...state, running: false, growComplete: true }
    // INTERACT_SENDING / DONE / ERROR: 旧 sendInteraction 路径已删除，
    // 互动通过 ChatPanel → useConversation 走 /conversations SSE。
    // 保留 case 防止 SSE 回放旧 events.jsonl 中的 interaction 事件触发 reducer 报错。
    case 'INTERACT_SENDING':
    case 'INTERACT_DONE':
    case 'INTERACT_ERROR':
      return state
    case 'SSE_INTERACTION': {
      // SSE 收到互动事件：多重去重（fetch 回调可能已添加同一条）
      const sseSeq = action.data?.seq
      // 1) seq 去重：已有同 seq 的完整 interaction → 跳过
      if (sseSeq && state.logs.some(l => l.event === 'interaction' && l.data?.seq === sseSeq)) return state
      // 2) 有匹配的 pending → 替换 pending 为完整 interaction（兼容 fetch 未返回的场景）
      const sseMsg = action.data?.parent_message
      const pending = state.logs.find(l => l.event === 'interaction_pending' && l.data?.parent_message === sseMsg)
      if (pending) {
        const mergedData = { ...action.data, emoji: pending.data?.emoji }
        const log = { time: pending.time, replyTime: getTime(), event: 'interaction', data: mergedData }
        const logs = stripTrailingTick(state.logs.filter(l => l !== pending))
        return { ...state, interacting: false, logs: [...logs, log] }
      }
      // 3) 正在等 fetch 回调且无匹配 pending → 跳过（fetch 会处理）
      if (state.interacting) return state
      // 4) 历史回放或其他来源的互动，正常追加
      const log = { time: getTime(), event: 'interaction', data: action.data }
      return { ...state, logs: [...stripTrailingTick(state.logs), log] }
    }
    case 'HEARTBEAT_INITIATIVE': {
      const log = { time: getTime(), event: 'heartbeat_initiative', data: action.data }
      return { ...state, logs: [...stripTrailingTick(state.logs), log] }
    }
    case 'HEARTBEAT_IGNORED': {
      const log = { time: getTime(), event: 'heartbeat_ignored', data: action.data }
      return { ...state, logs: [...stripTrailingTick(state.logs), log] }
    }
    case 'BABY_NEED': {
      const log = { time: getTime(), event: 'baby_need', data: action.data }
      return {
        ...state,
        logs: [...stripTrailingTick(state.logs), log],
        activeNeed: {
          need_id: action.data.need_id,
          trigger: action.data.trigger,
          urgency: action.data.urgency,
          timeout_sec: action.data.timeout_sec,
          expression: action.data.expression,
          behavior_type: action.data.behavior_type,
          parent_hint: action.data.parent_hint,
          ts: Date.now(),
        },
      }
    }
    case 'NEED_RESPONDED': {
      const log = { time: getTime(), event: 'need_responded', data: action.data }
      return {
        ...state,
        logs: [...stripTrailingTick(state.logs), log],
        activeNeed: null,
      }
    }
    case 'RESTORE_NEED': {
      // 页面刷新后从 /status 恢复 pending need（不写日志，日志已通过 lifeline 回放）
      return {
        ...state,
        activeNeed: {
          need_id: action.need.need_id,
          trigger: action.need.trigger,
          urgency: action.need.urgency,
          timeout_sec: action.need.timeout_sec,
          expression: action.need.expression,
          behavior_type: action.need.behavior_type,
          parent_hint: action.need.parent_hint,
          ts: Date.now(),
        },
      }
    }
    case 'INTERVENE_START':
      return { ...state, intervening: action.eventName }
    case 'INTERVENE_DONE': {
      const logs = [...stripTrailingTick(state.logs), { time: getTime(), event: 'intervene_result', data: action.result }]
      const criticals = state.criticals.filter(c => c.event_name !== action.eventName)
      return { ...state, logs, criticals, intervening: null }
    }
    case 'CRITICAL_EXPIRED': {
      const log = { time: action.ts, event: 'critical_expired', data: action.data }
      const criticals = state.criticals.map(c =>
        c.event_name === action.data.event_name ? { ...c, expired: true } : c
      )
      return { ...state, logs: [...stripTrailingTick(state.logs), log], criticals }
    }
    case 'AUTONOMOUS_ROUTINE': {
      const log = { time: getTime(), event: 'autonomous_routine', data: action.data }
      return { ...state, logs: [...stripTrailingTick(state.logs), log],
        simDay: action.data.sim_day ?? state.simDay,
        simHour: action.data.sim_hour ?? state.simHour,
        lastActivity: action.data.display_name || action.data.event_name,
        lastActivityTs: Date.now(),
      }
    }
    case 'AUTONOMOUS_EVENT': {
      const log = { time: getTime(), event: 'autonomous_event', data: action.data }
      // 先剥掉末尾可能存在的 sim_tick，再判断是否替换 processing 行
      const baseLogs = stripTrailingTick(state.logs)
      const lastLog = baseLogs[baseLogs.length - 1]
      const logs = lastLog?.data?.event === 'autonomous_processing'
        ? [...baseLogs.slice(0, -1), log]
        : [...baseLogs, log]
      return { ...state, logs,
        simDay: action.data.sim_day ?? state.simDay,
        simHour: action.data.sim_hour ?? state.simHour,
        lastActivity: action.data.display_name || action.data.event_name,
        lastActivityTs: Date.now(),
      }
    }
    case 'AUTONOMOUS_CATCHUP': {
      const log = { time: getTime(), event: 'autonomous_catchup', data: action.data }
      const events = action.data.events || []
      const last = events[events.length - 1]
      return { ...state, logs: [...stripTrailingTick(state.logs), log],
        simDay: last?.sim_day ?? state.simDay,
        lastActivityTs: Date.now(),
      }
    }
    case 'DAY_SUMMARY': {
      // 平静日压缩摘要：显示为折叠行
      const log = { time: getTime(), event: 'day_summary', data: action.data }
      return { ...state, logs: [...stripTrailingTick(state.logs), log],
        simDay: action.data.to_day ?? state.simDay,
        lastActivityTs: Date.now(),
      }
    }
    case 'SIM_TICK': {
      // 模拟时钟 tick：替换上一条 tick（不堆积），保持单行滚动
      // chainStart 记录当前"安静链路"起始时间戳，用于累计秒数显示
      const lastLog2 = state.logs[state.logs.length - 1]
      const chainStart = (lastLog2?.event === 'sim_tick' && lastLog2.chainStart)
        ? lastLog2.chainStart
        : Date.now()
      const tickLog = { time: getTime(), event: 'sim_tick', data: action.data, chainStart }
      const logs = lastLog2?.event === 'sim_tick'
        ? [...state.logs.slice(0, -1), tickLog]
        : [...state.logs, tickLog]
      return { ...state, logs,
        simDay: action.data.sim_day ?? state.simDay,
        simHour: action.data.sim_hour ?? state.simHour,
      }
    }
    default:
      return state
  }
}

export default function Cradle({ lang, graphState, graphDispatch }) {
  const tk = (v) => translateKey(v, lang)
  const isZh = lang === 'zh'

  const cradleMatch = useMatch('/cradle/:babyId')
  const selectedId = cradleMatch?.params?.babyId
  const navigate = useNavigate()

  // 摇篮生命图谱：切换宝宝初始加载 + SSE 事件驱动的节流刷新
  const cradleGraphFetchTimerRef = useRef(null)
  const fetchCradleGraph = useCallback((babyId) => {
    if (!babyId || !graphDispatch) return
    fetch(`${API}/cradle/${babyId}/graph`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data?.nodes?.length > 0 || data?.links?.length > 0) {
          graphDispatch({ type: 'LOAD_GRAPH', payload: data })
        }
      })
      .catch(() => { /* ignore */ })
  }, [graphDispatch])
  const scheduleCradleGraphFetch = useCallback(() => {
    if (!selectedId) return
    if (cradleGraphFetchTimerRef.current) clearTimeout(cradleGraphFetchTimerRef.current)
    cradleGraphFetchTimerRef.current = setTimeout(() => fetchCradleGraph(selectedId), 300)
  }, [selectedId, fetchCradleGraph])

  // 切换宝宝时立即加载一次；先清空以避免残留的子宫图谱短暂可见
  useEffect(() => {
    if (!selectedId) return
    graphDispatch?.({ type: 'CLEAR_GRAPH' })
    fetchCradleGraph(selectedId)
  }, [selectedId, fetchCradleGraph, graphDispatch])
  const [searchParams, setSearchParams] = useSearchParams()


  const [birthBabies, setBirthBabies] = useState(() => {
    try { return JSON.parse(localStorage.getItem('cradle:birthBabies') || '[]') } catch { return [] }
  })
  const [cradleBabies, setCradleBabies] = useState(() => {
    try { return JSON.parse(localStorage.getItem('cradle:cradleBabies') || '[]') } catch { return [] }
  })
  const [babyStatus, _setBabyStatus] = useState(() => {
    // 从缓存预加载，避免刷新时头部闪烁
    if (!selectedId) return null
    try { return JSON.parse(localStorage.getItem(`cradle:status:${selectedId}`)) } catch { return null }
  })
  const setBabyStatus = useCallback((valOrFn) => {
    _setBabyStatus(prev => {
      const next = typeof valOrFn === 'function' ? valOrFn(prev) : valOrFn
      // 写入缓存（null 时清除）
      try {
        if (next && selectedId) localStorage.setItem(`cradle:status:${selectedId}`, JSON.stringify(next))
        else if (selectedId) localStorage.removeItem(`cradle:status:${selectedId}`)
      } catch { /* ignore */ }
      return next
    })
  }, [selectedId])
  const [phaseSummaries, setPhaseSummaries] = useState({}) // 阶段完成总结 { index: summary_text }
  const [admitting, setAdmitting] = useState(false)
  const [portraitVer, setPortraitVer] = useState(0)  // cache-busting: admitted 后递增
  // 有 localStorage 缓存时跳过加载态，避免刷新闪烁
  const [initialLoaded, setInitialLoaded] = useState(() => birthBabies.length > 0 || cradleBabies.length > 0)
  const [readiness, _setReadiness] = useState(() => {
    if (!selectedId) return null
    try { return JSON.parse(localStorage.getItem(`cradle:readiness:${selectedId}`)) } catch { return null }
  })
  const setReadiness = useCallback((val) => {
    _setReadiness(val)
    try {
      if (val && selectedId) localStorage.setItem(`cradle:readiness:${selectedId}`, JSON.stringify(val))
      else if (selectedId) localStorage.removeItem(`cradle:readiness:${selectedId}`)
    } catch { /* ignore */ }
  }, [selectedId])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [nameInput, setNameInput] = useState('')
  const [state, dispatch] = useReducer(cradleReducer, INIT, (init) => {
    // 首次渲染前从 localStorage 预填当前宝宝的历史日志，消除刷新时控制台闪烁
    if (!selectedId) return init
    try {
      const cached = localStorage.getItem(`cradle:logs:${selectedId}`)
      if (cached) {
        const parsed = JSON.parse(cached)
        if (Array.isArray(parsed) && parsed.length > 0) {
          // 从缓存日志恢复关键状态（与 LOAD_HISTORY 逻辑一致）
          const reversed = [...parsed].reverse()
          const lastSnap = reversed.find(l => l.event === 'world_snapshot')
          const activityEvents = new Set(['autonomous_routine', 'autonomous_event', 'autonomous_catchup', 'day_summary'])
          const lastAct = reversed.find(l => activityEvents.has(l.event))
          return {
            ...init,
            logs: parsed,
            lifelineActive: true,
            worldSnapshot: lastSnap ? { weather: lastSnap.data?.weather, family_arc: lastSnap.data?.family_arc, mood: lastSnap.data?.mood } : null,
            simDay: lastAct?.data?.sim_day ?? lastAct?.data?.to_day ?? null,
            simHour: lastAct?.data?.sim_hour ?? null,
            lastActivity: lastAct?.data?.display_name || lastAct?.data?.event_name || null,
            activeNeed: deriveActiveNeed(parsed),
          }
        }
      }
    } catch { /* ignore */ }
    return init
  })
  // 定时 tick：用于刷新"自主生活中"→"生命线"状态切换
  const [, forceUpdate] = useReducer(x => x + 1, 0)
  useEffect(() => {
    if (!state.lastActivityTs) return
    const id = setTimeout(forceUpdate, 31000)
    return () => clearTimeout(id)
  }, [state.lastActivityTs])

  // 每秒强制重渲：sim_tick 尾部指示器 + activeNeed 倒计时
  const lastLogEvent = state.logs.length > 0 ? state.logs[state.logs.length - 1].event : null
  const hasTickOrNeed = lastLogEvent === 'sim_tick' || state.activeNeed
  useEffect(() => {
    if (!hasTickOrNeed) return
    const id = setInterval(forceUpdate, 1000)
    return () => clearInterval(id)
  }, [hasTickOrNeed])
  const logRef = useRef(null)
  const currentPhaseRef = useRef(null)
  const logRefCb = useCallback((node) => {
    logRef.current = node
    if (node) node.scrollTop = node.scrollHeight
  }, [])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [state.logs, state.lifelineActive])

  // 日志持久化到 localStorage，刷新页面时可即时恢复（防闪烁）
  useEffect(() => {
    if (!selectedId || state.logs.length === 0) return
    try {
      // 只缓存最近 300 条，避免 localStorage 配额问题
      const slice = state.logs.slice(-300)
      localStorage.setItem(`cradle:logs:${selectedId}`, JSON.stringify(slice))
    } catch { /* quota or disabled */ }
  }, [state.logs, selectedId])

  // 自动滚动到当前阶段卡片（首次渲染直接定位，阶段变化/全部完成时平滑滚动）
  const phaseScrolledRef = useRef(false)
  const lifeCompleted = state.logs.some(l => l.event === 'life_complete' || l.event === 'cradle_complete')
  useEffect(() => {
    setTimeout(() => {
      if (currentPhaseRef.current) {
        currentPhaseRef.current.scrollIntoView({ behavior: phaseScrolledRef.current ? 'smooth' : 'instant', block: 'center' })
        phaseScrolledRef.current = true
      }
    }, 100)
  }, [babyStatus?.current_phase?.index, lifeCompleted])

  // ── 数据加载 ──
  const loadBabies = useCallback(() => {
    Promise.all([
      fetch(`${API}/babies`).then(r => r.json()).catch(() => ({ babies: [] })),
      fetch(`${API}/cradle/babies`).then(r => r.json()).catch(() => ({ babies: [] })),
    ]).then(([birth, cradle]) => {
      const birthList = birth.babies || []
      const cradleList = cradle.babies || []
      // 只在数据实际变化时更新，避免新引用触发全量重渲染导致闪烁
      const birthJson = JSON.stringify(birthList)
      const cradleJson = JSON.stringify(cradleList)
      setBirthBabies(prev => JSON.stringify(prev) === birthJson ? prev : birthList)
      setCradleBabies(prev => JSON.stringify(prev) === cradleJson ? prev : cradleList)
      setInitialLoaded(true)
      try {
        localStorage.setItem('cradle:birthBabies', birthJson)
        localStorage.setItem('cradle:cradleBabies', cradleJson)
      } catch { /* quota or disabled */ }
    })
  }, [])

  useEffect(() => { loadBabies() }, [loadBabies])

  // 返回列表页时刷新婴儿数据（scheduler 可能已在后台推进天数/阶段）
  useEffect(() => {
    if (!selectedId && initialLoaded) loadBabies()
  }, [selectedId])

  // 记住最后访问的宝宝，便于从其他 tab 切回时恢复
  useEffect(() => {
    if (selectedId) {
      try { localStorage.setItem('cradle:lastBabyId', selectedId) } catch { /* ignore */ }
    }
  }, [selectedId])

  const loadStatus = useCallback((id) => {
    fetch(`${API}/cradle/${id}/status`)
      .then(r => { if (!r.ok) throw new Error(); return r.json() })
      .then(d => {
        setBabyStatus({ ...d, last_active_ts: Date.now() / 1000 })
        // 恢复待响应的关键事件（页面重进时）
        if (d.pending_criticals?.length > 0) {
          dispatch({ type: 'RESTORE_CRITICALS', criticals: d.pending_criticals })
        }
        // 恢复待响应的宝宝需求（页面刷新后）
        if (d.pending_need) {
          dispatch({ type: 'RESTORE_NEED', need: d.pending_need })
          setChatMode(prev => prev || 'single')
        }
      })
      .catch(() => setBabyStatus(null))
  }, [])

  // admit 刚完成时不清空日志（admit 日志应衔接成长日志）
  const justAdmittedRef = useRef(false)
  const prevSelectedIdRef = useRef(selectedId)

  useEffect(() => {
    // API 首次加载完成前不运行（避免 localStorage 缓存触发无用 RESET + 闪烁）
    if (!initialLoaded) return

    const skipReset = justAdmittedRef.current
    justAdmittedRef.current = false

    // 只在切换到不同宝宝时 RESET（刷新页面 / cradleBabies 更新不 RESET）
    const idChanged = prevSelectedIdRef.current !== selectedId
    prevSelectedIdRef.current = selectedId
    if (!skipReset && idChanged) {
      dispatch({ type: 'RESET' })
    }
    const savedMode = sessionStorage.getItem(`chatMode:${selectedId}`)
    setChatMode((savedMode === 'single' || savedMode === 'group') ? savedMode : false)
    setReadiness(null)
    setTouchActions(null)

    if (!selectedId) { setBabyStatus(null); return }
    const inCradle = cradleBabies.some(b => b.baby_id === selectedId)
    if (!inCradle) {
      // 来自 Womb 的自动跳转：旧 cradleBabies 列表还没包含新入摇篮的宝宝，主动刷新一次
      const shouldAdmit = searchParams.get('autoAdmit') === 'true' || searchParams.get('autoGrow') === 'true'
      if (shouldAdmit) loadBabies()
      setBabyStatus(null)
      return
    }
    // 从 localStorage 预加载日志，避免每次刷新控制台闪烁重建
    try {
      const cached = localStorage.getItem(`cradle:logs:${selectedId}`)
      if (cached) {
        const parsed = JSON.parse(cached)
        if (Array.isArray(parsed) && parsed.length > 0) {
          dispatch({ type: 'LOAD_HISTORY', logs: parsed })
        }
      }
    } catch { /* ignore */ }

    loadStatus(selectedId)
    fetch(`${API}/cradle/${selectedId}/history`).then(r => r.ok ? r.json() : null).then(h => {
        if (!h?.phase_summaries) return
        const m = {}; h.phase_summaries.forEach((s, i) => { let t = typeof s === 'object' ? s?.summary : s; if (t && typeof t === 'object') t = t.summary || JSON.stringify(t); if (t) m[i] = t }); setPhaseSummaries(m)
      }).catch(() => {})
      // 自动检查就绪度
      fetch(`${API}/cradle/${selectedId}/readiness`)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) setReadiness(d) })
        .catch(() => {})
      // 历史事件由 lifeline SSE 回放（after_seq 游标），无需额外拉取 /events
      // admit 刚完成时也跳过，日志已在 state.logs 中
  }, [selectedId, cradleBabies, initialLoaded, loadStatus, loadBabies, setSearchParams])

  // ── 自驱动生命：阶段推进由后端 scheduler 驱动 ──
  // 前端只通过 heartbeat/stream 接收事件，不需要主动触发 grow/stream。
  // grow/stream 保留为手动备用路径。
  const startGrowRef = useRef(null)

  // ── 操作 ──
  const admitBaby = (babyId) => {
    setAdmitting(true)

    const source = new EventSource(`${API}/cradle/admit/stream?baby_id=${encodeURIComponent(babyId)}`)
    source.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        // 推进 lastSeq，避免随后 lifeline?after_seq=0 重放 admit 事件造成控制台重复
        if (data.seq) {
          localStorage.setItem(`lastSeq_${babyId}`, String(data.seq))
        }
        dispatch({ type: 'SSE', data, ts: getTime() })

        if (data.event === 'admitted') {
          source.close()
          setAdmitting(false)
          // 标记刚完成 admit，跳过下次 effect 的 RESET
          justAdmittedRef.current = true
          // 刷新头像（入摇篮后可能重新生成了国家匹配头像）
          _setPortrait(babyId, undefined)
          setPortraitVer(v => v + 1)
          // 刷新列表 + 状态，lifeline SSE 会在 isCurrentInCradle 变化后自动连接
          loadBabies()
          loadStatus(babyId)
        } else if (data.event === 'error') {
          source.close()
          setAdmitting(false)
        }
      } catch { /* ignore */ }
    }
    source.onerror = () => {
      source.close()
      setAdmitting(false)
    }
  }

  // 从子宫跳转来 / URL 带 autoAdmit：自动触发 admit
  useEffect(() => {
    const shouldAdmit = searchParams.get('autoAdmit') === 'true' || searchParams.get('autoGrow') === 'true'
    if (!shouldAdmit || !selectedId) return
    setSearchParams({}, { replace: true })
    const inCradle = cradleBabies.some(b => b.baby_id === selectedId)
    if (!inCradle && !admitting) {
      admitBaby(selectedId)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, searchParams])

  // grow/stream 已废弃：主路径由后端 scheduler 自驱动
  // 保留 startGrowRef 避免其他残留引用报错
  startGrowRef.current = null

  const intervene = async (eventName, parentAction, parentInput = '') => {
    dispatch({ type: 'INTERVENE_START', eventName })
    try {
      const r = await fetch(`${API}/cradle/${selectedId}/intervene`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_name: eventName, parent_action: parentAction, parent_input: parentInput }),
      })
      const result = await r.json()
      dispatch({ type: 'INTERVENE_DONE', eventName, result })
      loadStatus(selectedId)
    } catch (e) {
      dispatch({ type: 'INTERVENE_DONE', eventName, result: { error: String(e) } })
    }
  }

  const [chatMode, setChatMode] = useState(() => {
    try {
      if (!selectedId) return false
      const saved = sessionStorage.getItem(`chatMode:${selectedId}`)
      if (saved === 'single' || saved === 'group') return saved
      return false
    } catch { return false }
  })
  const [chatTargetOpen, setChatTargetOpen] = useState(false) // 多宝宝下拉
  const [groupConvId, setGroupConvId] = useState(() => {
    try { return sessionStorage.getItem(`groupConvId:${selectedId}`) || null } catch { return null }
  })
  const [groupNameInput, setGroupNameInput] = useState('') // 群名输入
  const [socialSelected, setSocialSelected] = useState([]) // 多宝宝选择
  const [groupCreating, setGroupCreating] = useState(false)
  const [criticalsPanelOpen, setCriticalsPanelOpen] = useState(false) // 关键事件面板
  const criticalsPanelRef = useRef(null)
  // 默认肢体动作列表（后端可覆盖）
  const DEFAULT_TOUCH_ACTIONS = {
    actions: {
      comfort: {
        emoji: '🤗', label_zh: '安抚', label_en: 'Comfort',
        actions: [
          { key: 'hug', emoji: '🤗', label_zh: '拥抱', label_en: 'Hug' },
          { key: 'pat_back', emoji: '👋', label_zh: '拍背', label_en: 'Pat back' },
          { key: 'stroke_head', emoji: '🫳', label_zh: '摸头', label_en: 'Stroke head' },
          { key: 'rock', emoji: '🫂', label_zh: '轻摇', label_en: 'Rock gently' },
        ],
      },
      play: {
        emoji: '🎮', label_zh: '玩耍', label_en: 'Play',
        actions: [
          { key: 'tickle', emoji: '🤭', label_zh: '挠痒', label_en: 'Tickle' },
          { key: 'peek_a_boo', emoji: '🙈', label_zh: '躲猫猫', label_en: 'Peek-a-boo' },
          { key: 'clap_hands', emoji: '👏', label_zh: '拍手', label_en: 'Clap hands' },
          { key: 'blow_raspberry', emoji: '😜', label_zh: '吹嘴唇', label_en: 'Blow raspberry' },
        ],
      },
      care: {
        emoji: '💛', label_zh: '照护', label_en: 'Care',
        actions: [
          { key: 'feed', emoji: '🍼', label_zh: '喂食', label_en: 'Feed' },
          { key: 'change_diaper', emoji: '👶', label_zh: '换尿布', label_en: 'Change diaper' },
          { key: 'burp', emoji: '💨', label_zh: '拍嗝', label_en: 'Burp' },
          { key: 'swaddle', emoji: '🧸', label_zh: '裹襁褓', label_en: 'Swaddle' },
        ],
      },
      stimulate: {
        emoji: '✨', label_zh: '刺激', label_en: 'Stimulate',
        actions: [
          { key: 'show_toy', emoji: '🧸', label_zh: '展示玩具', label_en: 'Show toy' },
          { key: 'sing', emoji: '🎵', label_zh: '唱歌', label_en: 'Sing' },
          { key: 'read_book', emoji: '📖', label_zh: '读绘本', label_en: 'Read book' },
          { key: 'tummy_time', emoji: '🐣', label_zh: '趴着玩', label_en: 'Tummy time' },
        ],
      },
    },
  }
  const [touchActions, setTouchActions] = useState(DEFAULT_TOUCH_ACTIONS)

  // 持久化 chatMode + groupConvId
  useEffect(() => {
    if (selectedId) {
      if (chatMode === 'single' || chatMode === 'group') sessionStorage.setItem(`chatMode:${selectedId}`, chatMode)
      else sessionStorage.removeItem(`chatMode:${selectedId}`)
      if (groupConvId) sessionStorage.setItem(`groupConvId:${selectedId}`, groupConvId)
      else sessionStorage.removeItem(`groupConvId:${selectedId}`)
    }
  }, [chatMode, selectedId, groupConvId])
  const chatTargetRef = useRef(null)

  // 关键事件全部处理完后自动关闭面板
  useEffect(() => {
    if (state.criticals.length === 0) setCriticalsPanelOpen(false)
  }, [state.criticals.length])

  // 点击外部关闭下拉
  useEffect(() => {
    if (!chatTargetOpen && !criticalsPanelOpen) return
    const handler = (e) => {
      if (chatTargetOpen && chatTargetRef.current && !chatTargetRef.current.contains(e.target)) setChatTargetOpen(false)
      if (criticalsPanelOpen && criticalsPanelRef.current && !criticalsPanelRef.current.contains(e.target)) setCriticalsPanelOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [chatTargetOpen, criticalsPanelOpen])

  // 加载肢体动作列表
  const loadTouchActions = async () => {
    if (!selectedId) return
    try {
      const r = await fetch(`${API}/cradle/${selectedId}/touch-actions`)
      if (r.ok) setTouchActions(await r.json())
    } catch { /* ignore */ }
  }

  // 生命线 SSE：通过 lifeline 端点接收所有事件（日志读取器模式）
  // 前端带 after_seq 游标连接，断连重连从断点继续
  const isCurrentInCradle = initialLoaded && cradleBabies.some(b => b.baby_id === selectedId)
  useEffect(() => {
    if (!selectedId || !isCurrentInCradle) return

    let source = null
    let closed = false
    let reconnectTimer = null

    // 手动管理重连：每次重连从最新 lastSeq 构建 URL，避免重复回放
    const connect = () => {
      if (closed) return
      const seq = parseInt(localStorage.getItem(`lastSeq_${selectedId}`) || '0', 10)
      source = new EventSource(`${API}/cradle/${selectedId}/lifeline?after_seq=${seq}`)
      source.onopen = () => dispatch({ type: 'LIFELINE_CONNECTED' })
      source.onmessage = handleMessage
      source.onerror = () => {
        dispatch({ type: 'LIFELINE_DISCONNECTED' })
        source.close()
        reconnectTimer = setTimeout(connect, 3000)
      }
    }

    const handleMessage = (e) => {
      try {
        const data = JSON.parse(e.data)

        // 收到任何 SSE 事件 → 后端在活跃，刷新 last_active_ts 避免误判停滞
        // 只更新 babyStatus，不动 cradleBabies（cradleBabies 是 effect 依赖，改它会触发 loadStatus 用旧值覆盖）
        setBabyStatus(prev => prev ? { ...prev, last_active_ts: Date.now() / 1000 } : prev)

        // 更新游标（所有带 seq 的事件）
        if (data.seq) {
          localStorage.setItem(`lastSeq_${selectedId}`, String(data.seq))
        }

        // 宝宝主动需求：自动打开对话框
        if (data.event === 'baby_need') {
          dispatch({ type: 'BABY_NEED', data })
          setChatMode(prev => prev || 'single')
        }
        else if (data.event === 'need_responded') dispatch({ type: 'NEED_RESPONDED', data })
        // 世界快照（仅日志展示）
        else if (data.event === 'world_snapshot' || data.event === 'world_snapshot_fallback') {
          dispatch({ type: 'SSE', data, ts: getTime() })
        }
        // 心跳主动行为
        else if (data.event === 'heartbeat_initiative') dispatch({ type: 'HEARTBEAT_INITIATIVE', data })
        else if (data.event === 'heartbeat_ignored') dispatch({ type: 'HEARTBEAT_IGNORED', data })
        // LLM 处理中
        else if (data.event === 'autonomous_processing') {
          dispatch({ type: 'AUTONOMOUS_ROUTINE', data: { ...data, event: 'autonomous_processing' } })
        }
        // 自主生命事件
        else if (data.event === 'autonomous_routine' || data.event === 'autonomous_event') {
          dispatch({ type: data.event === 'autonomous_routine' ? 'AUTONOMOUS_ROUTINE' : 'AUTONOMOUS_EVENT', data })
          if (data.age_days != null) {
            setBabyStatus(prev => prev && data.age_days !== prev.age_days ? { ...prev, age_days: data.age_days } : prev)
            setCradleBabies(prev => prev.map(b => b.baby_id === selectedId && b.age_days !== data.age_days ? { ...b, age_days: data.age_days } : b))
          }
        }
        else if (data.event === 'sim_tick') dispatch({ type: 'SIM_TICK', data })
        // 平静日压缩摘要
        else if (data.event === 'day_summary') {
          dispatch({ type: 'DAY_SUMMARY', data })
          if (data.age_days_end != null) {
            setBabyStatus(prev => prev ? { ...prev, age_days: data.age_days_end } : prev)
            setCradleBabies(prev => prev.map(b => b.baby_id === selectedId ? { ...b, age_days: data.age_days_end } : b))
          }
        }
        // 阶段推进事件
        else if (data.event === 'phase_critical_event' || data.event === 'critical_event') {
          dispatch({ type: 'SSE', data: { ...data, event: 'critical_event', awaiting_parent: true }, ts: getTime() })
        }
        else if (data.event === 'critical_expired') {
          dispatch({ type: 'CRITICAL_EXPIRED', data, ts: getTime() })
        }
        else if (data.event === 'phase_start' || data.event === 'phase_completed' ||
                 data.event === 'phase_completing' || data.event === 'life_complete' || data.event === 'cradle_complete' ||
                 data.event === 'scene' || data.event === 'perceiving' ||
                 data.event === 'capabilities_unlocked' || data.event === 'milestones' ||
                 data.event === 'phase_state_update' || data.event === 'stress_regression' ||
                 data.event === 'regression_recovery' || data.event === 'phase_simulated' ||
                 data.event === 'fate_weaving') {
          dispatch({ type: 'SSE', data, ts: getTime() })
          setBabyStatus(prev => {
            if (!prev) return prev
            let next = prev
            if (data.event === 'phase_start') {
              next = { ...next, current_phase: { index: data.phase_index, name: data.phase_name, display: data.phase_display }, pending_criticals: [] }
              if (data.expression_mode) next = { ...next, expression_mode: data.expression_mode }
              setCradleBabies(prev => prev.map(b => b.baby_id === selectedId ? { ...b, current_phase: data.phase_index } : b))
            } else if (data.event === 'capabilities_unlocked' && data.capabilities) {
              const existing = new Set(next.capabilities || [])
              next = { ...next, capabilities: [...(next.capabilities || []), ...data.capabilities.filter(c => !existing.has(c))] }
            } else if (data.event === 'milestones' && data.milestones) {
              next = { ...next, milestones: [...(next.milestones || []), ...data.milestones] }
            } else if (data.event === 'phase_completed') {
              loadStatus(selectedId)
            } else if (data.event === 'phase_state_update') {
              const changes = data.changes || []
              for (const c of changes) {
                if (c.type === 'physical_growth') next = { ...next, physical: { ...(next.physical || {}), height_cm: c.height_cm, weight_kg: c.weight_kg } }
                else if (c.type === 'new_teeth') next = { ...next, physical: { ...(next.physical || {}), teeth_count: c.total } }
                else if (c.type === 'feeding_transition') next = { ...next, nutrition_sleep: { ...(next.nutrition_sleep || {}), feeding_mode: c.to } }
              }
            } else if (data.event === 'stress_regression') {
              next = { ...next, stress: { ...(next.stress || {}), stress_level: data.stress_level } }
            } else if (data.event === 'scene' && data.stress_level != null) {
              next = { ...next, stress: { ...(next.stress || {}), stress_level: data.stress_level } }
            }
            return next === prev ? prev : next
          })
        }
        // 入摇篮事件（也通过日志流推送）
        else if (data.event === 'loading' || data.event === 'extracting' ||
                 data.event === 'compiling' || data.event === 'constraints_ready' ||
                 data.event === 'assembling' || data.event === 'admitted') {
          dispatch({ type: 'SSE', data, ts: getTime() })
        }
        // 互动事件（旧格式，历史回放兼容）
        else if (data.event === 'interaction') {
          dispatch({ type: 'SSE_INTERACTION', data })
        }
        // 会话消息薄索引（新路径：conversation_message）
        else if (data.event === 'conversation_message') {
          dispatch({ type: 'SSE', data, ts: getTime() })
        }

        // 生命图谱：任何触发 lifegraph reducer 写入的事件后，节流刷新图谱
        // 对应后端 engine.record 的调用点（cradle/nanny.py + scheduler/handlers.py）
        if (GRAPH_REFRESH_EVENTS.has(data.event)) {
          scheduleCradleGraphFetch()
        }
      } catch { /* ignore */ }
    }
    connect()

    return () => {
      closed = true
      clearTimeout(reconnectTimer)
      if (source) source.close()
      dispatch({ type: 'LIFELINE_DISCONNECTED' })
    }
  }, [selectedId, isCurrentInCradle, scheduleCradleGraphFetch])

  const checkReadiness = async () => {
    if (!selectedId) return
    try {
      const r = await fetch(`${API}/cradle/${selectedId}/readiness`)
      setReadiness(await r.json())
    } catch { setReadiness(null) }
  }

  // 创建群聊会话
  const startGroupChat = async () => {
    if (socialSelected.length < 2 || !groupNameInput.trim()) return
    setGroupCreating(true)
    try {
      const meta = await createConversation({
        participants: socialSelected,
        kind: 'group',
        displayName: groupNameInput.trim(),
      })
      setGroupConvId(meta.conv_id)
      setChatMode('group')
      setChatTargetOpen(false)
      setGroupNameInput('')
    } catch (e) {
      console.error('Group create failed:', e)
    } finally {
      setGroupCreating(false)
    }
  }

  const isInCradle = (babyId) => cradleBabies.some(b => b.baby_id === babyId)
  const selectedBirth = birthBabies.find(b => b.id === selectedId)
  const allPhasesComplete = babyStatus && babyStatus.current_phase?.index >= PHASES_DATA.length - 1

  // ── 生长状态判断 ──
  // precise=true 用于选中宝宝（有 SSE 连接实时刷新 last_active_ts）
  // precise=false 用于列表页（无 SSE，last_active_ts 来自 API 持久化值，更新稀疏）
  const getGrowthStatus = (info, precise = false) => {
    if (!info || !info.last_active_ts) return 'unknown'
    if (!precise) return 'active'  // 列表页：在摇篮中即视为活跃
    const elapsed = Date.now() / 1000 - info.last_active_ts
    if (elapsed < 120) return 'active'
    return 'stale'
  }

  // ── 婴儿列表 ──
  const renderBabyList = () => {
    if (!initialLoaded) {
      return (
        <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
          <span className="animate-pulse">{isZh ? '加载中...' : 'Loading...'}</span>
        </div>
      )
    }

    const allBabies = birthBabies.map(b => ({
      id: b.id, species: b.species, sex: b.sex, alive: b.alive,
      birthplace: b.birthplace, born_at: b.born_at,
      inCradle: isInCradle(b.id),
      cradleInfo: cradleBabies.find(c => c.baby_id === b.id),
    })).filter(b => b.alive)

    if (allBabies.length === 0) {
      return (
        <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
          {isZh ? '还没有婴儿出生。请先前往子宫进行孕育。' : 'No babies born yet. Go to Womb to conceive first.'}
        </div>
      )
    }

    return (
      <div className="flex flex-col p-6">
        <div className="text-sm text-muted-foreground mb-3">
          {isZh ? '选择一个婴儿进行养育' : 'Select a baby to nurture'}
        </div>
        <div className="grid gap-3 grid-cols-4 sm:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10">
          {allBabies.map(baby => (
            <BabyCard key={baby.id} baby={baby} isZh={isZh} tk={tk} navigate={navigate} setReadiness={setReadiness} getGrowthStatus={getGrowthStatus} />
          ))}
        </div>
      </div>
    )
  }

  // ── 左面板：状态 ──
  const renderStatus = () => {
    if (!babyStatus) {
      // API 未加载完 或 已入篮但 status 还没加载完：显示加载中
      if (!initialLoaded || isInCradle(selectedId)) {
        return (
          <div className="flex flex-col items-center justify-center flex-1 gap-4 p-6">
            <span className="text-sm text-muted-foreground animate-pulse">{isZh ? '加载中...' : 'Loading...'}</span>
          </div>
        )
      }
      if (selectedBirth) {
        return (
          <div className="flex flex-col items-center justify-center flex-1 gap-4 p-6">
            <span className="text-sm text-muted-foreground">
              {isZh ? '等待放入摇篮' : 'Awaiting admission'}
            </span>
          </div>
        )
      }
      return null
    }

    const s = babyStatus
    const phase = s.current_phase || {}

    return (
      <div className="flex flex-col gap-3.5 w-full">
        {/* 阶段进度 — 居中时间线 */}
        <Card className="h-[500px] flex flex-col border border-border !py-0 overflow-hidden">
          <div className="shrink-0 border-b border-border py-2 px-4 bg-muted/50">
            <div className="flex items-center justify-center gap-3 text-[10px] text-muted-foreground">
              <span className="font-semibold tracking-wide uppercase">{isZh ? '阶段' : 'Phases'}: {phase.index ?? 0} / {PHASES_DATA.length}</span>
              <span className="text-border">/</span>
              <span>{babyStatus?.age_days ?? 0} {isZh ? '天' : 'days'}</span>
            </div>
          </div>
          <CardContent className="p-4 flex-1 overflow-y-auto">
            <div className="relative mx-auto w-full">
              {/* 居中竖线 */}
              <div className="absolute left-1/2 top-0 bottom-0 w-px bg-border -translate-x-px" />

              {PHASES_DATA.map((pd, i) => {
                const isCurrent = i === phase.index
                const isDone = i < phase.index
                const isLeft = i % 2 === 0
                // 优先 SSE 实时总结，再 history API 总结，最后 fallback 静态描述
                const logSummary = state.logs.find(l => l.event === 'phase_completed' && l.data.phase_index === i)
                const rawSum = logSummary ? logSummary.data.summary : null
                const sseSummary = rawSum ? (typeof rawSum === 'object' ? rawSum?.summary : rawSum) : null
                const rawSummary = sseSummary || phaseSummaries[i]
                const summary = rawSummary && typeof rawSummary === 'object' ? rawSummary.summary : rawSummary
                const desc = isZh ? pd.desc_zh : pd.desc_en

                // 当前阶段卡片：根据宝宝活跃需求动态变色
                const need = isCurrent ? state.activeNeed : null
                const needBorder = need ? {
                  physiological: 'animate-glow-red',
                  emotional: 'animate-glow-amber',
                  social: 'animate-glow-blue',
                }[need.urgency] || 'border-primary/30' : null
                const needDot = need ? {
                  physiological: 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.6)]',
                  emotional: 'bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.6)]',
                  social: 'bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.6)]',
                }[need.urgency] || null : null

                return (
                  <div key={pd.name} ref={isCurrent ? currentPhaseRef : null} className={cn("relative flex items-start", isLeft ? "justify-start" : "justify-end")}>
                    {/* 中间节点 */}
                    <div className={cn(
                      "absolute left-1/2 top-3.5 w-2.5 h-2.5 rounded-full -translate-x-1/2 z-[2]",
                      isDone && "bg-primary",
                      isCurrent && !needDot && "bg-primary shadow-[0_0_8px_rgba(213,147,55,0.6)] animate-pulse",
                      isCurrent && needDot && cn(needDot, "animate-pulse"),
                      !isDone && !isCurrent && "bg-border",
                    )} />

                    {/* 卡片 — 边框颜色随宝宝需求变化 */}
                    <div className={cn(
                      "w-[calc(50%-16px)] mb-3 rounded-xl border p-3 transition-all duration-500",
                      isCurrent && !need && "bg-card border-primary/30 shadow-sm",
                      isCurrent && need && cn("bg-card", needBorder),
                      isDone && "bg-card border-border",
                      !isDone && !isCurrent && "bg-card/50 border-border/50 opacity-50",
                    )}>
                      {/* 头部 */}
                      <div className="flex items-center gap-2">
                        <span className={cn(
                          "w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold shrink-0",
                          isDone && "bg-primary/15 text-primary",
                          isCurrent && "bg-primary text-primary-foreground",
                          !isDone && !isCurrent && "bg-muted text-muted-foreground",
                        )}>{i + 1}</span>
                        <span className={cn(
                          "text-[13px] font-semibold capitalize flex-1 min-w-0 truncate",
                          (isCurrent || isDone) ? "text-foreground" : "text-muted-foreground",
                        )}>{tk(pd.name)}</span>
                        {(isDone || isCurrent) && (
                          <span className={cn(
                            "text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded shrink-0",
                            isDone ? "bg-green-500/10 text-green-500" : "bg-primary/20 text-primary",
                          )}>
                            {isDone ? (isZh ? '完成' : 'DONE')
                              : state.simDay != null
                                ? (isZh ? `第${state.simDay}天` : `D${state.simDay}`)
                                : (isZh ? '进行中' : 'NOW')}
                          </span>
                        )}
                      </div>

                      {/* 内容 — 需求/实时状态/阶段描述 三态切换 */}
                      <div className="text-[11px] text-muted-foreground mt-2 leading-relaxed max-h-[300px] overflow-y-auto no-scrollbar">
                        {need ? (
                          /* 活跃需求 */
                          <div>
                            <div className={cn("text-xs font-medium", {
                              'text-red-400': need.urgency === 'physiological',
                              'text-amber-400': need.urgency === 'emotional',
                              'text-blue-400': need.urgency === 'social',
                            })}>
                              {need.trigger_label || need.parent_hint || need.trigger}
                            </div>
                            {need.signal && (
                              <div className="text-[10px] text-muted-foreground mt-0.5">{need.signal}</div>
                            )}
                            {need.expression && (
                              <div className="text-[10px] text-muted-foreground/70 mt-0.5 italic">{typeof need.expression === 'string' ? need.expression : need.expression?.vocalization || ''}</div>
                            )}
                          </div>
                        ) : isCurrent ? (
                          /* 当前阶段：实时世界 + 环境 + 家庭 + 宝宝状态 */
                          <div className="flex flex-col gap-1.5">
                            {/* 世界快照：天气 / 家庭弧线 */}
                            {state.worldSnapshot && (
                              <div className="text-[10px]">
                                {state.worldSnapshot.weather && <span className="text-indigo-400">{state.worldSnapshot.weather}</span>}
                                {state.worldSnapshot.family_arc && <span className="text-teal-400 ml-1">· {state.worldSnapshot.family_arc}</span>}
                              </div>
                            )}
                            {/* 家庭成员 */}
                            {s.caregivers && Object.keys(s.caregivers).length > 0 && (
                              <div className="flex items-center gap-1.5 text-[10px]">
                                <span className="text-muted-foreground/60">{isZh ? '家庭' : 'Family'}:</span>
                                {Object.entries(s.caregivers).map(([name, info]) => (
                                  <span key={name} className="text-foreground/80 capitalize">{name}{info?.role ? `(${info.role})` : ''}</span>
                                ))}
                              </div>
                            )}
                            {/* 宝宝最新状态 */}
                            <div className="flex items-center gap-2 text-[10px] flex-wrap">
                              {s.expression_mode && <span className="text-primary/80 capitalize">{tk(s.expression_mode)}</span>}
                              {s.attachment_style && <span className={cn("capitalize", {
                                'text-green-400': s.attachment_style === 'secure',
                                'text-yellow-400': s.attachment_style === 'anxious',
                                'text-red-400': s.attachment_style === 'avoidant',
                                'text-muted-foreground/70': !['secure', 'anxious', 'avoidant'].includes(s.attachment_style),
                              })}>{tk(s.attachment_style)}</span>}
                              {s.stress?.stress_level != null && (
                                <span className={cn(
                                  s.stress.stress_level < 0.3 ? 'text-green-400' : s.stress.stress_level < 0.6 ? 'text-yellow-400' : 'text-red-400',
                                )}>{isZh ? '压力' : 'Stress'} {(s.stress.stress_level * 100).toFixed(0)}%</span>
                              )}
                            </div>
                            {/* 最新活动 */}
                            {state.lastActivity && (
                              <div className="text-[10px] text-muted-foreground/60 truncate">
                                {state.lastActivity}
                              </div>
                            )}
                            {/* 无快照无标签时 fallback */}
                            {!state.worldSnapshot && !s.caregivers && !state.lastActivity && (
                              <div className="text-muted-foreground/60">{summary || desc}</div>
                            )}
                          </div>
                        ) : (
                          /* 非当前阶段：静态描述 */
                          <div>
                            <span className="text-muted-foreground/60">{pd.age}</span>
                            <div className="mt-1">{summary || desc}</div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>

        {/* 身份特质 */}
        <Card>
          <CardHeader><CardTitle>{isZh ? '身份特质' : 'Identity'}</CardTitle></CardHeader>
          <CardContent>
            <div className="bg-muted rounded-2xl p-4">
              <div className="flex flex-col divide-y divide-border text-sm">
                {[
                  [isZh ? '阶段' : 'Phase', <span className="capitalize">{tk(phase.name || '')}</span>],
                  [isZh ? '日龄' : 'Age', (() => {
                    const days = s.age_days || 0
                    const y = Math.floor(days / 365)
                    const m = Math.floor((days % 365) / 30)
                    const d = days % 30
                    const parts = []
                    if (y > 0) parts.push(`${y}${isZh ? '岁' : 'y'}`)
                    if (m > 0) parts.push(`${m}${isZh ? '个月' : 'mo'}`)
                    if (d > 0 || parts.length === 0) parts.push(`${d}${isZh ? '天' : 'd'}`)
                    return `${days}${isZh ? '天' : 'd'}（${parts.join('')}）`
                  })()],
                  [isZh ? '表达' : 'Expression', <span className="capitalize">{tk(s.expression_mode || '')}</span>],
                  [isZh ? '依恋' : 'Attachment', <span className={cn("capitalize",
                    s.attachment_style === 'secure' && "text-green-500",
                    s.attachment_style === 'anxious' && "text-yellow-500",
                    s.attachment_style === 'avoidant' && "text-red-500",
                  )}>{tk(s.attachment_style || 'forming')}</span>],
                ].map(([label, val], i) => (
                  <div key={i} className="flex justify-between py-2.5 first:pt-0 last:pb-0">
                    <span className="text-muted-foreground">{label}</span>
                    <span className="font-medium">{val}</span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* 能力 */}
        {s.capabilities?.length > 0 && (
          <Card>
            <CardHeader><CardTitle>{isZh ? '已解锁能力' : 'Capabilities'}</CardTitle></CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-1.5">
                {s.capabilities.map((cap, i) => (
                  <span key={i} className="text-xs px-2 py-1 bg-primary/10 text-primary rounded-full capitalize">
                    {tk(cap.replace(/_/g, ' '))}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* 里程碑 */}
        {s.milestones?.length > 0 && (
          <Card>
            <CardHeader><CardTitle>{isZh ? '里程碑' : 'Milestones'}</CardTitle></CardHeader>
            <CardContent>
              <div className="flex flex-col gap-1.5">
                {s.milestones.map((m, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className="text-primary">{'\u2605'}</span>
                    <span className="capitalize">{tk(m.description || m.name?.replace(/_/g, ' ') || '')}</span>
                    <span className="text-xs text-muted-foreground ml-auto">
                      {isZh ? '第' : 'Day '}{m.age_days}{isZh ? '天' : ''}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* 心理画像 */}
        {(s.fears?.length > 0 || s.preferences?.length > 0 || s.comfort_sources?.length > 0) && (
          <Card>
            <CardHeader><CardTitle>{isZh ? '心理画像' : 'Psychology'}</CardTitle></CardHeader>
            <CardContent>
              <div className="flex flex-col gap-3">
                {s.fears?.length > 0 && (
                  <div>
                    <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">{isZh ? '恐惧' : 'FEARS'}</div>
                    <div className="flex flex-wrap gap-1.5">
                      {s.fears.map((f, i) => <span key={i} className="text-xs px-2 py-1 bg-red-500/10 text-red-400 rounded-full">{f}</span>)}
                    </div>
                  </div>
                )}
                {s.preferences?.length > 0 && (
                  <div>
                    <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">{isZh ? '偏好' : 'PREFERENCES'}</div>
                    <div className="flex flex-wrap gap-1.5">
                      {s.preferences.map((p, i) => <span key={i} className="text-xs px-2 py-1 bg-blue-500/10 text-blue-400 rounded-full">{p}</span>)}
                    </div>
                  </div>
                )}
                {s.comfort_sources?.length > 0 && (
                  <div>
                    <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">{isZh ? '安慰来源' : 'COMFORT'}</div>
                    <div className="flex flex-wrap gap-1.5">
                      {s.comfort_sources.map((c, i) => <span key={i} className="text-xs px-2 py-1 bg-green-500/10 text-green-400 rounded-full">{c}</span>)}
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* 体征 & 压力 */}
        {(s.physical || s.stress) && (
          <Card>
            <CardHeader><CardTitle>{isZh ? '体征状态' : 'Vitals'}</CardTitle></CardHeader>
            <CardContent>
              <div className="bg-muted rounded-2xl p-4 flex flex-col gap-3">
                {/* 身高/体重/牙数 */}
                {s.physical && (
                  <div className="flex items-center gap-3 text-sm">
                    {s.physical.height_cm != null && (
                      <span className="text-muted-foreground">{isZh ? '身高' : 'H'} <span className="text-foreground font-medium">{s.physical.height_cm}cm</span></span>
                    )}
                    {s.physical.weight_kg != null && (
                      <span className="text-muted-foreground">{isZh ? '体重' : 'W'} <span className="text-foreground font-medium">{s.physical.weight_kg}kg</span></span>
                    )}
                    {s.physical.teeth_count != null && (
                      <span className="text-muted-foreground">{isZh ? '牙齿' : 'Teeth'} <span className="text-foreground font-medium">{s.physical.teeth_count}</span></span>
                    )}
                  </div>
                )}
                {/* 压力值条 */}
                {s.stress && s.stress.stress_level != null && (
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-muted-foreground">{isZh ? '压力值' : 'Stress'}</span>
                      <span className={cn(
                        "font-medium",
                        s.stress.stress_level < 0.3 ? "text-green-400" : s.stress.stress_level < 0.6 ? "text-yellow-400" : "text-red-400",
                      )}>{(s.stress.stress_level * 100).toFixed(0)}%</span>
                    </div>
                    <div className="h-1.5 bg-border rounded-full overflow-hidden">
                      <div
                        className={cn("h-full rounded-full transition-all duration-500",
                          s.stress.stress_level < 0.3 ? "bg-green-400" : s.stress.stress_level < 0.6 ? "bg-yellow-400" : "bg-red-400",
                        )}
                        style={{ width: `${Math.min(s.stress.stress_level * 100, 100)}%` }}
                      />
                    </div>
                    {s.stress.regressed_capabilities?.length > 0 && (
                      <div className="text-[10px] text-yellow-400/80 mt-1">
                        {isZh ? '回退' : 'Regressed'}: {s.stress.regressed_capabilities.map(r => tk(String(r).replace(/_/g, ' '))).join(', ')}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* 喂养 & 睡眠 */}
        {s.nutrition_sleep && (
          <Card>
            <CardHeader><CardTitle>{isZh ? '喂养与睡眠' : 'Nutrition & Sleep'}</CardTitle></CardHeader>
            <CardContent>
              <div className="bg-muted rounded-2xl p-4">
                <div className="flex flex-col divide-y divide-border text-sm">
                  {[
                    s.nutrition_sleep.feeding_mode && [isZh ? '喂养' : 'Feeding', <span className="capitalize">{tk(String(s.nutrition_sleep.feeding_mode).replace(/_/g, ' '))}</span>],
                    s.nutrition_sleep.sleep_quality != null && [isZh ? '睡眠质量' : 'Sleep', <span>{(s.nutrition_sleep.sleep_quality * 100).toFixed(0)}%</span>],
                    s.nutrition_sleep.sleep_regression_active != null && [
                      isZh ? '回归期' : 'Regression',
                      s.nutrition_sleep.sleep_regression_active
                        ? <span className="text-yellow-400 flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />{isZh ? '活跃' : 'Active'}</span>
                        : <span className="text-green-400">{isZh ? '无' : 'None'}</span>,
                    ],
                    s.nutrition_sleep.night_waking_frequency != null && [isZh ? '夜醒' : 'Night Wakes', `${s.nutrition_sleep.night_waking_frequency}${isZh ? '次/夜' : '/night'}`],
                    s.nutrition_sleep.transitional_object && [isZh ? '安抚物' : 'Comfort Object', s.nutrition_sleep.transitional_object],
                  ].filter(Boolean).map(([label, val], i) => (
                    <div key={i} className="flex justify-between py-2.5 first:pt-0 last:pb-0">
                      <span className="text-muted-foreground">{label}</span>
                      <span className="font-medium">{val}</span>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* 情绪发展 */}
        {s.emotional && (
          <Card>
            <CardHeader><CardTitle>{isZh ? '情绪发展' : 'Emotional'}</CardTitle></CardHeader>
            <CardContent>
              <div className="bg-muted rounded-2xl p-4">
                <div className="flex flex-col divide-y divide-border text-sm">
                  {[
                    s.emotional.empathy_level && [isZh ? '共情' : 'Empathy', <span className="font-medium capitalize">{tk(String(s.emotional.empathy_level))}</span>],
                    s.emotional.tantrum_frequency != null && [isZh ? '脾气频率' : 'Tantrums', <span className={cn("font-medium", s.emotional.tantrum_frequency > 0.5 ? "text-yellow-400" : "text-green-400")}>{(s.emotional.tantrum_frequency * 100).toFixed(0)}%</span>],
                    Array.isArray(s.emotional.emotional_vocabulary) && s.emotional.emotional_vocabulary.length > 0 && [isZh ? '情绪词汇' : 'Vocabulary', <span>{s.emotional.emotional_vocabulary.length}{isZh ? '个' : ''}</span>],
                    s.emotional.play_type && [isZh ? '游戏类型' : 'Play', <span className="capitalize">{tk(String(s.emotional.play_type).replace(/_/g, ' '))}</span>],
                    s.emotional.imaginary_friend && [isZh ? '想象朋友' : 'Imaginary Friend', s.emotional.imaginary_friend],
                  ].filter(Boolean).map(([label, val], i) => (
                    <div key={i} className="flex justify-between py-2.5 first:pt-0 last:pb-0">
                      <span className="text-muted-foreground">{label}</span>
                      <span className="font-medium">{val}</span>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* 照护者 */}
        {s.caregivers && Object.keys(s.caregivers).length > 0 && (
          <Card>
            <CardHeader><CardTitle>{isZh ? '照护者' : 'Caregivers'}</CardTitle></CardHeader>
            <CardContent>
              <div className="flex flex-col gap-2">
                {Object.entries(s.caregivers).map(([name, info]) => {
                  const att = s.attachment_per_caregiver?.[name]
                  return (
                    <div key={name} className="bg-muted rounded-xl p-3 flex items-center gap-3">
                      <Avatar size="sm">
                        <AvatarFallback className="text-[9px]">{name[0]?.toUpperCase()}</AvatarFallback>
                      </Avatar>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium capitalize">{name}</div>
                        {typeof info === 'object' && info.role && (
                          <div className="text-[10px] text-muted-foreground capitalize">{info.role}</div>
                        )}
                      </div>
                      {att && (
                        <span className={cn(
                          "text-[10px] px-1.5 py-0.5 rounded-full capitalize",
                          att === 'secure' || att?.style === 'secure' ? "bg-green-500/10 text-green-400" :
                          att === 'anxious' || att?.style === 'anxious' ? "bg-yellow-500/10 text-yellow-400" :
                          "bg-muted-foreground/10 text-muted-foreground",
                        )}>
                          {tk(typeof att === 'string' ? att : att?.style || 'forming')}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* 世界就绪度 */}
      </div>
    )
  }

  // ── 日志渲染 ──
  const renderLog = (entry, i) => {
    const { time, event, data } = entry

    if (event === 'phase_start') {
      return (
        <div key={i} className="log-stage-start">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '阶段' : 'PHASE'} {data.phase_index + 1}/${PHASES_DATA.length}</span>
          <span className="capitalize">{tk(data.phase_name)}</span>
          <span className="text-[#666] ml-1">({data.age_range})</span>
        </div>
      )
    }

    if (event === 'fate_weaving') {
      const selected = (data.traces || []).filter(t => t.selected)
      return (
        <div key={i} className="log-fate">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '命运编织' : 'FATE'}</span>
          <span className="text-[#aaa]">
            {selected.map(t => tk(t.event_name?.replace(/_/g, ' ') || '')).join(' · ') || (isZh ? '掷骰中...' : 'Rolling...')}
          </span>
        </div>
      )
    }

    if (event === 'environment_perceiving') {
      return (
        <div key={i} className="log-env">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '感知' : 'SENSE'}</span>
          <span className="capitalize">{tk(data.event_name?.replace(/_/g, ' ') || '')}</span>
          <span className="text-[#666] ml-1">
            {data.dominant_channel} {(data.total_perceived_intensity * 100).toFixed(0)}%
          </span>
        </div>
      )
    }

    if (event === 'narrating') {
      return (
        <div key={i} className="log-maternal">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '叙事' : 'NARRATE'}</span>
          {data.message || (isZh ? '生活展开中' : 'Unfolding')}{data.elapsed ? ` ${data.elapsed}s` : '...'}
        </div>
      )
    }

    if (event === 'nanny_caring') {
      return (
        <div key={i} className="log-maternal">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '保姆' : 'NANNY'}</span>
          {data.message || (isZh ? '照料中...' : 'Caring...')}
        </div>
      )
    }

    if (event === 'nanny_action') {
      return (
        <div key={i} className="log-stage-done">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '照料' : 'CARE'}</span>
          <span className="capitalize">{tk(data.event_name?.replace(/_/g, ' ') || '')}</span>
          {data.baby_reaction && <span className="cradle-reaction"> {data.baby_reaction}</span>}
        </div>
      )
    }

    if (event === 'environment_thinking') {
      return (
        <div key={i} className="log-maternal">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '思考' : 'THINK'}</span>
          {data.message || (isZh ? '处理环境刺激...' : 'Processing...')}
        </div>
      )
    }

    if (event === 'environment_reaction') {
      return (
        <div key={i} className="log-stage-done">
          <span className="time">{time}</span>
          <span className="tag">{tk(data.event_name?.replace(/_/g, ' ') || '')}</span>
          <span className="cradle-reaction"> {data.reaction}</span>
          {data.growth_signal && <span className="text-[10px] text-primary/60 ml-1">{data.growth_signal}</span>}
          {data.new_fear && <span className="text-[10px] text-red-400/80 ml-1">{isZh ? '新恐惧' : 'New fear'}: {data.new_fear}</span>}
          {data.new_preference && <span className="text-[10px] text-blue-400/80 ml-1">{isZh ? '新偏好' : 'New pref'}: {data.new_preference}</span>}
        </div>
      )
    }

    if (event === 'critical_event') {
      return (
        <div key={i} className="log-error">
          <span className="time">{time}</span>
          <span className="tag">{data.auto_resolved ? (isZh ? '自动' : 'AUTO') : (isZh ? '关键' : 'CRITICAL')}</span>
          <span className="font-medium">{tk(data.event_display || data.event_name?.replace(/_/g, ' ') || '')}</span>
          {data.auto_resolved && data.name
            ? <span className="text-emerald-400 ml-1">{data.name}</span>
            : <span className="text-[#aaa] text-[11px] ml-1">{typeof data.description === 'object' ? (data.description.name || JSON.stringify(data.description)) : data.description}</span>
          }
        </div>
      )
    }

    if (event === 'critical_expired') {
      return (
        <div key={i} className="log-error" style={{ opacity: 0.7 }}>
          <span className="time">{time}</span>
          <span className="tag" style={{ background: '#78716c' }}>{isZh ? '已错过' : 'MISSED'}</span>
          <span className="font-medium">{tk(data.event_display || data.event_name?.replace(/_/g, ' ') || '')}</span>
          <span className="text-[#aaa] text-[11px] ml-1">
            {isZh
              ? `${data.expired_after_days} 天未回应，已自动处理`
              : `Auto-resolved after ${data.expired_after_days} days`}
          </span>
        </div>
      )
    }

    if (event === 'capabilities_unlocked') {
      return (
        <div key={i} className="log-born">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '解锁' : 'UNLOCK'}</span>
          {(data.capabilities || []).map(c => tk(c.replace(/_/g, ' '))).join(', ')}
        </div>
      )
    }

    if (event === 'milestones') {
      return (
        <div key={i} className="log-complete">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '里程碑' : 'MILESTONE'}</span>
          {(data.milestones || []).map(m => tk(m.description || m.name?.replace(/_/g, ' ') || '')).join(', ')}
        </div>
      )
    }

    if (event === 'phase_simulated') {
      return (
        <div key={i} className="log-system">
          <span className="time">{time}</span>
          {isZh ? '阶段模拟完成' : 'Phase simulated'}
          {data.critical_count > 0 && (
            <span className="text-yellow-400 ml-1">
              ({data.critical_count} {isZh ? '个关键事件待处理' : 'critical event(s) pending'})
            </span>
          )}
        </div>
      )
    }

    if (event === 'phase_completing') {
      return (
        <div key={i} className="log-maternal">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '总结' : 'SUMMARY'}</span>
          {data.message || (isZh ? '生成阶段总结' : 'Generating summary')}{data.elapsed ? ` ${data.elapsed}s` : '...'}
        </div>
      )
    }

    if (event === 'phase_completed') {
      const summary = data.summary
      return (
        <div key={i} className="log-complete">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '完成' : 'DONE'}</span>
          {tk(data.phase_display || data.phase_name || '')}
          {summary && typeof summary === 'object' && summary.summary && (
            <span className="cradle-reaction"> {summary.summary}</span>
          )}
          {data.next_phase && (
            <div className="text-[11px] text-primary mt-1">{isZh ? '下一阶段' : 'Next'}: {tk(data.next_phase || data.next_phase_name || '')}</div>
          )}
        </div>
      )
    }

    if (event === 'day_summary') {
      const days = data.days || 1
      return (
        <div key={i} className="log-routine" style={{ opacity: 0.85 }}>
          <span className="time">{time}</span>
          <span className="tag" style={{ color: '#888' }}>{isZh ? `第${data.from_day}-${data.to_day}天` : `Day ${data.from_day}-${data.to_day}`}</span>
          <span style={{ color: '#999' }}>{isZh ? `平静的${days}天，规律的吃睡循环` : `${days} quiet days of routine`}</span>
        </div>
      )
    }

    if (event === 'life_complete' || event === 'cradle_complete') {
      return (
        <div key={i} className="log-complete">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '摇篮完成' : 'CRADLE COMPLETE'}</span>
          {isZh ? '摇篮阶段结束，准备进入世界' : 'Cradle phases completed, ready to enter the world'}
        </div>
      )
    }

    if (event === 'growth_complete') {
      return (
        <div key={i} className="log-complete">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '成长完成' : 'GROWN'}</span>
          {data.name || data.baby_id} — {data.total_milestones} {isZh ? '个里程碑' : 'milestones'} · {tk(data.attachment_style)}
        </div>
      )
    }

    if (event === 'intervene_result') {
      return (
        <div key={i} className="log-maternal">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '回应' : 'RESPONSE'}</span>
          <span className="cradle-reaction"> {data.reaction || data.parent_response_reaction || ''}</span>
          {data.developmental_impact && <span className="text-[10px] text-primary/60 ml-1">{data.developmental_impact}</span>}
        </div>
      )
    }

    if (event === 'interaction_pending') {
      return (
        <div key={i} className="log-fate">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '互动' : 'INTERACT'}</span>
          <span className="text-[#999]">{data.parent_message}</span>
          <span className="text-[#666]"> → </span>
          <span className="text-[#999] animate-pulse">{isZh ? '等待回应...' : 'Awaiting...'}</span>
        </div>
      )
    }

    if (event === 'interaction') {
      const sc = data.state_changes
      return (
        <div key={i} className="log-fate">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '互动' : 'INTERACT'}</span>
          <span className="text-[#999]">{data.parent_message}</span>
          <span className="text-[#666]"> → </span>
          <span className="text-[#ccc] italic">{data.baby_response}</span>
          {data.emotional_tone && <span className="text-[#666]"> [{data.emotional_tone}]</span>}
          {sc && Object.keys(sc).length > 0 && (
            <span className="text-[10px] ml-1">
              {sc.new_preference && <span className="text-green-400">+{isZh ? '偏好' : 'pref'}: {sc.new_preference} </span>}
              {sc.new_comfort_source && <span className="text-blue-400">+{isZh ? '安慰' : 'comfort'}: {sc.new_comfort_source} </span>}
              {sc.fear_reduced && <span className="text-green-400">-{isZh ? '恐惧' : 'fear'}: {sc.fear_reduced} </span>}
              {sc.new_fear && <span className="text-red-400">+{isZh ? '恐惧' : 'fear'}: {sc.new_fear} </span>}
            </span>
          )}
        </div>
      )
    }

    // 会话消息薄索引（新路径 conversation_message）
    if (event === 'conversation_message') {
      const roleLabel = data.role === 'parent'
        ? (isZh ? '家长' : 'Parent')
        : (data.role === 'baby' ? (data.name || (isZh ? '宝宝' : 'Baby')) : '')
      const icon = data.role === 'parent' ? '▸' : '◂'
      const subtypeTag = data.subtype === 'need' ? (isZh ? ' [需求]' : ' [need]') : ''
      return (
        <div key={i} className="log-fate">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '对话' : 'CHAT'}</span>
          <span className="text-[#888]">{icon} {roleLabel}{subtypeTag}</span>
          <span className="text-[#aaa] italic ml-1">{data.summary || ''}</span>
          {data.conv_id && <span className="text-[#555] text-[10px] ml-1">[{data.conv_id}]</span>}
        </div>
      )
    }

    // sim_tick 不渲染为日志条目——由尾部"生命在自然生长中..."指示器统一表达
    if (event === 'sim_tick') return null

    if (event === 'loading') {
      return (
        <div key={i} className="log-stage-start">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '入篮' : 'ADMIT'}</span>
          {isZh ? `加载婴儿数据 ${data.baby_id}...` : `Loading baby ${data.baby_id}...`}
        </div>
      )
    }
    if (event === 'extracting') {
      return (
        <div key={i} className="log-stage-start">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '提取' : 'EXTRACT'}</span>
          {isZh
            ? `感官画像已提取 | 唤醒基线: ${data.arousal_baseline} | 反射: ${data.reflex_count} | 本能: ${data.instinct_count}`
            : `Sensory profile extracted | Arousal: ${data.arousal_baseline} | Reflexes: ${data.reflex_count} | Instincts: ${data.instinct_count}`}
        </div>
      )
    }
    if (event === 'compiling') {
      return (
        <div key={i} className="log-stage-start">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '编译' : 'COMPILE'}</span>
          {isZh ? '正在编译行为约束（LLM）' : 'Compiling behavioral constraints (LLM)'}{data.elapsed ? ` ${data.elapsed}s` : '...'}
        </div>
      )
    }
    if (event === 'constraints_ready') {
      return (
        <div key={i} className="log-stage-start">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '约束' : 'CONSTRAINTS'}</span>
          {isZh ? `${data.count} 条行为约束已编译` : `${data.count} behavioral constraints compiled`}
        </div>
      )
    }
    if (event === 'assembling') {
      return (
        <div key={i} className="log-stage-start">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '组装' : 'ASSEMBLE'}</span>
          {isZh ? '正在组装身份和生成环境...' : 'Assembling identity and rolling environment...'}
        </div>
      )
    }
    if (event === 'admitted') {
      return (
        <div key={i} className="log-stage-start" style={{ color: 'var(--primary)' }}>
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '就绪' : 'READY'}</span>
          {isZh ? `${data.baby_id} 已投入摇篮` : `${data.baby_id} admitted to cradle`}
          {data.environment?.length > 0 && (
            <span className="text-[11px] text-[#888] ml-1">
              [{data.environment.map(t => tk(t.replace(/_/g, ' '))).join(' · ')}]
            </span>
          )}
        </div>
      )
    }

    if (event === 'lifeline_connecting') {
      return (
        <div key={i} className="log-maternal">
          <span className="time">{time}</span>
          <span className="tag" style={{ color: '#34d399' }}>{isZh ? '生命线' : 'LIFELINE'}</span>
          <span className="text-emerald-400/50 animate-pulse">
            {isZh ? '正在连接自主生命流...' : 'Connecting life stream...'}
          </span>
        </div>
      )
    }

    if (event === 'phase_state_update') {
      const icons = { feeding_transition: '🍼', physical_growth: '📏', new_teeth: '🦷', sleep_regression_onset: '😴', sleep_regression_resolved: '😊' }
      const labels = {
        feeding_transition: isZh ? '喂养转变' : 'Feeding',
        physical_growth: isZh ? '体格发育' : 'Growth',
        new_teeth: isZh ? '出牙' : 'Teething',
        sleep_regression_onset: isZh ? '睡眠回归期' : 'Sleep Regression',
        sleep_regression_resolved: isZh ? '睡眠恢复' : 'Sleep Recovered',
      }
      return (
        <div key={i} className="log-stage-done">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '状态' : 'STATE'}</span>
          {(data.changes || []).map((c, j) => (
            <span key={j} className="text-[11px]">
              {icons[c.type] || '•'} {labels[c.type] || c.type}
              {c.type === 'feeding_transition' && <span className="text-[#888]"> {c.from} → {c.to}</span>}
              {c.type === 'physical_growth' && <span className="text-[#888]"> {c.height_cm}cm / {c.weight_kg}kg</span>}
              {c.type === 'new_teeth' && <span className="text-[#888]"> +{c.count} ({isZh ? '共' : 'total'} {c.total})</span>}
            </span>
          ))}
        </div>
      )
    }

    if (event === 'stress_regression') {
      return (
        <div key={i} className="log-error" style={{ borderLeftColor: '#f59e0b' }}>
          <span className="time">{time}</span>
          <span className="tag" style={{ color: '#f59e0b' }}>{isZh ? '压力回退' : 'REGRESS'}</span>
          <span className="text-yellow-400">{isZh ? '压力' : 'Stress'}: {(data.stress_level * 100).toFixed(0)}%</span>
          {data.regressed?.length > 0 && (
            <span className="text-[11px] text-yellow-400/80 ml-1">
              {isZh ? '能力回退' : 'Regressed'}: {data.regressed.map(r => tk(r.replace(/_/g, ' '))).join(', ')}
            </span>
          )}
        </div>
      )
    }

    if (event === 'regression_recovery') {
      return (
        <div key={i} className="log-born">
          <span className="time">{time}</span>
          <span className="tag" style={{ color: '#22c55e' }}>{isZh ? '恢复' : 'RECOVER'}</span>
          <span className="text-green-400">{isZh ? '压力' : 'Stress'}: {(data.stress_level * 100).toFixed(0)}%</span>
          {data.recovered?.length > 0 && (
            <span className="text-[11px] text-green-400/80 ml-1">
              {isZh ? '已恢复' : 'Recovered'}: {data.recovered.map(r => tk(r.replace(/_/g, ' '))).join(', ')}
            </span>
          )}
          {data.strengthened?.length > 0 && (
            <span className="text-[11px] text-green-400 ml-1">
              {data.strengthened.map(s => `★ ${tk(s.replace(/_/g, ' '))}`).join('  ')}
              <span className="text-[10px] text-green-400/60 ml-1">({isZh ? '韧性强化' : 'strengthened'})</span>
            </span>
          )}
        </div>
      )
    }

    if (event === 'lifeline_ready') {
      return (
        <div key={i} className="log-system">
          <span className="time">{time}</span>
          <span className="tag" style={{ color: '#34d399' }}>{isZh ? '生命线' : 'LIFELINE'}</span>
          <span className="text-emerald-400/70">
            {isZh
              ? `自主生命已启动 · 第${data.sim_day ?? 0}天 · 队列 ${data.queue_size ?? 0} 事件`
              : `Life active · D${data.sim_day ?? 0} · ${data.queue_size ?? 0} events queued`}
          </span>
        </div>
      )
    }

    if (event === 'autonomous_processing') {
      const simDate = data.sim_day != null ? (isZh ? `第${data.sim_day}天` : `D${data.sim_day}`) : ''
      const simTime = data.sim_hour != null
        ? `${Math.floor(data.sim_hour)}:${String(Math.round((data.sim_hour % 1) * 60)).padStart(2, '0')}`
        : ''
      return (
        <div key={i} className="log-system">
          <span className="time">{time}</span>
          {(simDate || simTime) && (
            <span className="text-[10px] text-emerald-400/80 mr-1.5">{simDate}{simTime ? ` ${simTime}` : ''}</span>
          )}
          <span className="text-[#ccc]">
            <span className="inline-block w-1.5 h-1.5 rounded-full step-dot-running mr-1.5 align-middle" />
            {tk(data.display_name?.replace(/_/g, ' ') || data.event_name || '')}...
          </span>
        </div>
      )
    }

    if (event === 'autonomous_routine') {
      // 日常活动：浅灰简短行
      const simTime = data.sim_hour != null
        ? `${Math.floor(data.sim_hour)}:${String(Math.round((data.sim_hour % 1) * 60)).padStart(2, '0')}`
        : ''
      const simDate = data.age_days != null
        ? (isZh ? `第${data.age_days}天` : `D${data.age_days}`)
        : ''
      return (
        <div key={i} className="log-system">
          <span className="time">{time}</span>
          {(simDate || simTime) && (
            <span className="text-[10px] text-emerald-400/80 mr-1.5">{simDate}{simTime ? ` ${simTime}` : ''}</span>
          )}
          <span className="text-[#ccc] font-medium">{tk(data.display_name?.replace(/_/g, ' ') || data.event_name || '')}</span>
          {data.summary && <span className="text-[#999] ml-1">{data.summary}</span>}
          {data.changes && Object.keys(data.changes).length > 0 && (
            <span className="text-[10px] text-[#888] ml-1">
              {Object.entries(data.changes).map(([k, v]) => `${k}: ${typeof v === 'number' ? (v > 0 ? '+' : '') + v.toFixed(2) : v}`).join(' ')}
            </span>
          )}
        </div>
      )
    }

    if (event === 'autonomous_event') {
      const simTime = data.sim_hour != null
        ? `${Math.floor(data.sim_hour)}:${String(Math.round((data.sim_hour % 1) * 60)).padStart(2, '0')}`
        : ''
      const simDate = data.age_days != null
        ? (isZh ? `第${data.age_days}天` : `D${data.age_days}`)
        : ''
      return (
        <div key={i} className="log-stage-done">
          <span className="time">{time}</span>
          {(simDate || simTime) && (
            <span className="text-[10px] text-emerald-400/60 mr-1.5">{simDate}{simTime ? ` ${simTime}` : ''}</span>
          )}
          <span className="tag" style={{ color: '#a78bfa' }}>{tk(data.display_name?.replace(/_/g, ' ') || data.event_name || '')}</span>
          {data.summary && <span className="text-[#ccc] italic ml-1">{data.summary}</span>}
          {data.changes && (
            <span className="text-[10px] ml-1">
              {data.changes.new_preference && <span className="text-green-400">+{isZh ? '偏好' : 'pref'}: {data.changes.new_preference} </span>}
              {data.changes.new_fear && <span className="text-red-400">+{isZh ? '恐惧' : 'fear'}: {data.changes.new_fear} </span>}
              {data.changes.life_tag_hint && <span className="text-cyan-400">+tag: {data.changes.life_tag_hint} </span>}
            </span>
          )}
        </div>
      )
    }

    if (event === 'autonomous_catchup') {
      return (
        <div key={i} className="log-complete">
          <span className="time">{time}</span>
          <span className="tag" style={{ color: '#60a5fa' }}>{isZh ? '生活回顾' : 'CATCHUP'}</span>
          <span className="text-[#aaa]">{isZh ? `你不在的 ${data.sim_days || '?'} 天里` : `${data.sim_days || '?'} days while away`}</span>
          {data.events && data.events.length > 0 && (
            <div className="mt-1 flex flex-col gap-0.5">
              {data.events.map((evt, j) => (
                <div key={j} className="text-[11px]">
                  <span className="text-emerald-400/70">{isZh ? `第${evt.sim_day}天` : `D${evt.sim_day}`}</span>
                  <span className="text-[#666] mx-1">|</span>
                  <span className="text-[#bbb]">{evt.summary || tk(evt.display_name?.replace(/_/g, ' ') || '')}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )
    }

    if (event === 'baby_need') {
      const urgencyColors = { physiological: '#ef4444', emotional: '#f59e0b', social: '#3b82f6' }
      const color = urgencyColors[data.urgency] || '#f59e0b'
      const triggerLabel = data.trigger_label || data.parent_hint || data.trigger
      return (
        <div key={i} className="log-fate" style={{ borderLeft: `3px solid ${color}`, paddingLeft: 8 }}>
          <span className="time">{time}</span>
          {data.sim_day != null && <span className="tag" style={{ color: '#888' }}>{isZh ? `第${data.sim_day}天` : `D${data.sim_day}`}</span>}
          <span className="tag" style={{ color }}>
            {triggerLabel}
          </span>
          {data.signal && <span className="text-[11px]" style={{ color: '#ccc' }}>{data.signal}</span>}
          <span className="italic">{typeof data.expression === 'string' ? data.expression : data.expression?.vocalization || ''}</span>
          {data.facial && <span className="text-[10px] text-[#aaa] ml-1">[{data.facial}]</span>}
          {data.body && <span className="text-[10px] text-[#aaa] ml-1">[{data.body}]</span>}
          <span className="text-[10px] text-red-400/70 ml-1">{data.timeout_sec}s</span>
        </div>
      )
    }

    if (event === 'need_responded') {
      const isParent = data.responder === 'parent'
      return (
        <div key={i} className={isParent ? "log-fate" : "log-system"} style={{ opacity: isParent ? 1 : 0.7 }}>
          <span className="time">{time}</span>
          <span className="tag" style={{ color: isParent ? '#34d399' : '#9ca3af' }}>
            {isParent
              ? (isZh ? '已回应' : 'RESPONDED')
              : (isZh ? `${data.responder === 'self' ? '自行解决' : '代为照顾'}` : data.responder?.toUpperCase())}
          </span>
          {data.nanny_text && <span className="italic text-[#aaa]">{data.nanny_text}</span>}
          {data.attachment_change === 'toward_avoidant' && (
            <span className="text-red-400 text-[10px] ml-1">{isZh ? '依恋 ▼' : 'attach ▼'}</span>
          )}
        </div>
      )
    }

    if (event === 'world_snapshot') {
      return (
        <div key={i} className="log-system" style={{ opacity: 0.75 }}>
          <span className="time">{time}</span>
          {data.days && <span className="tag" style={{ color: '#888' }}>{isZh ? `第${data.days}天` : `D${data.days}`}</span>}
          <span className="tag" style={{ color: '#818cf8' }}>{isZh ? '世界' : 'WORLD'}</span>
          <span className="text-[#7dd3c0]">
            {data.weather} · {data.family_arc}
          </span>
        </div>
      )
    }

    if (event === 'world_snapshot_fallback') {
      return (
        <div key={i} className="log-system" style={{ opacity: 0.4 }}>
          <span className="time">{time}</span>
          <span className="tag" style={{ color: '#6b7280' }}>{isZh ? '世界降级' : 'WORLD FALLBACK'}</span>
        </div>
      )
    }

    if (event === 'heartbeat_initiative') {
      const isAvoidance = data.behavior_type === 'avoidance'
      return (
        <div key={i} className={isAvoidance ? "log-error" : "log-fate"}>
          <span className="time">{time}</span>
          <span className="tag" style={{ color: isAvoidance ? '#ef4444' : '#f59e0b' }}>
            {isAvoidance ? (isZh ? '回避' : 'AVOID') : (isZh ? '主动' : 'INITIATIVE')}
          </span>
          <span className="italic">{data.expression}</span>
          {data.parent_hint && <span className="text-[10px] text-[#888] ml-1">{data.parent_hint}</span>}
        </div>
      )
    }

    if (event === 'heartbeat_ignored') {
      return (
        <div key={i} className="log-system" style={{ opacity: 0.6 }}>
          <span className="time">{time}</span>
          <span className="tag" style={{ color: '#6b7280' }}>{isZh ? '未回应' : 'IGNORED'}</span>
          <span className="italic">{data.reaction}</span>
          {data.consecutive_ignores > 1 && <span className="text-red-400 ml-1">x{data.consecutive_ignores}</span>}
        </div>
      )
    }

    if (event === 'error') {
      return (
        <div key={i} className="log-error">
          <span className="time">{time}</span>
          <span className="tag">ERROR</span>
          {data.message}
        </div>
      )
    }

    return null
  }

  // ── 关键事件交互 ──
  const getCriticalRemainDays = (evt) => {
    if (evt.event_name === 'naming_ceremony') return null
    const currentDay = state.simDay ?? babyStatus?.age_days ?? 0
    const createdDay = evt.created_sim_day ?? evt.sim_day
    return createdDay != null ? 30 - (currentDay - createdDay) : null
  }

  const renderCriticalEvents = () => {
    if (state.criticals.length === 0) return null
    return [...state.criticals].reverse().map((evt, i) => {
      const isNaming = evt.event_name === 'naming_ceremony'
      const isProcessing = state.intervening === evt.event_name
      const remainDays = getCriticalRemainDays(evt)
      const resolved = evt.auto_resolved || evt.awaiting_parent === false
      const expired = evt.expired || (remainDays != null && remainDays <= 0)
      const urgent = !expired && !resolved && remainDays != null && remainDays > 0 && remainDays <= 7

      if (resolved) {
        return (
          <div key={i} className="cradle-critical-card" style={{ opacity: 0.6 }}>
            <div className="flex items-center gap-2 mb-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-sm font-medium text-muted-foreground">{tk(evt.event_display || evt.event_name?.replace(/_/g, ' ') || '')}</span>
              <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-600/20 text-emerald-600">
                {isZh ? '已处理' : 'RESOLVED'}
              </span>
            </div>
            {evt.name && <div className="text-xs text-muted-foreground">{isZh ? `已命名: ${evt.name}` : `Named: ${evt.name}`}</div>}
          </div>
        )
      }

      if (expired) {
        return (
          <div key={i} className="cradle-critical-card" style={{ opacity: 0.5 }}>
            <div className="flex items-center gap-2 mb-2">
              <span className="w-2 h-2 rounded-full bg-gray-400" />
              <span className="text-sm font-medium text-gray-400 line-through">{tk(evt.event_display || evt.event_name?.replace(/_/g, ' ') || '')}</span>
              <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded-full bg-gray-500/20 text-gray-400">
                {isZh ? '已错过' : 'MISSED'}
              </span>
            </div>
            <div className="text-xs text-[#666]">{isZh ? '未及时回应，将自动按默认方式处理' : 'Not responded in time, will be auto-resolved'}</div>
          </div>
        )
      }

      return (
        <div key={i} className="cradle-critical-card">
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 rounded-full bg-amber-600 animate-pulse" />
            <span className="text-sm font-medium text-amber-700">{tk(evt.event_display || evt.event_name?.replace(/_/g, ' ') || '')}</span>
            {remainDays != null && (
              <span className={`ml-auto text-[10px] px-1.5 py-0.5 rounded-full ${urgent ? 'bg-red-500/20 text-red-400' : 'bg-yellow-500/10 text-yellow-500/70'}`}>
                {urgent
                  ? (isZh ? `⏰ 剩 ${remainDays} 天` : `⏰ ${remainDays}d left`)
                  : (isZh ? `剩 ${remainDays} 天` : `${remainDays}d left`)}
              </span>
            )}
          </div>
          <div className="text-xs text-[#999] mb-3">{typeof evt.description === 'object' ? (evt.description.name || JSON.stringify(evt.description)) : evt.description}</div>
          {isNaming && (
            <input
              type="text"
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              placeholder={isZh ? '输入名字...' : 'Enter name...'}
              className="w-full mb-3 px-3 py-1.5 bg-white border border-amber-300 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500/30"
            />
          )}
          <div className="flex flex-wrap gap-2">
            {(evt.parent_choices || []).map((choice, j) => (
              <Button
                key={j}
                size="sm"
                variant={j === 0 ? "default" : "outline"}
                disabled={isProcessing || (isNaming && !nameInput.trim())}
                onClick={() => intervene(evt.event_name, choice.action, isNaming ? nameInput.trim() : '')}
              >
                {isProcessing ? '...' : tk(choice.display || choice.action || '')}
              </Button>
            ))}
          </div>
        </div>
      )
    })
  }

  // ── 主布局 ──
  if (!selectedId) {
    return (
      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 overflow-y-auto flex flex-col">{renderBabyList()}</div>
      </div>
    )
  }


  // 模拟时间格式化
  const simTimeStr = state.simHour != null
    ? `${Math.floor(state.simHour)}:${String(Math.round((state.simHour % 1) * 60)).padStart(2, '0')}`
    : ''
  // 活跃度指示：超过 30 秒没有新事件则视为"等待中"
  const isProcessing = state.lifelineActive && state.lastActivityTs && (Date.now() - state.lastActivityTs < 30000)

  // 刷新时 babyStatus 异步加载，从 cradleBabies 缓存取阶段信息避免头部闪烁
  const cachedBaby = cradleBabies.find(b => b.baby_id === selectedId)
  const phaseIndex = babyStatus?.current_phase?.index ?? cachedBaby?.current_phase
  const phaseName = babyStatus?.current_phase?.name ?? (phaseIndex != null ? PHASE_NAMES[phaseIndex] : null)
  const hasPhaseInfo = phaseIndex != null

  const consoleHeader = (
    <div className="flex items-center gap-2.5 text-[11px]">
      {hasPhaseInfo ? (
        <>
          <span className="text-[#666]">
            {isZh ? '阶段' : 'Phase'} {phaseIndex + 1}/${PHASES_DATA.length}
          </span>
          {phaseName && (
            <>
              <span className="w-px h-3 bg-[#444]" />
              <span className="text-primary font-medium capitalize">{tk(phaseName)}</span>
            </>
          )}
        </>
      ) : admitting ? (
        <span className="text-[#666]">{isZh ? '放入摇篮中' : 'Admitting'}</span>
      ) : (
        <span className="text-[#666]">{isZh ? '等待中' : 'Standby'}</span>
      )}
      {(state.simDay ?? babyStatus?.age_days) != null && (
        <>
          <span className="w-px h-3 bg-[#444]" />
          <span className="text-emerald-400/60 font-mono">
            {isZh ? `第${state.simDay ?? babyStatus?.age_days}天` : `D${state.simDay ?? babyStatus?.age_days}`}
            {simTimeStr && <span className="text-emerald-400/40 ml-0.5">{simTimeStr}</span>}
          </span>
        </>
      )}
      <span className="w-px h-3 bg-[#444]" />
      <div className="flex items-center gap-[5px]">
        {(() => {
          // 已入篮 + 有阶段信息 → 后端自驱动中，默认视为运行中（避免等 SSE 连接的"待命"闪烁）
          const assumedActive = hasPhaseInfo && isInCradle(selectedId)
          const showRunning = admitting || state.running || state.lifelineActive || assumedActive
          const gs = getGrowthStatus(babyStatus, true)
          const isStale = gs === 'stale' && isCurrentInCradle && state.lifelineActive
          return (
            <>
              <span className={cn(
                "w-1.5 h-1.5 rounded-full",
                isStale ? "bg-yellow-500" :
                (allPhasesComplete || state.growComplete) ? "bg-[#28C840]" :
                state.lifelineActive ? "dot-lifeline" :
                showRunning ? "step-dot-running" :
                "bg-[#555]"
              )} />
              <span className={cn(
                "text-[#666]",
                isStale ? "text-yellow-500" :
                showRunning && !state.running ? "text-emerald-400/70" : "",
              )}>
                {isStale ? (isZh ? '停滞' : 'Stalled') :
                 admitting ? (isZh ? '放入中' : 'Admitting') :
                 state.running ? (isZh ? '进行中' : 'Running') :
                 (allPhasesComplete || state.growComplete) ? (isZh ? '已完成' : 'Done') :
                 (state.lifelineActive || assumedActive) ? (isZh ? '运行中' : 'Running') :
                 (isZh ? '待命' : 'Idle')}
              </span>
            </>
          )
        })()}
      </div>
      {(() => {
        const active = state.criticals.filter(c => !c.auto_resolved && c.awaiting_parent !== false && !c.expired).length
        if (active === 0) return null
        return (
          <>
            <span className="w-px h-3 bg-[#444]" />
            <span className="text-yellow-400 animate-pulse text-[10px]">{active} {isZh ? '待回应' : 'pending'}</span>
          </>
        )
      })()}
    </div>
  )

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* 左面板：力导向因果图谱 */}
      <div className="w-[45%] shrink-0 bg-background border-r border-border flex flex-col">
        {/* 宝宝信息头 */}
        <div className="shrink-0 p-3 border-b border-border">
          <div className="flex items-center gap-3 px-2">
            <button
              className="w-8 h-8 flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              onClick={() => { try { localStorage.removeItem('cradle:lastBabyId') } catch { /* ignore */ } navigate('/cradle'); setBabyStatus(null); setReadiness(null) }}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" /></svg>
            </button>
            <div className="relative">
              <Avatar><AvatarImage src={portraitUrl(selectedId, portraitVer)} /><AvatarFallback className={cn("text-[9px] font-mono tracking-tighter font-semibold", avatarPalette(selectedId).bg, avatarPalette(selectedId).text)}>{shortId(selectedId)}</AvatarFallback></Avatar>
              {state.lifelineActive && (
                <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full dot-lifeline border-2 border-background" title={isZh ? '生命线活跃' : 'Lifeline active'} />
              )}
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="font-heading text-xl font-semibold capitalize">
                  {babyStatus?.name || tk(babyStatus?.species || selectedBirth?.species || '')}
                </h1>
                {babyStatus?.age_days != null && (
                  <span className="text-xs text-muted-foreground font-normal">
                    {(() => {
                      const days = babyStatus.age_days || 0
                      const y = Math.floor(days / 365)
                      const m = Math.floor((days % 365) / 30)
                      if (y > 0) return `${y}${isZh ? '岁' : 'y'}${m > 0 ? `${m}${isZh ? '月' : 'mo'}` : ''}`
                      if (m > 0) return `${m}${isZh ? '个月' : 'mo'}${days % 30 > 0 ? `${days % 30}${isZh ? '天' : 'd'}` : ''}`
                      return `${days}${isZh ? '天' : 'd'}`
                    })()}
                  </span>
                )}
                {readiness && (
                  <div className="flex items-center gap-2 text-[10px]">
                    <span className={cn(
                      "px-1.5 py-0.5 rounded-full font-semibold",
                      readiness.ready ? "bg-green-600/15 text-green-600" : "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-300",
                    )}>
                      {readiness.ready ? (isZh ? '可入世' : 'World Ready') : (isZh ? '入世未就绪' : 'World Not Ready')}
                    </span>
                    {readiness.hard && (() => {
                      const entries = Object.values(readiness.hard)
                      const met = entries.filter(v => v.met).length
                      return <span className="text-muted-foreground">{isZh ? '必须' : 'Hard'} {met}/{entries.length}</span>
                    })()}
                    {readiness.soft && (() => {
                      const entries = Object.values(readiness.soft)
                      const met = entries.filter(v => v.met).length
                      return <span className="text-muted-foreground">{isZh ? '加分' : 'Soft'} {met}/{entries.length}</span>
                    })()}
                  </div>
                )}
              </div>
              <div className="text-[10px] text-muted-foreground font-mono">{selectedId}</div>
            </div>
            {!babyStatus && selectedBirth && !admitting && initialLoaded && !isInCradle(selectedId) && (
              <Button size="sm" onClick={() => admitBaby(selectedId)}>
                {isZh ? '放入摇篮' : 'Admit to Cradle'}
              </Button>
            )}
            {admitting && (
              <span className="text-xs text-muted-foreground flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full step-dot-running" />
                {isZh ? '放入中...' : 'Admitting...'}
              </span>
            )}
            {state.running && (
              <span className="text-xs text-muted-foreground flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full step-dot-running" />
                {isZh ? '成长中...' : 'Growing...'}
              </span>
            )}
          </div>
        </div>
        {/* 图谱区域 */}
        <div className="flex-1 min-h-0">
          {graphState ? (
            <LifeGraph
              nodes={graphState.nodes}
              edges={graphState.edges}
              filter={graphState.filter}
              showLabels={graphState.showLabels}
              highlight={graphState.highlight}
              stage="cradle"
              dispatch={graphDispatch}
            />
          ) : (
            <div className="flex-1 overflow-y-auto flex flex-col">
              <div className="w-full flex-1 flex flex-col">{renderStatus()}</div>
            </div>
          )}
        </div>
      </div>

      {/* 右面板 */}
      <div className="flex-1 flex flex-col gap-3 p-5 relative">

        {/* 交互工具栏：只要宝宝已入篮或初始数据未就绪就立即渲染，避免 babyStatus 异步到达时的闪烁 */}
        {(isInCradle(selectedId) || !initialLoaded) ? (
          <div className="shrink-0 mx-1 flex items-center gap-3">
            <div className="flex items-center gap-2.5 mr-1">
              <MessageCircle className="size-5 text-muted-foreground" />
              <div>
                <div className="text-sm font-medium">{isZh ? '交互工具' : 'Interact'}</div>
                <div className="text-[10px] text-muted-foreground leading-tight">
                  {cradleBabies.length} {isZh ? '个宝宝可互动' : 'babies available'}
                </div>
              </div>
            </div>

            {/* 按钮1: 与当前宝宝互动 */}
            <Button
              size="sm"
              variant={chatMode === 'single' ? "default" : "outline"}
              className="gap-1.5"
              onClick={() => {
                setChatMode(m => m === 'single' ? false : 'single')
                setChatTargetOpen(false)
              }}
            >
              <MessageCircle className="size-3.5" />
              {(() => {
                const name = babyStatus?.name || cradleBabies.find(b => b.baby_id === selectedId)?.name || (isZh ? '宝宝' : 'baby')
                return isZh ? `与${name}互动` : `Interact with ${name}`
              })()}
            </Button>

            {/* 按钮2: 多宝宝群聊 */}
            {cradleBabies.length >= 2 && (
              <div className="relative" ref={chatTargetRef}>
                <Button
                  size="sm"
                  variant={(chatMode === 'group' || chatTargetOpen) ? "default" : "outline"}
                  className="gap-1.5"
                  onClick={() => {
                    setChatTargetOpen(o => !o)
                    if (!chatTargetOpen) setSocialSelected([])
                  }}
                >
                  <Users className="size-3.5" />
                  {chatMode === 'group' && groupConvId
                    ? (isZh ? '群聊中' : 'Group Chat')
                    : (isZh ? '多宝宝互动' : 'Multi-baby Interact')
                  }
                  <ChevronDown className={cn("size-3 transition-transform", chatTargetOpen && "rotate-180")} />
                </Button>

                {chatTargetOpen && (
                  <div className="absolute top-full left-0 mt-1.5 w-80 bg-popover border border-border rounded-xl shadow-xl z-50 overflow-hidden">
                    <div className="px-3 pt-3 pb-2 text-[11px] text-muted-foreground">
                      {isZh ? '选择参与对话的宝宝（至少 2 个），并为群起个名字' : 'Select babies (min 2) and name the group'}
                    </div>
                    <div className="max-h-64 overflow-y-auto">
                      {cradleBabies.map(b => {
                        const initial = (b.name || b.baby_id || '?')[0].toUpperCase()
                        const checked = socialSelected.includes(b.baby_id)
                        return (
                          <button
                            key={b.baby_id}
                            className={cn(
                              "w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-accent",
                              checked && "bg-primary/5",
                            )}
                            onClick={() => {
                              setSocialSelected(prev =>
                                checked ? prev.filter(id => id !== b.baby_id) : [...prev, b.baby_id]
                              )
                            }}
                          >
                            <Avatar className={cn("transition-colors", checked && "ring-2 ring-primary")}>
                              <AvatarImage src={portraitUrl(b.baby_id)} />
                              <AvatarFallback className={cn("text-xs font-mono", checked && "bg-primary/20 text-primary")}>
                                {initial}
                              </AvatarFallback>
                            </Avatar>
                            <div className="flex-1 min-w-0">
                              <div className="text-sm font-medium text-popover-foreground truncate">{b.name || b.baby_id}</div>
                              <div className="text-[11px] text-muted-foreground">
                                {isZh ? '阶段' : 'Phase'} {(b.current_phase || 0) + 1} · {tk(PHASE_NAMES[b.current_phase || 0] || '')}
                              </div>
                            </div>
                            <div className={cn(
                              "w-4 h-4 rounded border flex items-center justify-center text-[10px]",
                              checked ? "border-primary bg-primary text-primary-foreground" : "border-border",
                            )}>
                              {checked && '\u2713'}
                            </div>
                          </button>
                        )
                      })}
                    </div>
                    <div className="p-2 border-t border-border flex flex-col gap-2">
                      <Input
                        type="text"
                        className="h-8 text-sm"
                        placeholder={isZh ? '给群起个名字...' : 'Name this group...'}
                        value={groupNameInput}
                        onChange={e => setGroupNameInput(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); startGroupChat() } }}
                      />
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          className="flex-1"
                          onClick={startGroupChat}
                          disabled={socialSelected.length < 2 || !groupNameInput.trim() || groupCreating}
                        >
                          {groupCreating ? '...' : (isZh ? `开始群聊 (${socialSelected.length})` : `Start Group (${socialSelected.length})`)}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => setChatTargetOpen(false)}>
                          {isZh ? '取消' : 'Cancel'}
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* 关键事件按钮：只在有未处理事件时显示 */}
            {(() => {
              const activeCount = state.criticals.filter(c => {
                if (c.expired || c.auto_resolved || c.awaiting_parent === false) return false
                const r = getCriticalRemainDays(c)
                return r === null || r > 0
              }).length
              const expiredCount = state.criticals.filter(c => c.expired || (getCriticalRemainDays(c) != null && getCriticalRemainDays(c) <= 0)).length
              if (activeCount === 0 && expiredCount === 0) return null
              const remains = state.criticals
                .map(c => getCriticalRemainDays(c))
                .filter(r => r != null && r > 0)
              const minRemain = remains.length > 0 ? Math.min(...remains) : 30
              const btnUrgent = minRemain <= 7
              return (
              <div className="relative" ref={criticalsPanelRef}>
                <Button
                  size="sm"
                  variant="default"
                  className={cn("gap-1.5 border-none",
                    activeCount === 0
                      ? "bg-gray-500 text-white hover:bg-gray-400"
                      : btnUrgent ? "bg-red-500 text-white hover:bg-red-400 animate-pulse"
                      : "bg-yellow-500 text-black hover:bg-yellow-400")}
                  onClick={() => setCriticalsPanelOpen(o => !o)}
                >
                  <Bell className="size-3.5" />
                  <span>{activeCount > 0 ? activeCount : expiredCount}</span>
                  <span className="hidden sm:inline">{activeCount > 0 ? (isZh ? '待回应' : 'pending') : (isZh ? '已错过' : 'missed')}</span>
                  {activeCount > 0 && minRemain < 30 && <span className="text-[10px] opacity-80">({minRemain}d)</span>}
                  <ChevronDown className={cn("size-3 transition-transform", criticalsPanelOpen && "rotate-180")} />
                </Button>

                {criticalsPanelOpen && (
                  <div className="absolute top-full right-0 mt-1.5 w-96 bg-popover border border-border rounded-xl shadow-xl z-50 overflow-hidden">
                    <div className="px-3 pt-3 pb-2 text-[11px] text-muted-foreground flex items-center gap-2">
                      <Bell className="size-3" />
                      {isZh ? '需要你的关注' : 'Needs your attention'}
                    </div>
                    <div className="max-h-80 overflow-y-auto p-2 flex flex-col gap-2">
                      {renderCriticalEvents()}
                    </div>
                  </div>
                )}
              </div>
              )})()}

            {/* 速率选择器已移到顶部导航栏 */}
          </div>
        ) : null}

        {/* ── 对话面板 + 控制台布局 ── */}
        {chatMode ? (
          <>
            {/* 对话面板 (4/5) */}
            {chatMode === 'single' && (
              <ChatPanel
                babyId={selectedId}
                babyStatus={babyStatus}
                touchActions={touchActions}
                loadTouchActions={loadTouchActions}
                isZh={isZh}
                tk={tk}
              />
            )}
            {chatMode === 'group' && groupConvId && (
              <GroupChatPanel
                convId={groupConvId}
                isZh={isZh}
                onClose={() => { setGroupConvId(null); setChatMode(false) }}
              />
            )}

            {/* 控制台 (1/5) */}
            <ConsolePanel
              ref={logRefCb}
              className="flex-[1] min-h-[120px]"
              header={consoleHeader}
            >
              {state.logs.length === 0 && (
                <div className="log-system">
                  <span className="blink-dot" />
                  {loadingHistory
                    ? (isZh ? '正在加载历史记录...' : 'Loading history...')
                    : (isZh ? '成长日志' : 'Growth log')}
                </div>
              )}
              {state.logs.map(renderLog)}
              {state.lifelineActive && state.logs.length > 0 && (() => {
                const lastTick = [...state.logs].reverse().find(l => l.event === 'sim_tick')
                const lastLog = state.logs[state.logs.length - 1]
                const elapsedSec = lastTick?.chainStart
                  ? Math.max(0, Math.floor((Date.now() - lastTick.chainStart) / 1000))
                  : 0
                return (
                  <div className="log-system" style={{ color: '#34d399b3' }}>
                    <span className="time">{lastLog?.time || ''}</span>
                    <span className="inline-block w-1.5 h-1.5 rounded-full step-dot-running mr-2 align-middle" />
                    {isZh ? '生命在自然生长中...' : 'Life is unfolding...'}
                    {elapsedSec > 0 && <span className="ml-1">{elapsedSec}s</span>}
                  </div>
                )
              })()}
            </ConsolePanel>
          </>
        ) : (
          /* ── 无对话时：控制台全屏 ── */
          <ConsolePanel
            ref={logRefCb}
            className="flex-1"
            headerHeight={38}
            header={consoleHeader}
          >
            {state.logs.length === 0 && (
              <div className="log-system" style={{ color: '#34d399b3' }}>
                <span className="blink-dot" />
                {loadingHistory
                  ? (isZh ? '正在加载历史记录...' : 'Loading history...')
                  : (isZh ? '生命在自然生长中，等待新的事件...' : 'Life is unfolding, waiting for new events...')}
              </div>
            )}
            {state.logs.map(renderLog)}
            {state.lifelineActive && state.logs.length > 0 && (() => {
              const lastLog = state.logs[state.logs.length - 1]
              return (
                <div className="log-system" style={{ color: '#34d399b3' }}>
                  <span className="time">{lastLog?.time || ''}</span>
                  <span className="inline-block w-1.5 h-1.5 rounded-full step-dot-running mr-2 align-middle" />
                  {isZh ? '生命在自然生长中...' : 'Life is unfolding...'}
                </div>
              )
            })()}
          </ConsolePanel>
        )}
      </div>
    </div>
  )
}
