/**
 * [INPUT]: react, ./i18n, shadcn/ui (Button, Select, ToggleGroup, Card)
 * [OUTPUT]: App 根组件 — Angel Cradle 主界面
 * [POS]: 应用入口视图，消费 SSE 流驱动孕育模拟
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */
import { useState, useEffect, useRef, useReducer, useCallback } from 'react'
import { Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom'
import messages, { translateKey } from './i18n'
import { Button } from '@/components/ui/button'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { cn } from '@/lib/utils'
import Cradle from './Cradle'

const API = 'http://localhost:8000'

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
      return { logs: [], stageProgress: {}, maternalProgress: {}, currentStage: '', statusText: '', babyState: null, environment: null, parentGenomes: null, vitals: null, running: true, startedAt: Date.now(), elapsed: null }
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
      let { stageProgress, maternalProgress, currentStage, statusText, babyState, environment, parentGenomes, vitals, running } = state

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
            babyState = { ...babyState, stages: { ...babyState.stages, [data.stage]: data.response } }
          }
        } else if (data.status === 'maternal_response') {
          statusText = t.maternal_responding
          maternalProgress = { ...maternalProgress, [data.stage]: 'active' }
        } else if (data.status === 'maternal_response_done') {
          maternalProgress = { ...maternalProgress, [data.stage]: 'done' }
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

      return { ...state, logs: newLogs, stageProgress, maternalProgress, currentStage, statusText, babyState, environment, parentGenomes, vitals, running }
    }
    case 'CLOSE':
      return { ...state, running: false, logs: [...state.logs, { time: getTime(), type: 'system', text: action.text }] }
    case 'CLEAR_PROGRESS':
      return { ...state, stageProgress: {}, maternalProgress: {}, statusText: '', babyState: null, environment: null, parentGenomes: null, vitals: null }
    default:
      return state
  }
}

const INIT_STATE = { logs: [], stageProgress: {}, maternalProgress: {}, currentStage: '', statusText: '', babyState: null, environment: null, parentGenomes: null, vitals: null, running: false, startedAt: null, elapsed: null }

function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const tab = location.pathname.split('/')[1] || 'womb'

  const [lang, setLang] = useState(() => localStorage.getItem('lang') || 'en')
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
  const [state, dispatch] = useReducer(wombReducer, INIT_STATE)
  const consoleRef = useRef(null)
  const leftPanelRef = useRef(null)
  const stageCardsRef = useRef(null)
  const [expandedTag, setExpandedTag] = useState(null)

  const t = messages[lang]

  useEffect(() => {
    fetch(`${API}/species`)
      .then(r => r.json())
      .then(data => setSpeciesList(data.species))
      .catch(() => setSpeciesList(['human', 'dog', 'cat']))
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

  const conceive = useCallback(() => {
    dispatch({ type: 'RESET' })
    const params = new URLSearchParams({ species, lang })
    if (selectedSex !== 'random') params.set('sex', selectedSex)
    if (selectedPhenotype !== 'random') params.set('phenotype', selectedPhenotype)
    if (selectedNutrition !== 'random') params.set('nutrition', selectedNutrition)
    if (selectedStress !== 'random') params.set('stress', selectedStress)
    if (selectedToxin !== 'random') params.set('toxin_exposure', selectedToxin)
    if (selectedAge !== 'random') params.set('maternal_age_factor', selectedAge)
    if (selectedOffspring !== 'random') params.set('offspring_count', selectedOffspring)

    const source = new EventSource(`${API}/conceive/stream?${params}`)
    source.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        dispatch({ type: 'SSE_EVENT', data, ts: getTime(), t, lang })
      } catch { /* ignore */ }
    }
    source.onerror = () => {
      dispatch({ type: 'CLOSE', text: t.closed })
      source.close()
    }
  }, [species, lang, selectedSex, selectedPhenotype, selectedNutrition, selectedStress, selectedToxin, selectedAge, selectedOffspring, t])

  const { logs, stageProgress, maternalProgress, statusText, babyState, running } = state
  const environment = state.environment
  const tk = (v) => translateKey(v, lang)
  const isConceiving = running || Object.keys(stageProgress).length > 0

  // 孕育过程中左屏内容变化时，自动滑到底部
  useEffect(() => {
    if (isConceiving && leftPanelRef.current) {
      requestAnimationFrame(() => {
        leftPanelRef.current?.scrollTo({ top: leftPanelRef.current.scrollHeight, behavior: 'smooth' })
      })
    }
  }, [isConceiving, babyState, environment, state.vitals, stageProgress])

  // 阶段卡片自动滚底
  useEffect(() => {
    if (isConceiving && stageCardsRef.current) {
      requestAnimationFrame(() => {
        stageCardsRef.current?.scrollTo({ top: stageCardsRef.current.scrollHeight, behavior: 'smooth' })
      })
    }
  }, [isConceiving, stageProgress, maternalProgress])

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
            {t.birthplace_info(bp.name, bp.code, bp.coordinates.lat, bp.coordinates.lng)}
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

  const renderBlueprint = () => (
    <div className="flex flex-col gap-6 px-1">
      {/* 系统就绪 */}
      <div>
        <div className="text-[11px] text-muted-foreground tracking-wider mb-2 flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />{lang === 'zh' ? '系统状态' : 'System Status'}</div>
        <h2 className="font-heading text-3xl font-bold tracking-tight leading-tight">{lang === 'zh' ? '准备就绪' : 'System Ready'}</h2>
        <p className="text-sm text-muted-foreground mt-1.5">{lang === 'zh' ? '系统已准备好模拟生命孕育' : 'System is ready to simulate life conception'}</p>
      </div>

      {/* 发育阶段流程 */}
      <div>
        <div className="text-[11px] text-muted-foreground tracking-wider mb-4">{lang === 'zh' ? '· 发育流程' : '· Workflow Steps'}</div>
        <div className="flex flex-col divide-y divide-border">
          {WORKFLOW_STEPS.map((step, i) => (
            <div key={step.name} className="flex gap-4 py-4 first:pt-0">
              <span className="text-xl font-heading font-bold text-muted-foreground/20 w-7 shrink-0 tabular-nums pt-0.5">{String(i + 1).padStart(2, '0')}</span>
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
  const renderParams = () => (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto border border-border p-5 flex flex-col gap-6">
        {/* 区域 01 — 基因蓝图 */}
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

        {/* 分隔线 */}
        <div className="flex items-center gap-3">
          <div className="flex-1 border-t border-border" />
          <span className="text-[11px] text-muted-foreground tracking-wider">{lang === 'zh' ? '输入参数' : 'Input Parameters'}</span>
          <div className="flex-1 border-t border-border" />
        </div>

        {/* 区域 02 — 母体环境 */}
        <div>
          <div className="text-[11px] text-muted-foreground tracking-wider mb-3">02 / {t.env_conditions}</div>
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
        {/* 孕育按钮 */}
        <button
          className="w-full flex items-center justify-between px-5 py-3.5 text-base font-heading font-semibold text-primary border border-border hover:bg-primary/5 transition-colors cursor-pointer mt-auto"
          onClick={conceive}
        >
          {t.conceive}
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" strokeLinejoin="round" d="M17 8l4 4m0 0l-4 4m4-4H3" /></svg>
        </button>
      </div>
    </div>
  )

  // ── 发育监视器 (孕育后) ──
  const renderMonitorHeader = () => (
    babyState ? (
      <div className="flex items-center gap-2 px-2 capitalize flex-wrap">
        <span className="text-2xl leading-none">{SPECIES_ICONS[species] || '\u{1F9EC}'}</span>
        <h1 className="font-heading text-xl font-semibold">{tk(species)}</h1>
        <span className="text-muted-foreground">/</span>
        <span className="text-sm text-muted-foreground">{tk(babyState.sex)}</span>
        {babyState.id && <span className="ml-auto text-[10px] text-muted-foreground font-mono normal-case">{babyState.id}</span>}
      </div>
    ) : null
  )

  const renderMonitor = () => (
    <>
      {/* 遗传特征 */}
      {babyState && (() => {
        const pheno = Object.entries(babyState.phenotype || {})
        const hasDefects = babyState.defects?.length > 0
        return (
          <div className="px-1">
            <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-3">{t.fetal_status}</div>
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm capitalize">
              {pheno.map(([k, v]) => (
                <div key={k}>
                  <span className="text-muted-foreground">{tk(k.replace(/_/g, ' '))}</span>{' '}
                  <span className="font-medium text-foreground">{tk(v)}</span>
                </div>
              ))}
              <div>
                <span className="text-muted-foreground">{t.defects}</span>{' '}
                <span className={cn("font-medium", hasDefects ? "text-destructive" : "text-foreground")}>
                  {hasDefects
                    ? babyState.defects.map(d => typeof d === 'object' ? tk((d.defect || '').replace(/_/g, ' ')) : tk(d.replace(/_/g, ' '))).join(', ')
                    : t.no_defects}
                </span>
              </div>
            </div>
          </div>
        )
      })()}

      {/* 母体环境 */}
      {environment && (
        <Card>
          <CardHeader>
            <CardTitle>{t.env_conditions}</CardTitle>
          </CardHeader>
          <CardContent>
            {(() => {
              const fmt = (v) => {
                if (v === null || v === undefined) return '-'
                if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2)
                if (typeof v === 'boolean') return v ? (lang === 'zh' ? '是' : 'Yes') : (lang === 'zh' ? '否' : 'No')
                if (Array.isArray(v)) return v.length ? v.map(x => typeof x === 'object' ? JSON.stringify(x) : tk(String(x).replace(/_/g, ' '))).join(', ') : '-'
                if (typeof v === 'object') return null
                return tk(String(v).replace(/_/g, ' '))
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

              const baseItems = [
                [t.nutrition, tk(environment.nutrition)],
                [t.stress, tk(environment.stress)],
                [t.toxin, tk(environment.toxin_exposure)],
                [t.age, (AGE_LABELS[lang] || AGE_LABELS.en)[environment.maternal_age_factor] || tk(environment.maternal_age_factor)],
              ]
              if (environment.modifiers) {
                baseItems.push([t.budget, `${(environment.modifiers.budget_multiplier * 100).toFixed(0)}%`])
                baseItems.push([t.risk, `${environment.modifiers.defect_risk_multiplier.toFixed(1)}x`])
              }

              const subSections = [
                ['nutrients', t.nutrients_label],
                ['toxin_types', t.toxin_types_label],
                ['placenta', t.placenta_label],
                ['immunity', t.immunity_label],
              ]

              return (
                <div className="flex flex-col gap-3">
                  {renderBox(null, baseItems)}
                  {subSections.map(([key, label]) => {
                    const val = environment[key]
                    if (!val) return null
                    if (Array.isArray(val) && val.length > 0) {
                      return renderBox(label, [[label, val.map(x => tk(String(x).replace(/_/g, ' '))).join(', ')]])
                    }
                    if (typeof val === 'object' && !Array.isArray(val)) {
                      const items = Object.entries(val)
                        .map(([k, v]) => [tk(k.replace(/_/g, ' ')), fmt(v)])
                        .filter(([, v]) => v !== null)
                      if (items.length > 0) return renderBox(label, items)
                    }
                    return null
                  })}
                </div>
              )
            })()}
          </CardContent>
        </Card>
      )}

      {/* 胎儿生命体征 */}
      {state.vitals && (
        <Card>
          <CardHeader>
            <CardTitle>{lang === 'zh' ? '生命体征' : 'Vital Signs'}</CardTitle>
            <CardDescription>{state.vitals.status || ''}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="bg-muted rounded-2xl p-4">
              <div className="flex flex-col divide-y divide-border text-sm">
                {[
                  [lang === 'zh' ? '体重' : 'Weight', state.vitals.weight],
                  [lang === 'zh' ? '身长' : 'Length', state.vitals.length],
                  [lang === 'zh' ? '羊水' : 'Amniotic Fluid', state.vitals.amniotic_fluid],
                  [lang === 'zh' ? '胎动' : 'Movement', state.vitals.movement],
                  [lang === 'zh' ? '血压' : 'Blood Pressure', state.vitals.blood_pressure],
                  [lang === 'zh' ? '血氧' : 'Oxygen', state.vitals.oxygen],
                ].map(([label, val], i) => (
                  <div key={i} className="flex justify-between py-2.5 first:pt-0 last:pb-0">
                    <span className="text-muted-foreground">{label}</span>
                    <span className="font-medium">{val}</span>
                  </div>
                ))}
              </div>
            </div>
            {state.vitals.alerts?.length > 0 && (
              <div className="mt-3 bg-destructive/10 rounded-2xl p-4 text-sm text-destructive">
                {state.vitals.alerts.map((a, i) => <div key={i}>{a}</div>)}
              </div>
            )}
          </CardContent>
        </Card>
      )}

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
                  <span className="text-sm text-foreground leading-relaxed">{tend}</span>
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
                  <span className="text-2xl font-heading font-bold text-muted-foreground/40">{String(i + 1).padStart(2, '0')}</span>
                  <span className="text-base font-heading font-semibold capitalize">{tk(stg.name.replace(/_/g, ' '))}</span>
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
                              <div className="flex flex-col gap-1.5">
                                {val.map((item, j) => (
                                  <div key={j} className="flex gap-2">
                                    <span className="text-muted-foreground shrink-0">•</span>
                                    <span>{typeof item === 'object' ? JSON.stringify(item, null, 2) : String(item)}</span>
                                  </div>
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
                onClick={() => {
                  fetch(`${API}/cradle/admit`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ baby_id: babyState.id }),
                  })
                    .then(r => { if (!r.ok) throw new Error(); return r.json() })
                    .then(() => { navigate(`/cradle/${babyState.id}?autoGrow=true`) })
                    .catch(e => console.error('Admit failed:', e))
                }}
              >
                {lang === 'zh' ? '放入摇篮' : 'To Cradle'} →
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
  const renderConsole = () => (
    <div className="flex flex-col h-full bg-[#1C1C1C] rounded-xl overflow-hidden shadow-[0_4px_24px_rgba(0,0,0,0.3),0_0_0_0.5px_rgba(255,255,255,0.08)_inset]">
      <div className="h-[32px] bg-[#2D2D2D] border-b border-[#1a1a1a] flex items-center px-3.5 shrink-0">
        <div className="text-xs text-[#999] mx-auto whitespace-nowrap">
          {(() => {
            const doneCount = Object.values(stageProgress).filter(s => s === 'done').length + (Object.values(stageProgress).some(s => s === 'active') ? 1 : 0)
            const failedCount = Object.values(stageProgress).filter(s => s === 'failed').length
            const currentStageName = state.currentStage ? tk(state.currentStage) : ''
            const allDone = doneCount === 7
            const hasFailed = failedCount > 0
            const hasStarted = doneCount > 0 || running
            const isMaternalNow = state.currentStage && maternalProgress[state.currentStage] === 'active'
            return (
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
            )
          })()}
        </div>
      </div>
      <div className="console" ref={consoleRef}>
        {logs.length === 0 && <div className="log-system"><span className="blink-dot" />{t.ready}</div>}
        {logs.map(renderLog)}
      </div>
    </div>
  )

  // ── 孕育前单页布局 ──
  const renderPreConceive = () => (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-7xl mx-auto px-12 min-h-full flex items-center gap-12">
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
    <div className="flex flex-col flex-1 overflow-hidden">
      <div className="flex flex-1 overflow-hidden">
        {/* 左面板 */}
        <div className="left-panel w-1/2 bg-background border-r border-border flex flex-col shrink-0">
          <div className="shrink-0 px-5 pt-5 pb-2">
            {renderMonitorHeader()}
          </div>
          <div ref={leftPanelRef} className="flex-1 overflow-y-auto px-5 pb-5 flex flex-col gap-3">
            <div className="w-full flex flex-col gap-3">
              {renderMonitor()}
            </div>
          </div>
        </div>
        {/* 右面板：阶段卡片 */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 flex flex-col p-5 overflow-hidden">
            {renderStageCards()}
          </div>
        </div>
      </div>
      {/* 底部控制台 */}
      <div className="border-t border-border p-2 overflow-hidden" style={{ flex: '1 1 0%', minHeight: '120px', maxHeight: '25%' }}>
        <div className="h-full flex flex-col">
          {renderConsole()}
        </div>
      </div>
    </div>
  )

  const renderWomb = () => isConceiving ? renderConceiving() : renderPreConceive()

  const renderPlaceholder = (name) => (
    <div className="flex flex-1 overflow-hidden">
      <div className="flex-1 flex items-center justify-center text-foreground text-2xl">
        {name}
      </div>
    </div>
  )

  return (
    <div className="flex flex-col h-screen">
      {/* 顶部导航 */}
      <div className="h-16 bg-card border-b border-border flex items-center px-6 shrink-0 relative">
        <img src={`/logo.svg?v=${Date.now()}`} alt={t.title} className="h-[50px] mr-auto" />
        <div className="flex items-center gap-0.5 absolute left-1/2 -translate-x-1/2">
          {['womb', 'cradle', 'world'].map((key, i) => (
            <span key={key} className="contents">
              {i > 0 && <span className="w-[3px] h-[3px] bg-border rounded-full mx-2" />}
              <button
                className={cn(
                  "bg-transparent border-none text-muted-foreground text-xs py-2 px-5 cursor-pointer transition-all duration-200 relative font-[inherit]",
                  "hover:text-foreground",
                  tab === key && "text-primary after:content-[''] after:absolute after:bottom-0 after:left-[20%] after:right-[20%] after:h-0.5 after:bg-primary after:rounded-[1px]"
                )}
                onClick={() => navigate(`/${key}`)}
              >
                {t.tabs[key]}
              </button>
            </span>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => { const next = lang === 'en' ? 'zh' : 'en'; localStorage.setItem('lang', next); setLang(next) }}
          >
            {lang === 'en' ? '中文' : 'EN'}
          </Button>
          <a href="https://github.com/Lofelin/angelcradle" target="_blank" rel="noopener noreferrer">
            <Button size="sm" className="bg-[#24292f] text-white hover:bg-[#24292f]/90">
              <svg viewBox="0 0 16 16" fill="currentColor" className="size-4"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" /></svg>
              GitHub
            </Button>
          </a>
        </div>
      </div>
      <Routes>
        <Route path="/womb" element={renderWomb()} />
        <Route path="/cradle" element={<Cradle lang={lang} />} />
        <Route path="/cradle/:babyId" element={<Cradle lang={lang} />} />
        <Route path="/world" element={renderPlaceholder(t.tabs.world)} />
        <Route path="*" element={<Navigate to="/womb" replace />} />
      </Routes>
    </div>
  )
}

export default App
