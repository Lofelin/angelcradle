import { useState, useEffect, useRef, useReducer, useCallback } from 'react'
import messages, { translateKey } from './i18n'

const API = 'http://localhost:8000'

const SPECIES_ICONS = { human: '👶', dog: '🐕', cat: '🐈' }
const STAGE_KEYS = [
  'zygote', 'early_organogenesis', 'late_organogenesis',
  'early_neural', 'late_neural', 'fetal_movement', 'birth',
]

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

// Single reducer for all womb state — one SSE event = one render
function wombReducer(state, action) {
  switch (action.type) {
    case 'RESET':
      return { logs: [], stageProgress: {}, currentStage: '', statusText: '', babyState: null, running: true }
    case 'SSE_EVENT': {
      const { data, ts, t } = action
      const newLogs = [...state.logs, { time: ts, type: data.event || 'data', data }]
      let { stageProgress, currentStage, statusText, babyState, running } = state

      // Flatten LLM output into log lines
      if (data.event === 'stage' && data.status === 'done' && data.response && typeof data.response === 'object') {
        newLogs.push(...flattenToLogs(data.response, ts, data.stage))
      }
      if (data.event === 'stage' && data.status === 'maternal_response_done' && data.maternal_response && typeof data.maternal_response === 'object') {
        newLogs.push(...flattenToLogs(data.maternal_response, ts, 'MATERNAL'))
      }

      // Update progress
      if (data.event === 'offspring_fate') {
        babyState = { sex: data.sex, phenotype: data.phenotype, defects: data.defects, stillborn: data.stillborn, stages: {} }
      } else if (data.event === 'stage') {
        if (data.status === 'in_progress') {
          currentStage = data.stage
          statusText = t.developing(data.stage, data.gestation_day)
          stageProgress = { ...stageProgress, [data.stage]: 'active' }
        } else if (data.status === 'done') {
          stageProgress = { ...stageProgress, [data.stage]: 'done' }
          statusText = t.done(data.stage)
          if (babyState && data.response && typeof data.response === 'object') {
            babyState = { ...babyState, stages: { ...babyState.stages, [data.stage]: data.response } }
          }
        } else if (data.status === 'maternal_response') {
          statusText = t.maternal_responding
        } else if (data.status === 'failed') {
          stageProgress = { ...stageProgress, [data.stage]: 'failed' }
        }
      } else if (data.event === 'born') {
        if (babyState) {
          babyState = { ...babyState, id: data.baby.id, alive: data.alive, first_cry: data.baby.first_cry, tendencies: data.baby.genes?.expression }
        }
        statusText = data.alive ? `${t.born}!` : t.stillborn_label
      } else if (data.event === 'complete') {
        statusText = `${t.complete} — ${t.alive}: ${data.total_alive}/${data.total_conceived}`
      } else if (data.event === 'miscarriage') {
        statusText = t.miscarriage(data.message)
      }

      return { logs: newLogs, stageProgress, currentStage, statusText, babyState, running }
    }
    case 'CLOSE':
      return { ...state, running: false, logs: [...state.logs, { time: getTime(), type: 'system', text: action.text }] }
    case 'CLEAR_PROGRESS':
      return { ...state, stageProgress: {}, statusText: '', babyState: null }
    default:
      return state
  }
}

const INIT_STATE = { logs: [], stageProgress: {}, currentStage: '', statusText: '', babyState: null, running: false }

function App() {
  const [lang, setLang] = useState('en')
  const [tab, setTab] = useState('womb')
  const [species, setSpecies] = useState('human')
  const [speciesList, setSpeciesList] = useState([])
  const [state, dispatch] = useReducer(wombReducer, INIT_STATE)
  const consoleRef = useRef(null)

  const t = messages[lang]

  useEffect(() => {
    fetch(`${API}/species`)
      .then(r => r.json())
      .then(data => setSpeciesList(data.species))
      .catch(() => setSpeciesList(['human', 'dog', 'cat']))
  }, [])

  useEffect(() => {
    if (consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight
    }
  }, [state.logs.length])

  const conceive = useCallback(() => {
    dispatch({ type: 'RESET' })

    const source = new EventSource(`${API}/conceive/stream?species=${species}&lang=${lang}`)

    source.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        dispatch({ type: 'SSE_EVENT', data, ts: getTime(), t })
      } catch {
        // ignore parse errors
      }
    }

    source.onerror = () => {
      dispatch({ type: 'CLOSE', text: t.closed })
      source.close()
    }
  }, [species, t])

  const { logs, stageProgress, statusText, babyState, running } = state

  const renderLog = (entry, i) => {
    const { type, data, text, time } = entry

    if (type === 'system') {
      return <div key={i} className="log-system"><span className="time">{time}</span> {text}</div>
    }
    if (type === 'stage_data') {
      const tag = entry.tag ? translateKey(entry.tag, lang) : ''
      const colonIdx = text.indexOf(':')
      if (colonIdx > -1) {
        const rawKey = text.slice(0, colonIdx)
        const value = text.slice(colonIdx + 1)
        const translatedKey = rawKey.includes('.')
          ? rawKey.split('.').map(part => translateKey(part.trim(), lang)).join('.')
          : translateKey(rawKey, lang)
        return (
          <div key={i} className="log-stage-done">
            <span className="time">{time}</span>
            {tag && <span className="tag">{tag}</span>}
            <span style={{ color: '#2e7d32' }}>{translatedKey}:</span>
            <span style={{ color: '#555' }}>{value}</span>
          </div>
        )
      }
      return <div key={i} className="log-stage-done"><span className="time">{time}</span>{tag && <span className="tag">{tag}</span>} {text}</div>
    }
    if (type === 'raw') {
      return <div key={i} className="log-raw"><span className="time">{time}</span> {text}</div>
    }

    const event = data?.event || type

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

    if (event === 'miscarriage') {
      return <div key={i} className="log-error"><span className="time">{time}</span> {t.miscarriage(data.message)}</div>
    }

    if (event === 'environment') {
      const env = data.result
      const tk = (v) => translateKey(v, lang)
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
      const tk = (v) => translateKey(v, lang)
      return (
        <div key={i} className="log-fate">
          <span className="time">{time}</span>
          <span className="tag">{t.offspring} #{data.index}</span>
          {t.sex}: {tk(data.sex)} | {Object.entries(data.phenotype).map(([k, v]) => `${k}: ${tk(v)}`).join(' | ')}
          {data.defects.length > 0 && <span className="log-warn"> | {t.defects}: {data.defects.map(d => translateKey(d.replace(/_/g, ' '), lang)).join(', ')}</span>}
          {data.stillborn && <span className="log-error"> | {t.stillborn_label}</span>}
        </div>
      )
    }

    if (event === 'stage') {
      const tk = (v) => translateKey(v, lang)
      if (data.status === 'in_progress') {
        return (
          <div key={i} className="log-stage-start">
            <span className="time">{time}</span>
            <span className="tag">{t.stage} {data.stage_num}/7</span>
            {t.developing(tk(data.stage), data.gestation_day)}
          </div>
        )
      }
      if (data.status === 'done') {
        return (
          <div key={i} className="log-stage-done">
            <span className="time">{time}</span>
            ✓ <span className="tag">{t.stage} {data.stage_num}/7</span>
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
            ✓ <span className="tag">{t.maternal}</span>
            {t.done(tk('feedback'))}
          </div>
        )
      }
    }

    if (event === 'born') {
      const baby = data.baby
      return (
        <div key={i} className={`log-born ${data.alive ? '' : 'log-error'}`}>
          <span className="time">{time}</span>
          <span className="tag">{data.alive ? t.born : t.stillborn_label}</span>
          {t.id}: {baby.id} | {translateKey(baby.species, lang)} | {translateKey(baby.sex, lang)}
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
        </div>
      )
    }

    return null
  }

  const renderBabyState = () => {
    if (!babyState) return null
    const lastStage = Object.keys(babyState.stages || {}).pop()
    const lastResult = lastStage ? babyState.stages[lastStage] : null

    return (
      <div className="baby-state">
        <div className="baby-state-header">{t.fetal_status}</div>
        <div className="baby-state-row">
          <span className="baby-state-key">{t.sex}</span>
          <span className="baby-state-val">{translateKey(babyState.sex, lang)}</span>
        </div>
        {Object.entries(babyState.phenotype || {}).map(([k, v]) => (
          <div key={k} className="baby-state-row">
            <span className="baby-state-key">{translateKey(k, lang)}</span>
            <span className="baby-state-val">{translateKey(v, lang)}</span>
          </div>
        ))}
        {babyState.defects?.length > 0 && (
          <div className="baby-state-row">
            <span className="baby-state-key">{t.defects}</span>
            <span className="baby-state-val log-warn">{babyState.defects.map(d => translateKey(d.replace(/_/g, ' '), lang)).join(', ')}</span>
          </div>
        )}
        {babyState.id && (
          <div className="baby-state-row">
            <span className="baby-state-key">{t.id}</span>
            <span className="baby-state-val">{babyState.id}</span>
          </div>
        )}
        {babyState.first_cry && (
          <div className="baby-state-cry">
            <div className="baby-state-stage-label">{t.first_cry_label}</div>
            <div className="first-cry">{babyState.first_cry}</div>
          </div>
        )}
      </div>
    )
  }

  const renderLeftPanel = () => {
    if (!running && Object.keys(stageProgress).length === 0) {
      return (
        <>
          <div className="control-group">
            <label>{t.species}</label>
            <select value={species} onChange={e => setSpecies(e.target.value)}>
              {speciesList.map(s => <option key={s} value={s}>{translateKey(s, lang)}</option>)}
            </select>
          </div>
          <button className="conceive-btn" onClick={conceive}>{t.conceive}</button>
          <div className="info">{t.info.map((line, i) => <p key={i}>{line}</p>)}</div>
        </>
      )
    }

    return (
      <div className="progress-view">
        <div className="species-icon">{SPECIES_ICONS[species] || '🧬'}</div>
        <div className="progress-stages">
          {STAGE_KEYS.map((key) => {
            const s = stageProgress[key] || ''
            return (
              <div key={key} className={`progress-stage ${s}`}>
                <span className="progress-dot" />
                <div className="progress-bar-track">
                  <div className="progress-bar-fill" style={{ width: s === 'done' ? '100%' : s === 'active' ? '50%' : '0%' }} />
                </div>
                <span className="progress-label">{translateKey(key.replace(/_/g, ' '), lang)}</span>
              </div>
            )
          })}
        </div>
        <div className="progress-status">{statusText}</div>
        {renderBabyState()}
        {!running && (
          <button className="conceive-btn" onClick={() => dispatch({ type: 'CLEAR_PROGRESS' })}>{t.conceive}</button>
        )}
      </div>
    )
  }

  const renderWomb = () => (
    <div className="container">
      <div className={`panel left ${running || Object.keys(stageProgress).length > 0 ? 'expanded' : ''}`}>
        {renderLeftPanel()}
      </div>
      <div className="panel right">
        <div className="console-header">
          <span>{t.console}</span>
        </div>
        <div className="console" ref={consoleRef}>
          {logs.length === 0 && <div className="log-system"><span className="blink-dot" />{t.ready}</div>}
          {logs.map(renderLog)}
        </div>
      </div>
    </div>
  )

  const renderPlaceholder = (name) => (
    <div className="container">
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#333', fontSize: '24px' }}>
        {name}
      </div>
    </div>
  )

  return (
    <div className="app">
      <div className="notch">
        <img src={`/logo.svg?v=${Date.now()}`} alt={t.title} className="notch-logo" />
        <div className="notch-tabs">
          {['womb', 'cradle', 'world'].map((key, i) => (
            <span key={key} style={{ display: 'contents' }}>
              {i > 0 && <span className="notch-dot" />}
              <button className={`notch-btn ${tab === key ? 'active' : ''}`} onClick={() => setTab(key)}>
                {t.tabs[key]}
              </button>
            </span>
          ))}
        </div>
        <div className="notch-right">
          {(() => {
            const doneCount = Object.values(stageProgress).filter(s => s === 'done').length
            const failedCount = Object.values(stageProgress).filter(s => s === 'failed').length
            const currentStageName = state.currentStage ? translateKey(state.currentStage, lang) : ''
            const allDone = doneCount === 7
            const hasFailed = failedCount > 0
            const hasStarted = doneCount > 0 || running
            const statusClass = hasFailed ? 'failed' : allDone ? 'done' : running ? 'running' : 'idle'
            const statusText = !hasStarted ? t.step_ready : hasFailed ? t.step_failed : allDone ? t.step_done : running ? t.step_running : t.step_idle
            return (
              <div className="step-indicator">
                <span className="step-num">Step {doneCount}/7</span>
                <span className="step-name">{currentStageName || '—'}</span>
                <span className="step-divider" />
                <div className="step-status">
                  <span className={`step-status-dot ${statusClass}`} />
                  <span className="step-status-text">{statusText}</span>
                </div>
              </div>
            )
          })()}
          <span className="step-divider" />
          <button className="lang-btn" onClick={() => setLang(lang === 'en' ? 'zh' : 'en')}>
            {lang === 'en' ? '中' : 'EN'}
          </button>
        </div>
      </div>
      {tab === 'womb' && renderWomb()}
      {tab === 'cradle' && renderPlaceholder(t.tabs.cradle)}
      {tab === 'world' && renderPlaceholder(t.tabs.world)}
    </div>
  )
}

export default App
