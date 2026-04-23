/**
 * [INPUT]: kind prop ∈ {'womb', 'cradle'}, 决定加载哪份样本 JSON
 * [OUTPUT]: 全屏 LifeGraph 预览, 用于 Phase A / 批次 1 设计契约验证
 * [POS]: components/SampleGraphPreview.jsx - 临时调试入口
 *        对应 add-womb-conception-graph + add-cradle-growth-graph 两提案
 * [PROTOCOL]: 变更时更新此头部, 然后检查 CLAUDE.md
 *
 * 访问:
 *   http://localhost:5173/?sample=womb    → 孕育图样本
 *   http://localhost:5173/?sample=cradle  → 摇篮图样本 (138 节点 / 194 边)
 *
 * 用途:
 *   - 可视化验证 sample JSON 的 schema / 多重边 / 无时间节点 / 中心锚点
 *   - 无后端依赖, 纯前端静态数据 dry-run
 */
import { useMemo } from 'react'
import LifeGraph from './LifeGraph'
import wombSample from '@/data/womb-conception-sample.json'
import cradleSample from '@/data/cradle-growth-sample.json'

// 按 kind 选样本数据 + 顶栏元字段展示策略 + 关注的多重边指标。
const PRESETS = {
  womb: {
    sample: wombSample,
    title: 'Womb Sample Preview',
    versionOf: (s) => `v${s.metadata?.version ?? '?'}`,
    centerOf: (s) => s.metadata?.center_anchor ?? 'baby_this',
    // 孕育关注的多重边：cortisol→heart 等激素调控 + folate→brain 营养 + baby 辐射边
    edgeMetrics: (edges) => {
      const count = (s, t, tp) => edges.filter(e => e.source === s && e.target === t && e.type === tp).length
      return {
        'cortisol→heart MODULATES': count('hormone_cortisol', 'organ_heart', 'MODULATES'),
        'cortisol→brain MODULATES': count('hormone_cortisol', 'organ_brain', 'MODULATES'),
        'thyroid→brain MODULATES': count('hormone_thyroid', 'organ_brain', 'MODULATES'),
        'folate→brain FEEDS': count('nutrient_folate', 'organ_brain', 'FEEDS'),
        'folate→baby INTAKE': count('nutrient_folate', 'baby_this', 'INTAKE'),
        'hr→baby MEASURED': count('vital_hr', 'baby_this', 'MEASURED'),
        'baby→heart DEVELOPS': count('baby_this', 'organ_heart', 'DEVELOPS'),
        'baby→brain DEVELOPS': count('baby_this', 'organ_brain', 'DEVELOPS'),
        'baby→lung DEVELOPS': count('baby_this', 'organ_lung', 'DEVELOPS'),
      }
    },
  },
  cradle: {
    sample: cradleSample,
    title: 'Cradle Sample Preview',
    versionOf: (s) => s.schema ?? 'v?',
    centerOf: (s) => s.center_anchor ?? 'baby_this',
    // 摇篮关注的多重边：caregiver→baby CARED_BY + baby→caregiver ATTACHES_TO + regression/recovery
    // 注意 cradle sample 的 source/target 是 UUID 字符串（不是 raw id），
    // 所以要先从 nodes 里反查 raw_id 对应的 UUID。
    edgeMetrics: (edges, nodes) => {
      const uuidOf = (rawId) => nodes.find(n => n?.metadata?.raw_id === rawId)?.id
      const count = (sRaw, tRaw, tp) => {
        const s = uuidOf(sRaw), t = uuidOf(tRaw)
        if (!s || !t) return 0
        return edges.filter(e => e.source === s && e.target === t && e.type === tp).length
      }
      const byType = (tp) => edges.filter(e => e.type === tp).length
      return {
        'mother→baby CARED_BY': count('caregiver_mother', 'baby_this', 'CARED_BY'),
        'father→baby CARED_BY': count('caregiver_father', 'baby_this', 'CARED_BY'),
        'baby→mother ATTACHES_TO': count('baby_this', 'caregiver_mother', 'ATTACHES_TO'),
        'REGRESSES (total)': byType('REGRESSES'),
        'RECOVERS (total)': byType('RECOVERS'),
        'OCCURS_IN (total)': byType('OCCURS_IN'),
        'BELONGS_TO (total)': byType('BELONGS_TO'),
        'NEXT (total)': byType('NEXT'),
      }
    },
  },
}

export default function SampleGraphPreview({ kind = 'womb' }) {
  const preset = PRESETS[kind] ?? PRESETS.womb
  const { sample, title } = preset
  const { nodes, edges } = useMemo(() => ({
    nodes: sample.nodes || [],
    edges: sample.edges || [],
  }), [sample])

  const edgeMetrics = useMemo(
    () => preset.edgeMetrics(edges, nodes),
    [edges, nodes, preset],
  )

  // 守门："无时间节点" 硬铁律（两图共用）
  const hasTimeNode = nodes.some(n => {
    const rid = n?.metadata?.raw_id || n?.id || ''
    return /^(stage_|day_|phase_x_day_)/.test(rid)
  })

  return (
    <div className="flex flex-col h-screen bg-background">
      <div className="px-4 py-2 border-b border-border text-xs text-muted-foreground flex items-center gap-4 flex-wrap">
        <strong className="text-foreground">{title}</strong>
        <span>{preset.versionOf(sample)}</span>
        <span>{nodes.length} nodes / {edges.length} edges</span>
        <span>anchor: {preset.centerOf(sample)}</span>
        <span className={hasTimeNode ? 'text-red-500' : 'text-green-600'}>
          Time nodes: {hasTimeNode ? '❌ present' : '✓ none'}
        </span>
        <span className="flex-1" />
        <span className="opacity-70">
          Multi-edges: {Object.entries(edgeMetrics).map(([k, v]) => `${k}=${v}`).join(' · ')}
        </span>
      </div>
      <div className="flex-1 min-h-0">
        <LifeGraph nodes={nodes} edges={edges} fullscreen={false} />
      </div>
    </div>
  )
}
