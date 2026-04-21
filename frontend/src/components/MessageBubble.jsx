/**
 * [INPUT]: react, @/lib/utils, @/components/ui/avatar, ./chatHelpers
 * [OUTPUT]: MessageBubble — 单条会话消息渲染（parent / baby / system / subtype=need / action_type=touch）
 * [POS]: 聊天 UI 共享的消息气泡组件，被 ChatPanel / GroupChatPanel 复用
 * [PROTOCOL]: 变更时更新此头部，然后检查 src/CLAUDE.md
 */
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { cn } from '@/lib/utils'
import { shortId, avatarPalette, portraitUrl, formatClockTime, urgencyClasses } from './chatHelpers'

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
        <div className="h-6 flex items-center gap-1.5 flex-wrap">
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
              {isZh ? '需求' : 'need'} · {msg.urgency || ''}
            </span>
          )}
          {msg.emotional_tone && !isNeed && (
            <span className="text-[9px] text-muted-foreground">
              [{msg.emotional_tone}]
            </span>
          )}
        </div>
        <div
          className={cn(
            'px-3.5 py-2 rounded-lg rounded-tl-sm text-sm space-y-1',
            isNeed ? cn('border', urg.bg) : 'bg-muted text-foreground',
          )}
        >
          {parseBabyContent(msg.content).map((part, i) =>
            part.type === 'action' ? (
              <div
                key={i}
                className="text-[11px] italic text-muted-foreground/80"
              >
                * {part.text} *
              </div>
            ) : (
              <div key={i} className="leading-relaxed">
                {part.text}
              </div>
            ),
          )}
          {msg.state_changes && Object.keys(msg.state_changes).length > 0 && (
            <div className="text-[10px] text-muted-foreground mt-1 not-italic">
              {renderStateChanges(msg.state_changes, isZh)}
            </div>
          )}
        </div>
      </div>
    </div>
  )
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
