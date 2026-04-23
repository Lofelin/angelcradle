/**
 * [INPUT]: react, @/lib/utils, @/components/ui/avatar, ./chatHelpers
 * [OUTPUT]: MessageBubble — 单条会话消息渲染（parent / baby / system / subtype=need / action_type=touch）
 * [POS]: 聊天 UI 共享的消息气泡组件，被 ChatPanel / GroupChatPanel 复用
 * [PROTOCOL]: 变更时更新此头部，然后检查 src/CLAUDE.md
 */
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { cn } from '@/lib/utils'
import { shortId, avatarPalette, portraitUrl, formatClockTime, urgencyClasses } from './chatHelpers'

// 需求类别中英文映射——后端回传 urgency 为英文字符串（physiological / emotional / social / cognitive）。
// 与 chatHelpers.urgencyClasses 的键保持对齐；新增类别时两处一起补。
const URGENCY_LABEL = {
  zh: {
    physiological: '生理',
    emotional: '情绪',
    social: '社交',
    cognitive: '认知',
  },
  en: {
    physiological: 'physiological',
    emotional: 'emotional',
    social: 'social',
    cognitive: 'cognitive',
  },
}

function urgencyLabel(urgency, isZh) {
  if (!urgency) return ''
  const table = isZh ? URGENCY_LABEL.zh : URGENCY_LABEL.en
  return table[urgency] || urgency
}

/**
 * @param {{
 *   msg: object,         // /conversations SSE 推送的消息对象
 *   isZh: boolean,
 * }} props
 */
export default function MessageBubble({ msg, isZh }) {
  // 系统标记（破冰开始/结束）
  if (msg.role === 'system') {
    const label = labelFor(msg, isZh)
    if (!label) return null
    return (
      <div className="text-center text-[11px] text-muted-foreground/70 py-1.5 italic">
        — {label} —
      </div>
    )
  }

  // 家长（靠右）
  if (msg.role === 'parent') {
    const isTouch = msg.action_type === 'touch'
    return (
      <div className="flex justify-end items-start gap-2">
        <div className="max-w-[75%] flex flex-col items-end">
          <div className="h-6 flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground">
              {formatClockTime(msg.ts)}
            </span>
            <span className="text-[11px] font-medium text-foreground">
              {isZh ? '你' : 'You'}
            </span>
          </div>
          <div
            className={cn(
              'px-3.5 py-2 rounded-lg rounded-tr-sm text-sm',
              isTouch
                ? 'bg-amber-500/10 text-amber-700 dark:text-amber-300 italic border border-amber-500/20'
                : 'bg-primary/15 text-primary',
            )}
          >
            {isTouch ? (
              <span className="flex items-center gap-1.5">
                <span>✋</span>
                <span>{msg.content || msg.touch_key}</span>
                <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500/15 not-italic font-medium">
                  {isZh ? '动作' : 'Action'}
                </span>
              </span>
            ) : (
              msg.content
            )}
          </div>
        </div>
        <Avatar className="shrink-0">
          <AvatarFallback className="text-[10px] font-semibold bg-primary/20 text-primary">
            U
          </AvatarFallback>
        </Avatar>
      </div>
    )
  }

  // 宝宝（靠左）
  const babyId = msg.baby_id
  const isNeed = msg.subtype === 'need'
  const urg = urgencyClasses(msg.urgency)
  const parts = parseBabyContent(msg.content)
  const actions = parts.filter((p) => p.type === 'action')
  const speeches = parts.filter((p) => p.type === 'speech')

  return (
    <div className="flex items-start gap-2">
      <Avatar className="shrink-0">
        <AvatarImage src={babyId ? portraitUrl(babyId) : undefined} />
        <AvatarFallback
          className={cn(
            'text-[9px] font-mono tracking-tighter font-semibold',
            avatarPalette(babyId).bg,
            avatarPalette(babyId).text,
          )}
        >
          {shortId(babyId)}
        </AvatarFallback>
      </Avatar>
      <div className="max-w-[75%]">
        {/* 元信息行：名字 / 时间 / need·urgency
            min-h-6 允许窄容器（如世界页右侧卡片）里 urgency 标签自然换行；
            若固定 h-6 + flex-wrap，换行的标签会溢出被下一行动作文字遮住 */}
        <div className="min-h-6 flex items-center gap-1.5 flex-wrap">
          <span className="text-[11px] font-medium text-foreground">
            {msg.name || shortId(babyId)}
          </span>
          <span className="text-[10px] text-muted-foreground">
            {formatClockTime(msg.ts)}
          </span>
          {isNeed && (
            <span
              className={cn(
                'text-[9px] px-1.5 py-0.5 rounded-full font-medium',
                urg.text,
              )}
            >
              {isZh ? '需求' : 'need'} · {urgencyLabel(msg.urgency, isZh)}
            </span>
          )}
          {msg.emotional_tone && !isNeed && (
            <span className="text-[9px] text-muted-foreground">
              [{msg.emotional_tone}]
            </span>
          )}
        </div>
        {/* 动作描述统一放元信息行下方独立一行，不进气泡；
            借鉴剧本/小说的舞台说明风格：左侧细竖线 + 圆括号包裹斜体灰字，比 * text * 更易读 */}
        {actions.map((a, i) => (
          <div
            key={`act-${i}`}
            className="text-[11px] italic text-muted-foreground/80 py-0.5"
          >
            ({a.text})
          </div>
        ))}
        {(speeches.length > 0 || (msg.state_changes && Object.keys(msg.state_changes).length > 0)) && (
          <div
            className={cn(
              // w-fit 让气泡缩到内容宽度（上限受外层 max-w-[75%] 约束），短对白不再拉成宽条
              'w-fit max-w-full px-3 py-1.5 rounded-lg rounded-tl-sm text-sm space-y-1',
              isNeed ? cn('border', urg.bg) : 'bg-muted text-foreground',
            )}
          >
            {speeches.map((s, i) => (
              <div key={`sp-${i}`} className="leading-relaxed">
                {stripQuotes(s.text)}
              </div>
            ))}
            {msg.state_changes && Object.keys(msg.state_changes).length > 0 && (
              <div className="text-[10px] text-muted-foreground mt-1 not-italic">
                {renderStateChanges(msg.state_changes, isZh)}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// 去掉对白外包裹的成对引号：英文 ' " 及中文 " " ' '
function stripQuotes(text) {
  if (!text) return text
  const pairs = [
    ['"', '"'], ["'", "'"],
    ['“', '”'], ['‘', '’'],
    ['「', '」'], ['『', '』'],
  ]
  const s = text.trim()
  for (const [l, r] of pairs) {
    if (s.length >= 2 && s.startsWith(l) && s.endsWith(r)) {
      return s.slice(l.length, s.length - r.length).trim()
    }
  }
  return s
}


function labelFor(msg, isZh) {
  if (msg.subtype === 'icebreaker_start' || msg.action_type === 'icebreaker_start') {
    return isZh ? '宝宝们准备开口...' : 'Babies getting ready...'
  }
  if (msg.subtype === 'icebreaker_done' || msg.action_type === 'icebreaker_done') {
    return isZh ? '破冰完成，继续聊吧' : 'Icebreaker done'
  }
  return msg.content || null
}


// 将宝宝消息按 *动作* 与对白拆分为顺序片段
// 输入 "*头转向声音* 吃了！因为饿了" → [{action,"头转向声音"},{speech,"吃了！因为饿了"}]
function parseBabyContent(content) {
  if (!content) return []
  const parts = []
  const regex = /\*([^*]+)\*/g
  let last = 0
  let m
  while ((m = regex.exec(content)) !== null) {
    if (m.index > last) {
      const pre = content.slice(last, m.index).trim()
      if (pre) parts.push({ type: 'speech', text: pre })
    }
    const act = m[1].trim()
    if (act) parts.push({ type: 'action', text: act })
    last = regex.lastIndex
  }
  if (last < content.length) {
    const tail = content.slice(last).trim()
    if (tail) parts.push({ type: 'speech', text: tail })
  }
  if (parts.length === 0 && content.trim()) {
    parts.push({ type: 'speech', text: content.trim() })
  }
  return parts
}


function renderStateChanges(changes, isZh) {
  const parts = []
  if (changes.new_preference) parts.push(`${isZh ? '新偏好' : '+pref'}: ${changes.new_preference}`)
  if (changes.new_comfort_source) parts.push(`${isZh ? '安慰物' : '+comfort'}: ${changes.new_comfort_source}`)
  if (changes.fear_reduced) parts.push(`${isZh ? '恐惧↓' : '-fear'}: ${changes.fear_reduced}`)
  if (changes.new_fear) parts.push(`${isZh ? '新恐惧' : '+fear'}: ${changes.new_fear}`)
  return parts.join(' · ')
}
