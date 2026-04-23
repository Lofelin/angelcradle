/**
 * [INPUT]: 无外部依赖
 * [OUTPUT]: shortId / avatarPalette / portraitUrl / formatClockTime / urgencyColorClasses / DEFAULT_TOUCH_ACTIONS / fetchTouchActions
 * [POS]: 聊天相关 UI 的纯工具函数；ChatPanel / GroupChatPanel / MessageBubble / WorldMap 消费；Cradle.jsx 保留本地同名实现待 M4b 去重
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

/** 默认肢体互动列表（后端 /cradle/{id}/touch-actions 可覆盖）。 */
export const DEFAULT_TOUCH_ACTIONS = {
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

/** 拉取指定宝宝的肢体互动列表；失败返回 null 由调用方回退到默认。 */
export const fetchTouchActions = async (babyId) => {
  if (!babyId) return null
  try {
    const r = await fetch(`${API}/cradle/${encodeURIComponent(babyId)}/touch-actions`)
    if (!r.ok) return null
    return await r.json()
  } catch { return null }
}
