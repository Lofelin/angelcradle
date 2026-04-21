/**
 * [INPUT]: causeTags: string[], effectTags: string[], onTagClick?: (tag) => void
 * [OUTPUT]: 因果标签芯片组（cause 蓝底左箭头, effect 绿底右箭头, 先天因素金底）
 * [POS]: 事件卡片内嵌组件，展示事件的因果标签
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */
import { memo } from 'react'
import { cn } from '@/lib/utils'

// ── 标签 namespace 分类 ──────────────────────────
const INNATE_PREFIXES = ['sensory_dominant', 'sensory_weak', 'gene', 'defect']

const isInnate = (tag) => INNATE_PREFIXES.some(p => tag.startsWith(p + ':'))

// ── 标签显示名映射 ──────────────────────────────
const TAG_DISPLAY = {
  sensory_dominant: '主感官',
  sensory_weak: '弱感官',
  arousal: '唤醒',
  stress: '压力',
  stage: '阶段',
  defect: '缺陷',
  gene: '基因',
  emotion: '情绪',
  attachment: '依恋',
  capability: '能力',
  caregiver: '照护者',
}

const formatTag = (tag) => {
  const [ns, ...rest] = tag.split(':')
  const label = TAG_DISPLAY[ns] || ns
  const value = rest.join(':').replace(/_/g, ' ')
  return { label, value, ns }
}

// ── 单个标签芯片 ─────────────────────────────────
const TagChip = memo(function TagChip({ tag, type, onClick }) {
  const { label, value, ns } = formatTag(tag)
  const innate = type === 'cause' && isInnate(tag)

  return (
    <button
      type="button"
      onClick={() => onClick?.(tag)}
      className={cn(
        'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors',
        'hover:brightness-90 cursor-pointer',
        innate
          ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300'
          : type === 'cause'
            ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300'
            : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300'
      )}
      title={tag}
    >
      {type === 'cause' && <span className="text-[8px]">←</span>}
      {innate && <span className="text-[8px]">★</span>}
      <span>{label}</span>
      <span className="opacity-70">{value}</span>
      {type === 'effect' && <span className="text-[8px]">→</span>}
    </button>
  )
})

// ── 主组件 ───────────────────────────────────────
const CausalTags = memo(function CausalTags({ causeTags = [], effectTags = [], onTagClick }) {
  if (causeTags.length === 0 && effectTags.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1 mt-1.5">
      {causeTags.map(tag => (
        <TagChip key={`c:${tag}`} tag={tag} type="cause" onClick={onTagClick} />
      ))}
      {effectTags.map(tag => (
        <TagChip key={`e:${tag}`} tag={tag} type="effect" onClick={onTagClick} />
      ))}
    </div>
  )
})

export default CausalTags
