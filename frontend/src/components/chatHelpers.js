/**
 * [INPUT]: 无外部依赖
 * [OUTPUT]: shortId / avatarPalette / portraitUrl / formatClockTime / urgencyColorClasses
 * [POS]: 聊天相关 UI 的纯工具函数；ChatPanel / GroupChatPanel / MessageBubble 消费；Cradle.jsx 保留本地同名实现待 M4b 去重
 * [PROTOCOL]: 变更时更新此头部，然后检查 src/CLAUDE.md
 */

const API = 'http://localhost:8000'

/** 截取 baby_id 末段作为简短标识（AC-20260414-30865 → 30865）。 */
export const shortId = (id) => (id ? id.split('-').pop() || '?' : '?')

/** 为任意 baby_id 生成稳定的 Tailwind 色板（bg + text 类名）。 */
export const avatarPalette = (id) => {
  if (!id) return { bg: 'bg-muted', text: 'text-foreground' }
  let hash = 0
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0
  const palettes = [
    { bg: 'bg-rose-500/15', text: 'text-rose-600 dark:text-rose-300' },
    { bg: 'bg-amber-500/15', text: 'text-amber-700 dark:text-amber-300' },
    { bg: 'bg-emerald-500/15', text: 'text-emerald-700 dark:text-emerald-300' },
    { bg: 'bg-sky-500/15', text: 'text-sky-700 dark:text-sky-300' },
    { bg: 'bg-violet-500/15', text: 'text-violet-700 dark:text-violet-300' },
    { bg: 'bg-pink-500/15', text: 'text-pink-700 dark:text-pink-300' },
  ]
  return palettes[hash % palettes.length]
}

/** 肖像图 URL。 */
export const portraitUrl = (id) =>
  `${API}/cradle/baby/${encodeURIComponent(id)}/portrait`

/** Unix ts → HH:MM。 */
export const formatClockTime = (ts) => {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 需求 urgency → Tailwind 色类。 */
export const urgencyClasses = (urgency) => {
  const map = {
    physiological: {
      text: 'text-red-400',
      bg: 'bg-red-500/10 border-red-500/30',
    },
    emotional: {
      text: 'text-amber-400',
      bg: 'bg-amber-500/10 border-amber-500/30',
    },
    social: {
      text: 'text-blue-400',
      bg: 'bg-blue-500/10 border-blue-500/30',
    },
  }
  return map[urgency] || map.emotional
}
