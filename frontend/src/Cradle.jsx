/**
 * [INPUT]: react, react-router-dom, ../i18n, shadcn/ui (Button, Card), ../lib/utils
 * [OUTPUT]: Cradle 组件 — 摇篮养育界面
 * [POS]: 摇篮 tab 页面，消费 SSE 流驱动婴儿成长模拟
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */
import { useState, useEffect, useRef, useReducer, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { translateKey } from './i18n'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

const API = 'http://localhost:8000'
const SPECIES_ICONS = { human: '\u{1F476}', dog: '\u{1F415}', cat: '\u{1F408}' }

const PHASE_NAMES = [
  'neonatal', 'sensory_awakening', 'body_discovery', 'object_permanence',
  'locomotion', 'first_word', 'language_explosion', 'why_phase',
  'social_budding', 'rule_understanding', 'abstract_beginning', 'independence',
]

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
}

function cradleReducer(state, action) {
  switch (action.type) {
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
      // 心跳事件：更新最后一条而非新增（避免刷屏）
      const heartbeatEvents = ['narrating', 'compiling', 'phase_completing']
      if (heartbeatEvents.includes(data.event) && data.elapsed && state.logs.length > 0 && state.logs[state.logs.length - 1].event === data.event) {
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
    case 'INTERACT_SENDING':
      return { ...state, interacting: true }
    case 'INTERACT_DONE': {
      const log = { time: getTime(), event: 'interaction', data: action.data }
      return { ...state, interacting: false, logs: [...state.logs, log] }
    }
    case 'INTERACT_ERROR':
      return { ...state, interacting: false }
    case 'INTERVENE_START':
      return { ...state, intervening: action.eventName }
    case 'INTERVENE_DONE': {
      const logs = [...state.logs, { time: getTime(), event: 'intervene_result', data: action.result }]
      const criticals = state.criticals.filter(c => c.event_name !== action.eventName)
      return { ...state, logs, criticals, intervening: null }
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
  const [admitting, setAdmitting] = useState(false)
  const [readiness, setReadiness] = useState(null)
  const [nameInput, setNameInput] = useState('')
  const [state, dispatch] = useReducer(cradleReducer, INIT)
  const logRef = useRef(null)

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [state.logs.length])

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
    if (!selectedId) { setBabyStatus(null); return }
    const inCradle = cradleBabies.some(b => b.baby_id === selectedId)
    if (inCradle) {
      loadStatus(selectedId)
      // 加载历史 SSE 事件
      fetch(`${API}/cradle/${selectedId}/events`)
        .then(r => r.json())
        .then(data => {
          if (data.events && data.events.length > 0) {
            const historicalLogs = data.events
              .filter(e => e.event !== 'narrating') // 过滤心跳
              .map(e => {
                const ts = e.ts ? new Date(e.ts * 1000).toLocaleTimeString('en-US', { hour12: false }) : ''
                return { time: ts, event: e.event, data: e }
              })
            dispatch({ type: 'LOAD_HISTORY', logs: historicalLogs })
          }
        })
        .catch(() => {})
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
        if (data.event === 'paused') {
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

  const sendInteraction = async () => {
    const msg = chatInput.trim()
    if (!msg || !selectedId || state.interacting) return
    setChatInput('')
    dispatch({ type: 'INTERACT_SENDING' })
    try {
      const r = await fetch(`${API}/cradle/${selectedId}/interact`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      })
      if (r.status === 409) {
        dispatch({ type: 'INTERACT_ERROR' })
        return
      }
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      dispatch({ type: 'INTERACT_DONE', data: { parent_message: msg, baby_response: data.baby_response, emotional_tone: data.emotional_tone, expression_mode: data.expression_mode } })
    } catch (e) {
      console.error('Interact failed:', e)
      dispatch({ type: 'INTERACT_ERROR' })
    }
  }

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
              <span className="text-2xl">{SPECIES_ICONS[baby.species] || '\u{1F9EC}'}</span>
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
      if (selectedBirth) {
        return (
          <div className="flex flex-col items-center justify-center flex-1 gap-4 p-6">
            <span className="text-5xl">{SPECIES_ICONS[selectedBirth.species] || '\u{1F9EC}'}</span>
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
      <div className="flex flex-col gap-3.5 p-6 pt-0">
        {/* 阶段进度 */}
        <Card>
          <CardHeader><CardTitle>{isZh ? '成长阶段' : 'Growth Phases'}</CardTitle></CardHeader>
          <CardContent>
            <div className="bg-muted rounded-2xl p-4 flex flex-col">
              {PHASE_NAMES.map((name, i) => {
                const isCurrent = i === phase.index
                const isDone = i < phase.index
                const isLast = i === PHASE_NAMES.length - 1
                return (
                  <div key={name} className="flex gap-3 min-h-[24px]">
                    <div className="flex flex-col items-center w-3 shrink-0">
                      <span className={cn(
                        "w-2 h-2 rounded-full bg-border shrink-0 z-[1] transition-all duration-300 mt-0.5",
                        isCurrent && "tl-dot-active",
                        isDone && "!bg-primary",
                      )} />
                      {!isLast && (
                        <div className={cn(
                          "w-px flex-1 bg-border transition-colors duration-500",
                          isDone && "bg-primary",
                          isCurrent && "bg-gradient-to-b from-primary to-border",
                        )} />
                      )}
                    </div>
                    <div className="flex items-baseline gap-2 pb-1">
                      <span className={cn(
                        "text-xs text-muted-foreground capitalize transition-colors duration-300",
                        isCurrent && "text-primary font-semibold",
                        isDone && "text-primary",
                      )}>{tk(name)}</span>
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

        {/* 家长档案 */}
        {s.parent_profile && s.parent_profile.total_interventions > 0 && (
          <Card>
            <CardHeader><CardTitle>{isZh ? '家长档案' : 'Parent Profile'}</CardTitle></CardHeader>
            <CardContent>
              <div className="bg-muted rounded-2xl p-4">
                <div className="flex flex-col divide-y divide-border text-sm">
                  {[
                    [isZh ? '响应度' : 'Responsiveness', `${(s.parent_profile.responsiveness * 100).toFixed(0)}%`],
                    [isZh ? '风格' : 'Style', <span className="capitalize">{tk(s.parent_profile.intervention_style || '')}</span>],
                    [isZh ? '介入次数' : 'Interventions', s.parent_profile.total_interventions],
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
        )}

        {/* 世界就绪度 */}
        {readiness && (
          <Card>
            <CardHeader><CardTitle>{isZh ? '入世就绪度' : 'World Readiness'}</CardTitle></CardHeader>
            <CardContent>
              <div className="flex flex-col gap-3">
                <div className={cn(
                  "text-center py-2 rounded-xl font-medium text-sm",
                  readiness.ready ? "bg-green-500/10 text-green-400" : "bg-yellow-500/10 text-yellow-400",
                )}>
                  {readiness.ready ? (isZh ? '已准备好面对世界！' : 'Ready for the world!') : (isZh ? '尚未准备好' : 'Not yet ready')}
                </div>
                {readiness.hard && (
                  <div className="bg-muted rounded-2xl p-4">
                    <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">{isZh ? '必须达成' : 'REQUIRED'}</div>
                    {Object.entries(readiness.hard).map(([k, v]) => (
                      <div key={k} className="flex justify-between py-1 text-sm">
                        <span className="text-muted-foreground capitalize">{tk(k.replace(/_/g, ' '))}</span>
                        <span className={v.met ? "text-green-400" : "text-red-400"}>{v.met ? '\u2713' : '\u2717'}</span>
                      </div>
                    ))}
                  </div>
                )}
                {readiness.soft && (
                  <div className="bg-muted rounded-2xl p-4">
                    <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">{isZh ? '加分项' : 'DESIRABLE'}</div>
                    {Object.entries(readiness.soft).map(([k, v]) => (
                      <div key={k} className="flex justify-between py-1 text-sm">
                        <span className="text-muted-foreground capitalize">{tk(k.replace(/_/g, ' '))}</span>
                        <span className={v.met ? "text-green-400" : "text-yellow-400"}>{v.met ? '\u2713' : '\u2014'}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}
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
          {data.baby_reaction && <div className="cradle-reaction">{data.baby_reaction}</div>}
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
          <div className="cradle-reaction">{data.reaction}</div>
          {data.growth_signal && <div className="text-[10px] text-primary/60 mt-0.5">{data.growth_signal}</div>}
          {data.new_fear && <div className="text-[10px] text-red-400/80 mt-0.5">{isZh ? '新恐惧' : 'New fear'}: {data.new_fear}</div>}
          {data.new_preference && <div className="text-[10px] text-blue-400/80 mt-0.5">{isZh ? '新偏好' : 'New pref'}: {data.new_preference}</div>}
        </div>
      )
    }

    if (event === 'critical_event') {
      return (
        <div key={i} className="log-error">
          <span className="time">{time}</span>
          <span className="tag">{isZh ? '关键' : 'CRITICAL'}</span>
          <span className="font-medium">{tk(data.event_display || data.event_name?.replace(/_/g, ' ') || '')}</span>
          <div className="text-[#aaa] text-[11px] mt-0.5">{data.description}</div>
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
            <div className="cradle-reaction mt-1">{summary.summary}</div>
          )}
          {data.next_phase && (
            <div className="text-[10px] text-primary/60 mt-0.5">{isZh ? '下一阶段' : 'Next'}: {tk(data.next_phase || data.next_phase_name || '')}</div>
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
          <div className="cradle-reaction">{data.reaction || data.parent_response_reaction || ''}</div>
          {data.developmental_impact && <div className="text-[10px] text-primary/60 mt-0.5">{data.developmental_impact}</div>}
        </div>
      )
    }

    if (event === 'interaction') {
      const sc = data.state_changes
      return (
        <div key={i} className="flex flex-col gap-1.5 my-1.5 mx-1">
          <div className="flex justify-end">
            <div className="px-3 py-1.5 rounded-xl bg-primary/20 text-primary text-xs max-w-[80%]">
              {data.parent_message}
            </div>
          </div>
          <div className="flex justify-start">
            <div className="px-3 py-1.5 rounded-xl bg-[#2a2a2a] text-[#ccc] text-xs italic max-w-[80%]">
              {data.baby_response}
              {sc && Object.keys(sc).length > 0 && (
                <div className="mt-1 pt-1 border-t border-[#444] text-[10px] not-italic">
                  {sc.new_preference && <span className="text-green-400">+{isZh ? '偏好' : 'pref'}: {sc.new_preference} </span>}
                  {sc.new_comfort_source && <span className="text-blue-400">+{isZh ? '安慰' : 'comfort'}: {sc.new_comfort_source} </span>}
                  {sc.fear_reduced && <span className="text-green-400">-{isZh ? '恐惧' : 'fear'}: {sc.fear_reduced} </span>}
                  {sc.new_fear && <span className="text-red-400">+{isZh ? '恐惧' : 'fear'}: {sc.new_fear} </span>}
                </div>
              )}
            </div>
          </div>
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

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* 左面板 */}
      <div className="w-[496px] shrink-0 bg-background border-r border-border flex flex-col">
        <div className="shrink-0 px-6 pt-6 pb-3">
          <div className="flex items-center gap-3 px-2">
            <button
              className="text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => { navigate('/cradle'); setBabyStatus(null); setReadiness(null) }}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" /></svg>
            </button>
            <span className="text-2xl leading-none">{SPECIES_ICONS[babyStatus?.species || selectedBirth?.species] || '\u{1F9EC}'}</span>
            <div className="flex-1">
              <h1 className="font-heading text-xl font-semibold capitalize">
                {babyStatus?.name || tk(babyStatus?.species || selectedBirth?.species || '')}
              </h1>
              {babyStatus && (
                <p className="text-xs text-muted-foreground">
                  {tk(babyStatus.current_phase?.name || '')} · {babyStatus.age_days}{isZh ? '天' : 'd'}
                </p>
              )}
            </div>
            {babyStatus && <span className="text-[10px] text-muted-foreground font-mono">{selectedId}</span>}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          <div className="w-full max-w-md">{renderStatus()}</div>
        </div>
      </div>

      {/* 右面板 */}
      <div className="flex-1 flex flex-col gap-3 p-3 pl-0">
        <div className="shrink-0 flex items-center gap-2 px-1">
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
          {(allPhasesComplete || state.growComplete) && (
            <Button size="sm" variant="outline" onClick={checkReadiness}>
              {isZh ? '检查就绪度' : 'Check Readiness'}
            </Button>
          )}
          {eligibleForSocial.length >= 2 && !state.running && !socialSession && (
            <Button size="sm" variant="outline" onClick={() => { setShowSocialSelector(true); setSocialSelected([]) }}>
              {isZh ? '社交' : 'Social'}
            </Button>
          )}
          {socialSession && (
            <>
              <Button size="sm" onClick={socialTurn} disabled={socialLoading}>
                {socialLoading ? '...' : (isZh ? '下一轮' : 'Next Turn')}
              </Button>
              <Button size="sm" variant="outline" onClick={endSocial} disabled={socialLoading}>
                {isZh ? '结束' : 'End'}
              </Button>
              <span className="text-xs text-muted-foreground">
                {isZh ? '社交中' : 'Social'} ({socialSession.participants?.map(p => p.name).join(', ')})
              </span>
            </>
          )}
        </div>

        {/* 社交选择器 */}
        {showSocialSelector && (
          <div className="shrink-0 mx-1 p-3 bg-[#222] rounded-lg border border-[#444] flex flex-col gap-2">
            <div className="text-xs text-muted-foreground">{isZh ? '选择参与社交的婴儿（至少 2 个，Phase 9+）' : 'Select babies for social (min 2, Phase 9+)'}</div>
            <div className="flex flex-wrap gap-2">
              {eligibleForSocial.map(b => (
                <label key={b.baby_id} className={cn(
                  "flex items-center gap-1.5 px-2 py-1 rounded border text-xs cursor-pointer",
                  socialSelected.includes(b.baby_id) ? "border-primary bg-primary/10 text-primary" : "border-[#555] text-[#aaa]",
                )}>
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={socialSelected.includes(b.baby_id)}
                    onChange={(e) => {
                      setSocialSelected(prev =>
                        e.target.checked ? [...prev, b.baby_id] : prev.filter(id => id !== b.baby_id)
                      )
                    }}
                  />
                  {SPECIES_ICONS[b.species] || ''} {b.name || b.baby_id}
                </label>
              ))}
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={startSocial} disabled={socialSelected.length < 2 || socialLoading}>
                {isZh ? '开始' : 'Start'}
              </Button>
              <Button size="sm" variant="outline" onClick={() => setShowSocialSelector(false)}>
                {isZh ? '取消' : 'Cancel'}
              </Button>
            </div>
          </div>
        )}

        <div className="flex-1 flex flex-col bg-[#1C1C1C] rounded-xl overflow-hidden shadow-[0_4px_24px_rgba(0,0,0,0.3),0_0_0_0.5px_rgba(255,255,255,0.08)_inset]">
          <div className="h-[38px] bg-[#2D2D2D] border-b border-[#1a1a1a] flex items-center px-3.5 shrink-0">
            <div className="flex items-center gap-2.5 text-[11px] mx-auto">
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
                  "bg-[#555]"
                )} />
                <span className="text-[#666]">
                  {state.running ? (isZh ? '进行中' : 'Running') :
                   state.criticals.length > 0 ? (isZh ? '待回应' : 'Awaiting') :
                   (allPhasesComplete || state.growComplete) ? (isZh ? '已完成' : 'Done') :
                   state.paused ? (isZh ? '已暂停' : 'Paused') :
                   (isZh ? '待命' : 'Idle')}
                </span>
              </div>
            </div>
          </div>

          <div className="console" ref={logRef}>
            {state.logs.length === 0 && !socialSession && (
              <div className="log-system">
                <span className="blink-dot" />
                {isZh ? '点击「开始成长」开始养育。' : 'Click "Start Growing" to begin nurturing.'}
              </div>
            )}
            {state.logs.map(renderLog)}

            {/* 社交会话历史 */}
            {socialHistory.map((msg, i) => {
              if (msg.role === 'parent') {
                return (
                  <div key={`social-${i}`} className="flex justify-end my-1 mx-1">
                    <div className="px-3 py-1.5 rounded-xl bg-primary/20 text-primary text-xs max-w-[80%]">
                      {msg.content}
                    </div>
                  </div>
                )
              }
              if (msg.role === 'system') {
                return (
                  <div key={`social-${i}`} className="log-system text-center text-[10px] my-2">
                    {msg.content}
                  </div>
                )
              }
              // baby
              const participant = socialSession?.participants?.find(p => p.baby_id === msg.baby_id)
              const icon = SPECIES_ICONS[participant?.species] || ''
              return (
                <div key={`social-${i}`} className="flex items-start gap-2 my-1.5 mx-1">
                  <div className="shrink-0 text-xs font-medium text-[#888] w-16 text-right pt-0.5">
                    {icon} {msg.name}
                  </div>
                  <div className="px-3 py-1.5 rounded-xl bg-[#2a2a2a] text-[#ccc] text-xs italic max-w-[70%]">
                    {msg.baby_response}
                    {msg.emotional_tone && <span className="ml-1.5 not-italic text-[10px] text-[#666]">[{msg.emotional_tone}]</span>}
                  </div>
                </div>
              )
            })}
          </div>

          {state.criticals.length > 0 && (
            <div className="shrink-0 border-t border-[#333] bg-[#222] p-3 max-h-[40%] overflow-y-auto flex flex-col gap-3">
              {renderCriticalEvents()}
            </div>
          )}

          {/* 对话输入：亲子 / 社交共用 */}
          {babyStatus && (!(state.running && !state.paused) || socialSession) && (
            <div className="shrink-0 border-t border-[#333] bg-[#222] p-2 flex gap-2">
              <input
                type="text"
                className="flex-1 bg-[#1a1a1a] border border-[#444] rounded-lg px-3 py-1.5 text-xs text-[#ddd] placeholder-[#666] outline-none focus:border-primary/50"
                placeholder={
                  socialSession
                    ? (isZh ? '对孩子们说...' : 'Talk to the children...')
                    : (isZh ? `对${babyStatus.name || '宝宝'}说...` : `Talk to ${babyStatus.name || 'baby'}...`)
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
              <Button
                size="sm" variant="outline"
                className="text-xs px-3"
                onClick={() => {
                  if (socialSession) { socialParentMsg(chatInput); setChatInput('') }
                  else sendInteraction()
                }}
                disabled={(state.interacting || socialLoading) || !chatInput.trim()}
              >
                {(state.interacting || socialLoading) ? '...' : (isZh ? '发送' : 'Send')}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
