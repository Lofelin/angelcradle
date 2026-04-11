/**
 * [INPUT]: react, react-router-dom, ../i18n, shadcn/ui (Button, Card), ../lib/utils
 * [OUTPUT]: Cradle 组件 — 摇篮养育界面
 * [POS]: 摇篮 tab 页面，消费 SSE 流驱动婴儿成长模拟（含 phase_state_update/stress_regression/regression_recovery/autonomous_routine/autonomous_event/autonomous_catchup 事件）
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */
import { useState, useEffect, useLayoutEffect, useRef, useReducer, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { translateKey } from './i18n'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Avatar, AvatarFallback, AvatarGroup } from '@/components/ui/avatar'
import { Input } from '@/components/ui/input'
import ConsolePanel from '@/components/ConsolePanel'
import { cn } from '@/lib/utils'
import { MessageCircle, Users, ChevronDown, Send, Hand } from 'lucide-react'

const API = 'http://localhost:8000'

// 从 baby_id 提取短标识（取末4位）
const shortId = (id) => id ? id.slice(-4).toUpperCase() : '?'

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
  { name: 'rule_understanding', age: '4-5岁', desc_zh: '初步逻辑思维，用"因为/所以/如果"推理', desc_en: 'Beginning logic. Uses "because/so/if" but reasoning is often wrong.' },
  { name: 'abstract_beginning', age: '5-6岁', desc_zh: '有自己的观点，能反驳，但非黑即白', desc_en: 'Has opinions and can argue, but still thinks in black-and-white.' },
  { name: 'independence', age: '6-7岁', desc_zh: '"我自己来！"独立意识，准备好面对世界', desc_en: '"I\'ll do it myself." Has own opinions, ready to enter the world.' },
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
}

function cradleReducer(state, action) {
  switch (action.type) {
    case 'RESET':
      return { ...INIT }
    case 'LIFELINE_CONNECTED':
      return { ...state, lifelineActive: true }
    case 'LIFELINE_DISCONNECTED':
      return { ...state, lifelineActive: false }
    case 'LOAD_HISTORY':
      return { ...state, logs: action.logs }
    case 'START_GROW':
      return { ...INIT, running: true, startedAt: state.startedAt || Date.now() }
    case 'RESUME_GROW':
      return { ...state, logs: [], criticals: [], running: true, paused: false }
    case 'SSE': {
      const { data, ts } = action
      const log = { time: ts, event: data.event, data }
      let logs
      // 心跳事件：只要最后一条也是心跳类型就替换（避免交替刷屏）
      const heartbeatEvents = ['narrating', 'compiling', 'phase_completing']
      const lastEvent = state.logs.length > 0 ? state.logs[state.logs.length - 1].event : null
      if (heartbeatEvents.includes(data.event) && data.elapsed && heartbeatEvents.includes(lastEvent)) {
        logs = [...state.logs.slice(0, -1), log]
      } else {
        logs = [...state.logs, log]
      }
      let { phase, criticals } = state

      if (data.event === 'phase_start') {
        phase = { index: data.phase_index, name: data.phase_name, display: data.phase_display, age_range: data.age_range, description: data.description, expression_mode: data.expression_mode }
      } else if (data.event === 'critical_event') {
        criticals = [...criticals, data]
      }
      return { ...state, logs, phase, criticals }
    }
    case 'STREAM_END':
      return { ...state, running: false }
    case 'PAUSED':
      return { ...state, running: false, paused: true }
    case 'GROW_COMPLETE':
      return { ...state, running: false, growComplete: true }
    case 'INTERACT_SENDING': {
      // 乐观更新：立即显示用户消息
      const pendingLog = { time: getTime(), event: 'interaction_pending', data: { parent_message: action.message, action_type: action.actionType || 'message', emoji: action.emoji } }
      return { ...state, interacting: true, logs: [...state.logs, pendingLog] }
    }
    case 'INTERACT_DONE': {
      // 替换 pending 日志为完整的 interaction，保留发送时间
      const pending = state.logs.find(l => l.event === 'interaction_pending')
      const mergedData = { ...action.data, emoji: pending?.data?.emoji }
      const log = { time: pending?.time || getTime(), replyTime: getTime(), event: 'interaction', data: mergedData }
      const logs = state.logs.filter(l => l.event !== 'interaction_pending')
      return { ...state, interacting: false, logs: [...logs, log] }
    }
    case 'INTERACT_ERROR': {
      // 移除 pending 日志
      const logs = state.logs.filter(l => l.event !== 'interaction_pending')
      return { ...state, interacting: false, logs }
    }
    case 'HEARTBEAT_INITIATIVE': {
      const log = { time: getTime(), event: 'heartbeat_initiative', data: action.data }
      return { ...state, logs: [...state.logs, log] }
    }
    case 'HEARTBEAT_IGNORED': {
      const log = { time: getTime(), event: 'heartbeat_ignored', data: action.data }
      return { ...state, logs: [...state.logs, log] }
    }
    case 'INTERVENE_START':
      return { ...state, intervening: action.eventName }
    case 'INTERVENE_DONE': {
      const logs = [...state.logs, { time: getTime(), event: 'intervene_result', data: action.result }]
      const criticals = state.criticals.filter(c => c.event_name !== action.eventName)
      return { ...state, logs, criticals, intervening: null }
    }
    case 'AUTONOMOUS_ROUTINE': {
      const log = { time: getTime(), event: 'autonomous_routine', data: action.data }
      return { ...state, logs: [...state.logs, log] }
    }
    case 'AUTONOMOUS_EVENT': {
      const log = { time: getTime(), event: 'autonomous_event', data: action.data }
      return { ...state, logs: [...state.logs, log] }
    }
    case 'AUTONOMOUS_CATCHUP': {
      const log = { time: getTime(), event: 'autonomous_catchup', data: action.data }
      return { ...state, logs: [...state.logs, log] }
    }
    default:
      return state
  }
}

export default function Cradle({ lang }) {
  const tk = (v) => translateKey(v, lang)
  const isZh = lang === 'zh'

  const { babyId: selectedId } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const autoGrowRef = useRef(searchParams.get('autoGrow') === 'true')

  const [birthBabies, setBirthBabies] = useState([])
  const [cradleBabies, setCradleBabies] = useState([])
  const [babyStatus, setBabyStatus] = useState(null)
  const [phaseSummaries, setPhaseSummaries] = useState({}) // 阶段完成总结 { index: summary_text }
  const [admitting, setAdmitting] = useState(false)
  const [readiness, setReadiness] = useState(null)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [nameInput, setNameInput] = useState('')
  const [state, dispatch] = useReducer(cradleReducer, INIT)
  const logRef = useRef(null)
  const currentPhaseRef = useRef(null)
  const logRefCb = useCallback((node) => {
    logRef.current = node
    if (node) node.scrollTop = node.scrollHeight
  }, [])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [state.logs.length])

  // 自动滚动到当前阶段卡片
  useEffect(() => {
    setTimeout(() => {
      if (currentPhaseRef.current) {
        currentPhaseRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }, 100)
  }, [babyStatus?.current_phase?.index])

  // ── 数据加载 ──
  const loadBabies = useCallback(() => {
    Promise.all([
      fetch(`${API}/babies`).then(r => r.json()).catch(() => ({ babies: [] })),
      fetch(`${API}/cradle/babies`).then(r => r.json()).catch(() => ({ babies: [] })),
    ]).then(([birth, cradle]) => {
      setBirthBabies(birth.babies || [])
      setCradleBabies(cradle.babies || [])
    })
  }, [])

  useEffect(() => { loadBabies() }, [loadBabies])

  const loadStatus = useCallback((id) => {
    fetch(`${API}/cradle/${id}/status`)
      .then(r => { if (!r.ok) throw new Error(); return r.json() })
      .then(setBabyStatus)
      .catch(() => setBabyStatus(null))
  }, [])

  useEffect(() => {
    // 切换宝宝时重置所有状态，避免残留上一个宝宝的日志和对话
    dispatch({ type: 'RESET' })
    const savedMode = sessionStorage.getItem(`chatMode:${selectedId}`)
    setChatMode(savedMode === 'single' ? 'single' : false)
    setSocialSession(null)
    setSocialHistory([])
    setShowSocialSelector(false)
    setChatInput('')
    setReadiness(null)
    setTouchPanelOpen(false)
    setTouchActions(null)

    if (!selectedId) { setBabyStatus(null); return }
    const inCradle = cradleBabies.some(b => b.baby_id === selectedId)
    if (inCradle) {
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
      // 加载历史 SSE 事件
      setLoadingHistory(true)
      fetch(`${API}/cradle/${selectedId}/events`)
        .then(r => r.json())
        .then(resp => {
          let lastTs = ''
          const heartbeats = ['narrating', 'compiling', 'phase_completing']
          const historicalLogs = (resp.events || [])
            .filter(e => e.event !== 'narrating') // 过滤叙事心跳
            .reduce((acc, e) => {
              if (e.ts) lastTs = new Date(e.ts * 1000).toLocaleTimeString('en-US', { hour12: false })
              const payload = e.data ? { ...e.data, event: e.event } : e
              const log = { time: lastTs, event: e.event, data: payload }
              // 连续心跳事件只保留最后一条
              if (heartbeats.includes(e.event) && acc.length > 0 && heartbeats.includes(acc[acc.length - 1].event)) {
                acc[acc.length - 1] = log
              } else {
                acc.push(log)
              }
              return acc
            }, [])
          dispatch({ type: 'LOAD_HISTORY', logs: historicalLogs })
          setLoadingHistory(false)
        })
        .catch(() => setLoadingHistory(false))
    } else {
      setBabyStatus(null)
    }
  }, [selectedId, cradleBabies, loadStatus])

  // ── 自动开始成长（从 Womb 跳转过来时）──
  const startGrowRef = useRef(null)
  useEffect(() => {
    if (autoGrowRef.current && babyStatus && !state.running) {
      autoGrowRef.current = false
      setSearchParams({}, { replace: true })
      // 延迟一帧确保 startGrow 已绑定
      setTimeout(() => startGrowRef.current?.(), 0)
    }
  }, [babyStatus, state.running, setSearchParams])

  // ── 操作 ──
  const admitBaby = (babyId) => {
    setAdmitting(true)
    dispatch({ type: 'START_GROW' })

    const source = new EventSource(`${API}/cradle/admit/stream?baby_id=${encodeURIComponent(babyId)}`)
    source.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        dispatch({ type: 'SSE', data, ts: getTime() })

        if (data.event === 'admitted') {
          source.close()
          setAdmitting(false)
          dispatch({ type: 'STREAM_END' })
          loadBabies()
          navigate(`/cradle/${babyId}`)
        } else if (data.event === 'error') {
          source.close()
          setAdmitting(false)
          dispatch({ type: 'STREAM_END' })
        }
      } catch { /* ignore */ }
    }
    source.onerror = () => {
      source.close()
      setAdmitting(false)
      dispatch({ type: 'STREAM_END' })
    }
  }

  // 使用 grow/stream 自动成长
  const startGrow = useCallback((resume = false) => {
    if (!selectedId || state.running) return
    dispatch({ type: resume ? 'RESUME_GROW' : 'START_GROW' })

    const source = new EventSource(`${API}/cradle/${selectedId}/grow/stream`)
    source.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.event === 'error') {
          // 错误时终止流，重新加载历史日志（START_GROW 已清空）
          dispatch({ type: 'STREAM_END' })
          source.close()
          fetch(`${API}/cradle/${selectedId}/events`)
            .then(r => r.json())
            .then(evts => {
              let lastTs2 = ''
              const hb = ['narrating', 'compiling', 'phase_completing']
              const historicalLogs = (evts.events || [])
                .filter(ev => ev.event !== 'narrating')
                .reduce((acc, ev) => {
                  if (ev.ts) lastTs2 = new Date(ev.ts * 1000).toLocaleTimeString('en-US', { hour12: false })
                  const payload = ev.data ? { ...ev.data, event: ev.event } : ev
                  const log = { time: lastTs2, event: ev.event, data: payload }
                  if (hb.includes(ev.event) && acc.length > 0 && hb.includes(acc[acc.length - 1].event)) {
                    acc[acc.length - 1] = log
                  } else {
                    acc.push(log)
                  }
                  return acc
                }, [])
              historicalLogs.push({ time: getTime(), event: 'error', data })
              dispatch({ type: 'LOAD_HISTORY', logs: historicalLogs })
            })
            .catch(() => {
              dispatch({ type: 'SSE', data, ts: getTime() })
            })
          return
        } else if (data.event === 'paused') {
          dispatch({ type: 'PAUSED' })
        } else if (data.event === 'growth_complete') {
          dispatch({ type: 'GROW_COMPLETE' })
        } else {
          dispatch({ type: 'SSE', data, ts: getTime() })
        }
        // 增量更新左面板状态卡片，有什么就展示什么
        setBabyStatus(prev => {
          if (!prev) return prev
          let next = prev
          if (data.event === 'phase_start') {
            next = { ...next, current_phase: { index: data.phase_index, name: data.phase_name, display: data.phase_display } }
            if (data.expression_mode) next = { ...next, expression_mode: data.expression_mode }
          } else if (data.event === 'capabilities_unlocked' && data.capabilities) {
            const existing = new Set(next.capabilities || [])
            const merged = [...(next.capabilities || []), ...data.capabilities.filter(c => !existing.has(c))]
            next = { ...next, capabilities: merged }
          } else if (data.event === 'milestones' && data.milestones) {
            next = { ...next, milestones: [...(next.milestones || []), ...data.milestones] }
          } else if (data.event === 'environment_reaction') {
            if (data.new_fear) next = { ...next, fears: [...(next.fears || []), data.new_fear] }
            if (data.new_preference) next = { ...next, preferences: [...(next.preferences || []), data.new_preference] }
          } else if (data.event === 'phase_completed') {
            if (data.age_days != null) next = { ...next, age_days: data.age_days }
          } else if (data.event === 'phase_state_update') {
            // 增量更新体格/喂养/睡眠/出牙
            const changes = data.changes || []
            for (const c of changes) {
              if (c.type === 'physical_growth') {
                next = { ...next, physical: { ...(next.physical || {}), height_cm: c.height_cm, weight_kg: c.weight_kg } }
              } else if (c.type === 'new_teeth') {
                next = { ...next, physical: { ...(next.physical || {}), teeth_count: c.total } }
              } else if (c.type === 'feeding_transition') {
                next = { ...next, nutrition_sleep: { ...(next.nutrition_sleep || {}), feeding_mode: c.to } }
              } else if (c.type === 'sleep_regression_onset') {
                next = { ...next, nutrition_sleep: { ...(next.nutrition_sleep || {}), sleep_regression_active: true } }
              } else if (c.type === 'sleep_regression_resolved') {
                next = { ...next, nutrition_sleep: { ...(next.nutrition_sleep || {}), sleep_regression_active: false } }
              }
            }
          } else if (data.event === 'stress_regression') {
            next = { ...next, stress: { ...(next.stress || {}), stress_level: data.stress_level, regressed_capabilities: data.regressed } }
          } else if (data.event === 'regression_recovery') {
            next = { ...next, stress: { ...(next.stress || {}), stress_level: data.stress_level, regressed_capabilities: [] } }
          } else if (data.event === 'scene' && data.stress_level != null) {
            next = { ...next, stress: { ...(next.stress || {}), stress_level: data.stress_level } }
          }
          return next === prev ? prev : next
        })
      } catch { /* ignore */ }
    }
    source.onerror = () => {
      dispatch({ type: 'STREAM_END' })
      source.close()
      loadStatus(selectedId)
    }
  }, [selectedId, state.running, loadStatus])
  startGrowRef.current = startGrow

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

  const [chatInput, setChatInput] = useState('')
  const [chatMode, setChatMode] = useState(() => {
    try {
      if (!selectedId) return false
      const saved = sessionStorage.getItem(`chatMode:${selectedId}`)
      return saved === 'single' ? 'single' : false
    } catch { return false }
  })
  const [chatTargetOpen, setChatTargetOpen] = useState(false) // 任意宝宝下拉
  const [touchPanelOpen, setTouchPanelOpen] = useState(false) // 肢体动作面板
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

  // 持久化 chatMode
  useEffect(() => {
    if (selectedId) {
      if (chatMode === 'single') sessionStorage.setItem(`chatMode:${selectedId}`, 'single')
      else sessionStorage.removeItem(`chatMode:${selectedId}`)
    }
  }, [chatMode, selectedId])
  const chatInputRef = useRef(null)
  const chatTargetRef = useRef(null)
  const chatScrollRef = useRef(null)

  // 点击外部关闭下拉
  useEffect(() => {
    if (!chatTargetOpen) return
    const handler = (e) => {
      if (chatTargetRef.current && !chatTargetRef.current.contains(e.target)) setChatTargetOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [chatTargetOpen])

  const sendInteraction = async (touchKey = null, touchLabel = null, touchEmoji = null) => {
    const isTouch = !!touchKey
    const msg = isTouch ? (touchLabel || touchKey) : chatInput.trim()
    if ((!msg && !isTouch) || !selectedId || state.interacting) return
    if (!isTouch) setChatInput('')
    if (isTouch) setTouchPanelOpen(false)
    dispatch({ type: 'INTERACT_SENDING', message: msg, actionType: isTouch ? 'touch' : 'message', emoji: touchEmoji })
    try {
      const body = isTouch
        ? { message: '', action_type: 'touch', touch_key: touchKey }
        : { message: msg }
      const r = await fetch(`${API}/cradle/${selectedId}/interact`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (r.status === 409) {
        dispatch({ type: 'INTERACT_ERROR' })
        return
      }
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      dispatch({ type: 'INTERACT_DONE', data: { parent_message: msg, action_type: isTouch ? 'touch' : 'message', baby_response: data.baby_response, emotional_tone: data.emotional_tone, expression_mode: data.expression_mode } })
    } catch (e) {
      console.error('Interact failed:', e)
      dispatch({ type: 'INTERACT_ERROR' })
    }
  }

  // 加载肢体动作列表
  const loadTouchActions = async () => {
    if (!selectedId) return
    try {
      const r = await fetch(`${API}/cradle/${selectedId}/touch-actions`)
      if (r.ok) setTouchActions(await r.json())
    } catch { /* ignore */ }
  }

  // 心跳 SSE 流：宝宝在摇篮中时持续连接，实时接收主动行为
  useEffect(() => {
    if (!selectedId) return
    const inCradle = cradleBabies.some(b => b.baby_id === selectedId)
    if (!inCradle) return

    const source = new EventSource(`${API}/cradle/${selectedId}/heartbeat/stream`)
    source.onopen = () => dispatch({ type: 'LIFELINE_CONNECTED' })
    source.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.event === 'heartbeat_initiative') dispatch({ type: 'HEARTBEAT_INITIATIVE', data })
        if (data.event === 'heartbeat_ignored') dispatch({ type: 'HEARTBEAT_IGNORED', data })
        if (data.event === 'autonomous_routine') dispatch({ type: 'AUTONOMOUS_ROUTINE', data })
        if (data.event === 'autonomous_event') dispatch({ type: 'AUTONOMOUS_EVENT', data })
        if (data.event === 'autonomous_catchup') dispatch({ type: 'AUTONOMOUS_CATCHUP', data })
      } catch { /* ignore */ }
    }
    source.onerror = () => {
      dispatch({ type: 'LIFELINE_DISCONNECTED' })
    }
    return () => { source.close(); dispatch({ type: 'LIFELINE_DISCONNECTED' }) }
  }, [selectedId, cradleBabies])

  const checkReadiness = async () => {
    if (!selectedId) return
    try {
      const r = await fetch(`${API}/cradle/${selectedId}/readiness`)
      setReadiness(await r.json())
    } catch { setReadiness(null) }
  }

  // ── 社交会话 ──
  const [socialSession, setSocialSession] = useState(null) // { session_id, participants }
  const [socialHistory, setSocialHistory] = useState([])
  const [socialLoading, setSocialLoading] = useState(false)
  const [showSocialSelector, setShowSocialSelector] = useState(false)
  const [socialSelected, setSocialSelected] = useState([])

  // 对话区自动滚动到底部（layoutEffect 在绘制前执行，避免闪烁）
  useLayoutEffect(() => {
    const el = chatScrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [state.logs.length, socialHistory.length])

  const eligibleForSocial = cradleBabies.filter(b => (b.current_phase || 0) >= 8)

  const startSocial = async () => {
    if (socialSelected.length < 2) return
    setSocialLoading(true)
    try {
      const r = await fetch(`${API}/cradle/social/start`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ baby_ids: socialSelected, context: '' }),
      })
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setSocialSession(data)
      setSocialHistory([])
      setShowSocialSelector(false)
    } catch (e) {
      console.error('Social start failed:', e)
    } finally {
      setSocialLoading(false)
    }
  }

  const socialTurn = async () => {
    if (!socialSession) return
    setSocialLoading(true)
    try {
      const r = await fetch(`${API}/cradle/social/turn`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: socialSession.session_id }),
      })
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setSocialHistory(prev => [...prev, { role: 'baby', ...data }])
    } catch (e) {
      console.error('Social turn failed:', e)
    } finally {
      setSocialLoading(false)
    }
  }

  const socialParentMsg = async (msg) => {
    if (!socialSession || !msg.trim()) return
    setSocialLoading(true)
    try {
      const r = await fetch(`${API}/cradle/social/message`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: socialSession.session_id, message: msg }),
      })
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setSocialHistory(prev => [
        ...prev,
        { role: 'parent', content: data.parent_message },
        { role: 'baby', ...data.response },
      ])
    } catch (e) {
      console.error('Social message failed:', e)
    } finally {
      setSocialLoading(false)
    }
  }

  const endSocial = async () => {
    if (!socialSession) return
    setSocialLoading(true)
    try {
      const r = await fetch(`${API}/cradle/social/end`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: socialSession.session_id }),
      })
      const data = await r.json()
      setSocialHistory(prev => [...prev, { role: 'system', content: isZh ? `会话结束，共 ${data.total_turns} 轮` : `Session ended, ${data.total_turns} turns` }])
      setSocialSession(null)
    } catch (e) {
      console.error('Social end failed:', e)
    } finally {
      setSocialLoading(false)
    }
  }

  const isInCradle = (babyId) => cradleBabies.some(b => b.baby_id === babyId)
  const selectedBirth = birthBabies.find(b => b.id === selectedId)
  const allPhasesComplete = babyStatus && babyStatus.current_phase?.index >= 11

  // ── 婴儿列表 ──
  const renderBabyList = () => {
    const allBabies = birthBabies.map(b => ({
      id: b.id, species: b.species, sex: b.sex, alive: b.alive,
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
      <div className="flex flex-col gap-2 p-6">
        <div className="text-sm text-muted-foreground mb-2">
          {isZh ? '选择一个婴儿进行养育' : 'Select a baby to nurture'}
        </div>
        {allBabies.map(baby => (
          <button
            key={baby.id}
            className={cn(
              "w-full text-left p-4 rounded-xl border border-border bg-card transition-all duration-200",
              "hover:border-primary/50 hover:shadow-sm cursor-pointer",
            )}
            onClick={() => { navigate(`/cradle/${baby.id}`); setReadiness(null) }}
          >
            <div className="flex items-center gap-3">
              <div className="relative">
                <Avatar><AvatarFallback className="text-[10px] font-mono">{shortId(baby.id)}</AvatarFallback></Avatar>
                {baby.inCradle && (
                  <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full dot-lifeline border-2 border-card" title={isZh ? '生命线活跃' : 'Lifeline active'} />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm capitalize">{baby.cradleInfo?.name || tk(baby.species)}</span>
                  <span className="text-xs text-muted-foreground capitalize">{tk(baby.sex)}</span>
                  {baby.inCradle && (
                    <span className="text-[10px] px-1.5 py-0.5 bg-primary/10 text-primary rounded-full">
                      {baby.cradleInfo ? `${isZh ? '阶段' : 'Phase'} ${(baby.cradleInfo.current_phase || 0) + 1}/12` : (isZh ? '已入篮' : 'In Cradle')}
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-muted-foreground font-mono truncate mt-0.5">{baby.id}</div>
              </div>
              <svg className="w-4 h-4 text-muted-foreground/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" /></svg>
            </div>
          </button>
        ))}
      </div>
    )
  }

  // ── 左面板：状态 ──
  const renderStatus = () => {
    if (!babyStatus) {
      // 已入篮但 status 还没加载完：显示加载中
      if (isInCradle(selectedId)) {
        return (
          <div className="flex flex-col items-center justify-center flex-1 gap-4 p-6">
            <span className="text-sm text-muted-foreground animate-pulse">{isZh ? '加载中...' : 'Loading...'}</span>
          </div>
        )
      }
      if (selectedBirth) {
        return (
          <div className="flex flex-col items-center justify-center flex-1 gap-4 p-6">
            <Avatar size="lg"><AvatarFallback className="text-xs font-mono">{shortId(selectedId)}</AvatarFallback></Avatar>
            <div className="text-center">
              <div className="font-heading text-lg font-semibold capitalize">{tk(selectedBirth.species)}</div>
              <div className="text-sm text-muted-foreground capitalize">{tk(selectedBirth.sex)}</div>
              <div className="text-[11px] text-muted-foreground font-mono mt-1">{selectedBirth.id}</div>
            </div>
            <Button onClick={() => admitBaby(selectedId)} disabled={admitting}>
              {admitting ? '...' : (isZh ? '放入摇篮' : 'Admit to Cradle')}
            </Button>
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

                return (
                  <div key={pd.name} ref={isCurrent ? currentPhaseRef : null} className={cn("relative flex items-start", isLeft ? "justify-start" : "justify-end")}>
                    {/* 中间节点 */}
                    <div className={cn(
                      "absolute left-1/2 top-3.5 w-2.5 h-2.5 rounded-full -translate-x-1/2 z-[2]",
                      isDone && "bg-primary",
                      isCurrent && "bg-primary shadow-[0_0_8px_rgba(213,147,55,0.6)] animate-pulse",
                      !isDone && !isCurrent && "bg-border",
                    )} />

                    {/* 卡片 */}
                    <div className={cn(
                      "w-[calc(50%-16px)] mb-3 rounded-xl border p-3",
                      isCurrent && "bg-card border-primary/30 shadow-sm",
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
                            {isDone ? (isZh ? '完成' : 'DONE') : (isZh ? '进行中' : 'NOW')}
                          </span>
                        )}
                      </div>

                      {/* 内容 */}
                      <div className="text-[11px] text-muted-foreground mt-2 leading-relaxed max-h-[300px] no-scrollbar">
                        <span className="text-muted-foreground/60">{pd.age}</span>
                        <div className="mt-1">{summary || desc}</div>
                      </div>
                      {isCurrent && s.expression_mode && (
                        <div className="text-[10px] text-muted-foreground/60 mt-1.5 capitalize">{tk(s.expression_mode)}</div>
                      )}
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
                  [isZh ? '日龄' : 'Age', `${s.age_days}${isZh ? '天' : 'd'}`],
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
          <span className="tag">{isZh ? '阶段' : 'PHASE'} {data.phase_index + 1}/12</span>
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
          <span className="tag">{isZh ? '关键' : 'CRITICAL'}</span>
          <span className="font-medium">{tk(data.event_display || data.event_name?.replace(/_/g, ' ') || '')}</span>
          <span className="text-[#aaa] text-[11px] ml-1">{data.description}</span>
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
    if (event === 'admitted') {
      return (
        <div key={i} className="log-stage-start" style={{ color: 'var(--primary)' }}>
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '就绪' : 'READY'}</span>
          {isZh ? `${data.baby_id} 已投入摇篮` : `${data.baby_id} admitted to cradle`}
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

    if (event === 'autonomous_routine') {
      // 日常活动：浅灰简短行
      const simTime = data.sim_hour != null
        ? `${Math.floor(data.sim_hour)}:${String(Math.round((data.sim_hour % 1) * 60)).padStart(2, '0')}`
        : ''
      const simDate = data.age_days != null
        ? (isZh ? `第${data.age_days}天` : `D${data.age_days}`)
        : ''
      return (
        <div key={i} className="log-system" style={{ opacity: 0.5 }}>
          <span className="time">{time}</span>
          {(simDate || simTime) && (
            <span className="text-[10px] text-emerald-400/40 mr-1.5">{simDate}{simTime ? ` ${simTime}` : ''}</span>
          )}
          <span className="text-[#888]">{tk(data.display_name?.replace(/_/g, ' ') || data.event_name || '')}</span>
          {data.changes && Object.keys(data.changes).length > 0 && (
            <span className="text-[10px] text-[#555] ml-1">
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
  const renderCriticalEvents = () => {
    if (state.criticals.length === 0) return null
    return state.criticals.map((evt, i) => {
      const isNaming = evt.event_name === 'naming_ceremony'
      const isProcessing = state.intervening === evt.event_name
      return (
        <div key={i} className="cradle-critical-card">
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
            <span className="text-sm font-medium text-yellow-400">{tk(evt.event_display || evt.event_name?.replace(/_/g, ' ') || '')}</span>
          </div>
          <div className="text-xs text-[#999] mb-3">{evt.description}</div>
          {isNaming && (
            <input
              type="text"
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              placeholder={isZh ? '输入名字...' : 'Enter name...'}
              className="w-full mb-3 px-3 py-1.5 bg-[#333] border border-[#555] rounded-lg text-sm text-white placeholder:text-[#666] outline-none focus:border-primary"
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

  const canGrow = babyStatus && !state.running && !state.paused && state.criticals.length === 0 && !allPhasesComplete && !state.growComplete
  const canResume = state.paused && state.criticals.length === 0
  const isPaused = state.paused && state.criticals.length > 0

  const consoleHeader = (
    <div className="flex items-center gap-2.5 text-[11px]">
      <span className="text-[#666]">
        {isZh ? '阶段' : 'Phase'} {(babyStatus?.current_phase?.index ?? 0) + 1}/12
      </span>
      <span className="w-px h-3 bg-[#444]" />
      <span className="text-primary font-medium capitalize">{tk(babyStatus?.current_phase?.name || '')}</span>
      <span className="w-px h-3 bg-[#444]" />
      <div className="flex items-center gap-[5px]">
        <span className={cn(
          "w-1.5 h-1.5 rounded-full",
          state.running ? "step-dot-running" :
          state.criticals.length > 0 ? "bg-yellow-400 animate-pulse" :
          (allPhasesComplete || state.growComplete) ? "bg-[#28C840]" :
          state.paused ? "bg-yellow-400" :
          state.lifelineActive ? "dot-lifeline" :
          "bg-[#555]"
        )} />
        <span className={cn("text-[#666]", state.lifelineActive && !state.running && !state.paused && "text-emerald-400/70")}>
          {state.running ? (isZh ? '进行中' : 'Running') :
           state.criticals.length > 0 ? (isZh ? '待回应' : 'Awaiting') :
           (allPhasesComplete || state.growComplete) ? (isZh ? '已完成' : 'Done') :
           state.paused ? (isZh ? '已暂停' : 'Paused') :
           state.lifelineActive ? (isZh ? '生命线' : 'Alive') :
           (isZh ? '待命' : 'Idle')}
        </span>
      </div>
    </div>
  )

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* 左面板 */}
      <div className="w-[45%] shrink-0 bg-background border-r border-border flex flex-col p-5 gap-3">
        <div className="shrink-0">
          <div className="flex items-center gap-3 px-2">
            <button
              className="text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => { navigate('/cradle'); setBabyStatus(null); setReadiness(null) }}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" /></svg>
            </button>
            <div className="relative">
              <Avatar><AvatarFallback className="text-[10px] font-mono">{shortId(selectedId)}</AvatarFallback></Avatar>
              {state.lifelineActive && (
                <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full dot-lifeline border-2 border-background" title={isZh ? '生命线活跃' : 'Lifeline active'} />
              )}
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="font-heading text-xl font-semibold capitalize">
                  {babyStatus?.name || tk(babyStatus?.species || selectedBirth?.species || '')}
                </h1>
                {readiness && (
                  <div className="flex items-center gap-2 text-[10px]">
                    <span className={cn(
                      "px-1.5 py-0.5 rounded-full font-semibold",
                      readiness.ready ? "bg-green-500/10 text-green-400" : "bg-yellow-500/10 text-yellow-400",
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
            {canGrow && (
              <Button size="sm" onClick={() => startGrow(false)}>
                {isZh ? '开始成长' : 'Start Growing'}
              </Button>
            )}
            {canResume && (
              <Button size="sm" onClick={() => startGrow(true)}>
                {isZh ? '继续成长' : 'Continue Growing'}
              </Button>
            )}
            {state.running && (
              <span className="text-xs text-muted-foreground flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full step-dot-running" />
                {isZh ? '成长中...' : 'Growing...'}
              </span>
            )}
            {isPaused && (
              <span className="text-xs text-yellow-400 flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
                {isZh ? '等待回应...' : 'Awaiting response...'}
              </span>
            )}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          <div className="w-full">{renderStatus()}</div>
        </div>
      </div>

      {/* 右面板 */}
      <div className="flex-1 flex flex-col gap-3 p-5">

        {/* 交互工具栏 */}
        {babyStatus && (
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
                if (socialSession) { endSocial() }
                setChatTargetOpen(false)
                setTimeout(() => chatInputRef.current?.focus(), 100)
              }}
            >
              <MessageCircle className="size-3.5" />
              {isZh ? `与${babyStatus.name || '宝宝'}互动` : `Interact with ${babyStatus.name || 'baby'}`}
            </Button>

            {/* 按钮2: 多宝宝社交互动 */}
            {cradleBabies.length >= 2 && (
              <div className="relative" ref={chatTargetRef}>
                <Button
                  size="sm"
                  variant={(chatMode === 'social' || chatTargetOpen) ? "default" : "outline"}
                  className="gap-1.5"
                  onClick={() => {
                    if (socialSession) {
                      // 正在社交，点击切换下拉
                      setChatTargetOpen(o => !o)
                    } else {
                      setChatTargetOpen(o => !o)
                      if (!chatTargetOpen) setSocialSelected([])
                    }
                  }}
                >
                  <Users className="size-3.5" />
                  {socialSession
                    ? (socialSession.participants?.map(p => p.name).join(' & '))
                    : (isZh ? '多宝宝互动' : 'Multi-baby Interact')
                  }
                  <ChevronDown className={cn("size-3 transition-transform", chatTargetOpen && "rotate-180")} />
                </Button>

                {chatTargetOpen && !socialSession && (
                  <div className="absolute top-full left-0 mt-1.5 w-80 bg-popover border border-border rounded-xl shadow-xl z-50 overflow-hidden">
                    <div className="px-3 pt-3 pb-2 text-[11px] text-muted-foreground">
                      {isZh ? '选择参与对话的宝宝（至少 2 个）' : 'Select babies (min 2)'}
                    </div>
                    <div className="max-h-64 overflow-y-auto">
                      {cradleBabies.map(b => {
                        const initial = (b.name || b.baby_id || '?')[0].toUpperCase()
                        const eligible = (b.current_phase || 0) >= 8
                        const checked = socialSelected.includes(b.baby_id)
                        return (
                          <button
                            key={b.baby_id}
                            disabled={!eligible}
                            className={cn(
                              "w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors",
                              eligible ? "hover:bg-accent" : "opacity-50 cursor-not-allowed",
                              checked && "bg-primary/5",
                            )}
                            onClick={() => {
                              if (!eligible) return
                              setSocialSelected(prev =>
                                checked ? prev.filter(id => id !== b.baby_id) : [...prev, b.baby_id]
                              )
                            }}
                          >
                            <Avatar className={cn("transition-colors", checked && "ring-2 ring-primary")}>
                              <AvatarFallback className={cn("text-xs font-mono", checked && "bg-primary/20 text-primary")}>
                                {initial}
                              </AvatarFallback>
                            </Avatar>
                            <div className="flex-1 min-w-0">
                              <div className="text-sm font-medium text-popover-foreground truncate">{b.name || b.baby_id}</div>
                              <div className="text-[11px] text-muted-foreground">
                                {isZh ? '阶段' : 'Phase'} {(b.current_phase || 0) + 1} · {tk(PHASE_NAMES[b.current_phase || 0] || '')}
                                {!eligible && (isZh ? ' · 需 Phase 9+' : ' · Requires Phase 9+')}
                              </div>
                            </div>
                            {eligible && (
                              <div className={cn(
                                "w-4 h-4 rounded border flex items-center justify-center text-[10px]",
                                checked ? "border-primary bg-primary text-primary-foreground" : "border-border",
                              )}>
                                {checked && '\u2713'}
                              </div>
                            )}
                          </button>
                        )
                      })}
                    </div>
                    <div className="p-2 border-t border-border flex items-center gap-2">
                      <Button
                        size="sm"
                        className="flex-1"
                        onClick={() => { startSocial(); setChatMode('social'); setChatTargetOpen(false) }}
                        disabled={socialSelected.length < 2 || socialLoading}
                      >
                        {socialLoading ? '...' : (isZh ? `开始对话 (${socialSelected.length})` : `Start Chat (${socialSelected.length})`)}
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => setChatTargetOpen(false)}>
                        {isZh ? '取消' : 'Cancel'}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* 社交控制按钮 */}
            {socialSession && (
              <>
                <Button size="sm" variant="outline" className="gap-1" onClick={socialTurn} disabled={socialLoading}>
                  {socialLoading ? '...' : (isZh ? '下一轮' : 'Next Turn')}
                </Button>
                <Button size="sm" variant="outline" className="gap-1 text-red-400 hover:text-red-300" onClick={() => { endSocial(); setChatMode(false) }} disabled={socialLoading}>
                  {isZh ? '结束' : 'End'}
                </Button>
              </>
            )}
          </div>
        )}

        {/* ── 对话面板 + 控制台布局 ── */}
        {(chatMode || socialSession) ? (
          <>
            {/* 对话面板 (4/5) */}
            <div className="flex-[4] flex flex-col bg-card border border-border rounded-lg overflow-hidden min-h-0">
              {/* 宝宝资料卡 */}
              {chatMode === 'single' && babyStatus && (
                <div className="shrink-0 border-b border-border p-4">
                  <div className="flex items-start gap-3">
                    <Avatar size="lg">
                      <AvatarFallback className="text-xs font-mono">{shortId(selectedId)}</AvatarFallback>
                    </Avatar>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm">{babyStatus.name || selectedId}</span>
                        <span className="text-xs text-muted-foreground">@{babyStatus.species}</span>
                        <span className="text-[10px] px-1.5 py-0.5 bg-primary/10 text-primary rounded-full capitalize">
                          {tk(babyStatus.expression_mode || '')}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {tk(babyStatus.current_phase?.name || '')} · {babyStatus.age_days}{isZh ? '天' : 'd'} · {tk(babyStatus.attachment_style || 'forming')}
                      </div>
                    </div>
                  </div>
                  {(babyStatus.temperament || babyStatus.tendencies?.length > 0) && (
                    <div className="mt-2.5 p-2.5 bg-muted rounded-md text-xs text-muted-foreground">
                      <div className="text-[10px] font-medium text-muted-foreground/70 mb-1">{isZh ? '简介' : 'Bio'}</div>
                      {babyStatus.temperament && <span className="capitalize">{babyStatus.temperament}</span>}
                      {babyStatus.tendencies?.length > 0 && (
                        <span>{babyStatus.temperament ? ' · ' : ''}{babyStatus.tendencies.join(' · ')}</span>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* 社交资料卡 */}
              {chatMode === 'social' && socialSession && (
                <div className="shrink-0 border-b border-border p-4">
                  <div className="flex items-center gap-3">
                    <AvatarGroup>
                      {socialSession.participants?.slice(0, 4).map((p, i) => (
                        <Avatar key={i}>
                          <AvatarFallback className="text-[10px] font-mono">{shortId(p.baby_id)}</AvatarFallback>
                        </Avatar>
                      ))}
                    </AvatarGroup>
                    <div className="flex-1">
                      <div className="font-semibold text-sm">
                        {socialSession.participants?.map(p => p.name).join(' & ')}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {isZh ? '社交互动' : 'Social Interaction'} · {socialSession.participants?.length} {isZh ? '位参与者' : 'participants'}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* 对话消息区 */}
              <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2" ref={chatScrollRef}>
                {chatMode === 'single' && (() => {
                  const chatEvents = new Set(['interaction', 'interaction_pending', 'heartbeat_initiative', 'heartbeat_ignored'])
                  const chatMessages = state.logs.filter(l => chatEvents.has(l.event))
                  if (chatMessages.length === 0) {
                    return (
                      <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-2">
                        <MessageCircle className="size-10 opacity-30" />
                        <span className="text-sm">{isZh ? '与宝宝互动，了解他的世界' : 'Interact with baby, explore their world'}</span>
                      </div>
                    )
                  }
                  return chatMessages.map((entry, i) => {
                    const babyName = babyStatus?.name || shortId(selectedId)

                    // 心跳主动行为
                    if (entry.event === 'heartbeat_initiative') {
                      const d = entry.data
                      const isAvoidance = d.behavior_type === 'avoidance'
                      return (
                        <div key={i} className="flex items-start gap-2">
                          <Avatar className="shrink-0">
                            <AvatarFallback className="text-[10px] font-mono">{shortId(selectedId)}</AvatarFallback>
                          </Avatar>
                          <div className="max-w-[80%]">
                            <div className="flex items-center gap-1.5 mb-1">
                              <span className="text-[11px] font-medium text-foreground">{babyName}</span>
                              <span className="text-[10px] text-muted-foreground">{entry.time}</span>
                              <span className={cn(
                                "text-[9px] px-1.5 py-0.5 rounded-full font-medium",
                                isAvoidance ? "bg-slate-500/15 text-slate-400" : "bg-amber-500/15 text-amber-500",
                              )}>{isAvoidance ? (isZh ? '回避' : 'avoidance') : d.trigger || (isZh ? '主动' : 'initiative')}</span>
                            </div>
                            <div className={cn(
                              "px-3.5 py-2 rounded-lg rounded-tl-sm text-sm italic",
                              isAvoidance ? "bg-slate-500/10 text-slate-300 border border-slate-500/20" : "bg-amber-500/10 text-amber-900 dark:text-amber-200 border border-amber-500/20",
                            )}>
                              {d.expression}
                            </div>
                            {d.parent_hint && (
                              <div className="text-[10px] text-muted-foreground mt-1">{d.parent_hint}</div>
                            )}
                            {!isAvoidance && chatMessages[i + 1]?.event !== 'heartbeat_ignored' && (
                              <button
                                className="text-[10px] text-primary hover:underline mt-1 cursor-pointer"
                                onClick={() => { chatInputRef.current?.focus() }}
                              >{isZh ? '回应' : 'Respond'}</button>
                            )}
                          </div>
                        </div>
                      )
                    }

                    // 心跳被忽略反应
                    if (entry.event === 'heartbeat_ignored') {
                      const d = entry.data
                      return (
                        <div key={i} className="flex items-start gap-2 opacity-60">
                          <Avatar className="shrink-0">
                            <AvatarFallback className="text-[10px] font-mono">{shortId(selectedId)}</AvatarFallback>
                          </Avatar>
                          <div className="max-w-[80%]">
                            <div className="flex items-center gap-1.5 mb-1">
                              <span className="text-[11px] font-medium text-muted-foreground">{babyName}</span>
                              <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">{isZh ? '未回应' : 'ignored'}</span>
                              {d.consecutive_ignores > 1 && <span className="text-[9px] text-red-400">x{d.consecutive_ignores}</span>}
                            </div>
                            <div className="px-3.5 py-2 rounded-lg rounded-tl-sm bg-muted/50 text-muted-foreground text-sm italic">
                              {d.reaction}
                            </div>
                          </div>
                        </div>
                      )
                    }

                    const isPending = entry.event === 'interaction_pending'
                    return (
                    <div key={i} className="flex flex-col gap-3">
                      {/* 用户消息：靠右 */}
                      <div className="flex justify-end items-start gap-2">
                        <div className="max-w-[75%] flex flex-col items-end">
                          <div className="h-8 flex items-center gap-1.5">
                            <span className="text-[10px] text-muted-foreground">{entry.time}</span>
                            <span className="text-[11px] font-medium text-foreground">{isZh ? '你' : 'You'}</span>
                          </div>
                          <div className={cn(
                            "px-3.5 py-2 rounded-lg rounded-tr-sm text-sm",
                            entry.data.action_type === 'touch'
                              ? "bg-amber-500/10 text-amber-700 dark:text-amber-300 italic border border-amber-500/20"
                              : "bg-primary/15 text-primary",
                          )}>
                            {entry.data.action_type === 'touch' ? (
                              <span className="flex items-center gap-1.5">
                                <span>{entry.data.emoji || '✋'}</span>
                                <span>{entry.data.parent_message}</span>
                                <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500/15 not-italic font-medium">{isZh ? '动作' : 'Action'}</span>
                              </span>
                            ) : entry.data.parent_message}
                          </div>
                        </div>
                        <Avatar className="shrink-0">
                          <AvatarFallback className="text-[10px] font-semibold bg-primary/20 text-primary">U</AvatarFallback>
                        </Avatar>
                      </div>
                      {/* 宝宝回复：靠左 */}
                      {isPending ? (
                        <div className="flex items-start gap-2">
                          <Avatar className="shrink-0">
                            <AvatarFallback className="text-[10px] font-mono">{shortId(selectedId)}</AvatarFallback>
                          </Avatar>
                          <div>
                            <div className="h-8 flex items-center gap-1.5">
                              <span className="text-[11px] font-medium text-foreground">{babyName}</span>
                            </div>
                            <div className="px-3.5 py-2 rounded-lg rounded-tl-sm bg-muted text-muted-foreground text-sm">
                              <span className="animate-pulse">{isZh ? '思考中...' : 'Thinking...'}</span>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start gap-2">
                          <Avatar className="shrink-0">
                            <AvatarFallback className="text-[10px] font-mono">{shortId(selectedId)}</AvatarFallback>
                          </Avatar>
                          <div className="max-w-[75%]">
                            <div className="h-8 flex items-center gap-1.5">
                              <span className="text-[11px] font-medium text-foreground">{babyName}</span>
                              <span className="text-[10px] text-muted-foreground">{entry.replyTime || entry.time}</span>
                            </div>
                            <div className="px-3.5 py-2 rounded-lg rounded-tl-sm bg-muted text-foreground text-sm">
                              <div className="italic">{entry.data.baby_response}</div>
                              {entry.data.emotional_tone && (
                                <div className="text-[10px] text-muted-foreground mt-1 not-italic">[{entry.data.emotional_tone}]</div>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )})

                })()}

                {chatMode === 'social' && (() => {
                  if (socialHistory.length === 0) {
                    return (
                      <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-2">
                        <Users className="size-10 opacity-30" />
                        <span className="text-sm">{isZh ? '宝宝们的互动空间，点击「下一轮」开始' : 'Interaction space — click "Next Turn" to begin'}</span>
                      </div>
                    )
                  }
                  return socialHistory.map((msg, i) => {
                    if (msg.role === 'parent') {
                      return (
                        <div key={i} className="flex justify-end items-start gap-2">
                          <div className="max-w-[75%] flex flex-col items-end">
                            <div className="h-8 flex items-center gap-1.5">
                              <span className="text-[10px] text-muted-foreground">{msg.time || ''}</span>
                              <span className="text-[11px] font-medium text-foreground">{isZh ? '你' : 'You'}</span>
                            </div>
                            <div className="px-3.5 py-2 rounded-lg rounded-tr-sm bg-primary/15 text-primary text-sm">
                              {msg.content}
                            </div>
                          </div>
                          <Avatar className="shrink-0">
                            <AvatarFallback className="text-[10px] font-semibold bg-primary/20 text-primary">U</AvatarFallback>
                          </Avatar>
                        </div>
                      )
                    }
                    if (msg.role === 'system') {
                      return (
                        <div key={i} className="text-center text-xs text-muted-foreground py-2">{msg.content}</div>
                      )
                    }
                    const participant = socialSession?.participants?.find(p => p.baby_id === msg.baby_id)
                    return (
                      <div key={i} className="flex items-start gap-2">
                        <Avatar className="shrink-0">
                          <AvatarFallback className="text-[10px] font-mono">{shortId(msg.baby_id)}</AvatarFallback>
                        </Avatar>
                        <div className="max-w-[75%]">
                          <div className="h-8 flex items-center gap-1.5">
                            <span className="text-[11px] font-medium text-foreground">{msg.name}</span>
                            <span className="text-[10px] text-muted-foreground">{msg.time || ''}</span>
                          </div>
                          <div className="px-3.5 py-2 rounded-lg rounded-tl-sm bg-muted text-foreground text-sm">
                            <div className="italic">{msg.baby_response}</div>
                            {msg.emotional_tone && (
                              <div className="text-[10px] text-muted-foreground mt-1 not-italic">[{msg.emotional_tone}]</div>
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  })
                })()}
              </div>

              {/* 肢体动作面板 */}
              {touchPanelOpen && !socialSession && touchActions?.actions && (
                <div className="shrink-0 border-t border-border bg-muted/30 max-h-[240px] overflow-y-auto">
                  <div className="p-3 flex flex-col gap-2.5">
                    {Object.entries(touchActions.actions).map(([cat, group]) => (
                      <div key={cat}>
                        <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
                          {group.emoji} {isZh ? group.label_zh : group.label_en}
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {group.actions.map((a) => (
                            <button
                              key={a.key}
                              className="px-2.5 py-1.5 text-xs rounded-full bg-background border border-border hover:bg-primary/10 hover:border-primary/30 hover:text-primary transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                              disabled={state.interacting}
                              onClick={() => sendInteraction(a.key, isZh ? a.label_zh : a.label_en, a.emoji)}
                            >
                              {a.emoji} {isZh ? a.label_zh : a.label_en}
                            </button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 对话输入 */}
              <div className="shrink-0 border-t border-border p-3 flex items-center gap-2">
                {/* 肢体互动按钮（仅单人对话时显示） */}
                {!socialSession && (
                  <button
                    className={cn(
                      "w-9 h-9 rounded-md flex items-center justify-center transition-colors shrink-0",
                      touchPanelOpen
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground hover:bg-muted/80",
                      "cursor-pointer",
                    )}
                    onClick={() => {
                      if (!touchActions) loadTouchActions()
                      setTouchPanelOpen(v => !v)
                    }}
                    title={isZh ? '肢体互动' : 'Touch interaction'}
                  >
                    <Hand className="size-4" />
                  </button>
                )}
                <Input
                  ref={chatInputRef}
                  type="text"
                  className="flex-1 h-9 rounded-md"
                  placeholder={
                    socialSession
                      ? (isZh ? '对孩子们说点什么...' : 'Say something to the kids...')
                      : (isZh ? '说点什么...' : 'Say something...')
                  }
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      if (socialSession) { socialParentMsg(chatInput); setChatInput('') }
                      else sendInteraction()
                    }
                  }}
                  disabled={state.interacting || socialLoading}
                />
                <button
                  className={cn(
                    "w-9 h-9 rounded-md flex items-center justify-center transition-colors shrink-0",
                    chatInput.trim() && !state.interacting && !socialLoading
                      ? "bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer"
                      : "bg-muted text-muted-foreground cursor-not-allowed",
                  )}
                  onClick={() => {
                    if (socialSession) { socialParentMsg(chatInput); setChatInput('') }
                    else sendInteraction()
                  }}
                  disabled={(state.interacting || socialLoading) || !chatInput.trim()}
                >
                  <Send className="size-4" />
                </button>
              </div>
            </div>

            {/* 控制台 (1/5) */}
            <ConsolePanel
              ref={logRefCb}
              className="flex-[1] min-h-[120px]"
              header={consoleHeader}
              footer={state.criticals.length > 0 && (
                <div className="shrink-0 border-t border-[#333] bg-[#222] p-2 max-h-[60%] overflow-y-auto flex flex-col gap-2">
                  {renderCriticalEvents()}
                </div>
              )}
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
            </ConsolePanel>
          </>
        ) : (
          /* ── 无对话时：控制台全屏 ── */
          <ConsolePanel
            ref={logRefCb}
            className="flex-1"
            headerHeight={38}
            header={consoleHeader}
            footer={state.criticals.length > 0 && (
              <div className="shrink-0 border-t border-[#333] bg-[#222] p-3 max-h-[40%] overflow-y-auto flex flex-col gap-3">
                {renderCriticalEvents()}
              </div>
            )}
          >
            {state.logs.length === 0 && (
              <div className="log-system">
                <span className="blink-dot" />
                {loadingHistory
                  ? (isZh ? '正在加载历史记录...' : 'Loading history...')
                  : (isZh ? '点击「开始成长」开始养育。' : 'Click "Start Growing" to begin nurturing.')}
              </div>
            )}
            {state.logs.map(renderLog)}
          </ConsolePanel>
        )}
      </div>
    </div>
  )
}
