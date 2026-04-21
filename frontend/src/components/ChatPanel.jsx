/**
 * [INPUT]: react, lucide-react, @/lib/utils, @/components/ui/*, hooks/useConversation, ./MessageBubble, ./chatHelpers
 * [OUTPUT]: ChatPanel — 1v1 亲子聊天面板（DM 会话）
 * [POS]: 摇篮 tab 聊天区，替代 Cradle.jsx 内部的 chatMode==='single' 分支；SSE 驱动
 * [PROTOCOL]: 变更时更新此头部，然后检查 src/CLAUDE.md
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Hand, Send } from 'lucide-react'

import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

import { useConversation, createConversation } from '../hooks/useConversation'
import MessageBubble from './MessageBubble'
import { shortId, avatarPalette, portraitUrl } from './chatHelpers'

const DM_CONV_ID = (babyId) => `dm:${babyId}`

/**
 * @param {{
 *   babyId: string,
 *   babyStatus: object|null,
 *   touchActions: object|null,
 *   loadTouchActions: () => void,
 *   isZh: boolean,
 *   tk: (key: string) => string,
 * }} props
 */
export default function ChatPanel({
  babyId,
  babyStatus,
  touchActions,
  loadTouchActions,
  isZh,
  tk,
}) {
  const [chatInput, setChatInput] = useState('')
  const [touchPanelOpen, setTouchPanelOpen] = useState(false)
  const [ensuring, setEnsuring] = useState(false)
  const [convReady, setConvReady] = useState(false)
  const inputRef = useRef(null)
  const scrollRef = useRef(null)
  const convId = convReady ? DM_CONV_ID(babyId) : null

  const { messages, connected, sending, send, error } = useConversation(convId)

  // babyId 变化：确保 DM 会话存在（幂等），然后再启用 hook
  useEffect(() => {
    let cancelled = false
    setConvReady(false)
    if (!babyId) return
    setEnsuring(true)
    createConversation({ participants: [babyId], kind: 'dm' })
      .then(() => { if (!cancelled) setConvReady(true) })
      .catch(() => { /* 错误在 send 阶段会再次暴露 */ })
      .finally(() => { if (!cancelled) setEnsuring(false) })
    return () => { cancelled = true }
  }, [babyId])

  // 自动滚底
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages.length])

  // 是否有 pending need（最近一条 need 之后是否已有家长回复）
  const pendingNeed = useMemo(() => findPendingNeed(messages), [messages])

  const doSend = async (overrides) => {
    const payload = overrides || { content: chatInput.trim(), action_type: 'message', touch_key: null }
    if (!payload.content && payload.action_type !== 'touch') return
    try {
      await send(payload)
      setChatInput('')
    } catch {
      /* error 已写入 hook */
    }
  }

  const doTouch = (action) => {
    const label = isZh ? action.label_zh : action.label_en
    doSend({ content: `${action.emoji || '✋'} ${label}`, action_type: 'touch', touch_key: action.key })
    setTouchPanelOpen(false)
  }

  return (
    <div className="flex-[4] flex flex-col bg-card border border-border rounded-lg overflow-hidden min-h-0">
      <BabyHeader
        babyId={babyId}
        babyStatus={babyStatus}
        connected={connected}
        isZh={isZh}
        tk={tk}
      />

      {/* 消息区 */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2" ref={scrollRef}>
        {messages.length === 0 && !ensuring && (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-2">
            <span className="text-sm">
              {isZh ? '与宝宝互动，了解他的世界' : 'Interact with baby, explore their world'}
            </span>
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.seq} msg={m} isZh={isZh} />
        ))}
        {sending && (
          <div className="text-[11px] text-muted-foreground italic animate-pulse pl-11">
            {isZh ? '宝宝思考中...' : 'Thinking...'}
          </div>
        )}
        {error && (
          <div className="text-xs text-red-400 px-2 py-1 bg-red-500/10 rounded">
            {error}
          </div>
        )}
      </div>

      {/* 肢体动作面板 */}
      {touchPanelOpen && touchActions?.actions && (
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
                      disabled={sending}
                      onClick={() => doTouch(a)}
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

      {/* 输入 */}
      <div className="shrink-0 border-t border-border p-3 flex items-center gap-2">
        <button
          className={cn(
            'w-9 h-9 rounded-md flex items-center justify-center transition-colors shrink-0 cursor-pointer',
            touchPanelOpen ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-muted/80',
          )}
          onClick={() => {
            if (!touchActions) loadTouchActions?.()
            setTouchPanelOpen((v) => !v)
          }}
          title={isZh ? '肢体互动' : 'Touch interaction'}
        >
          <Hand className="size-4" />
        </button>
        <Input
          ref={inputRef}
          type="text"
          className="flex-1 h-9 rounded-md"
          placeholder={
            pendingNeed
              ? (isZh ? '宝宝在等你回应...' : 'Baby is waiting for you...')
              : (isZh ? '说点什么...' : 'Say something...')
          }
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              doSend()
            }
          }}
          disabled={sending || !convReady}
        />
        <button
          className={cn(
            'w-9 h-9 rounded-md flex items-center justify-center transition-colors shrink-0',
            chatInput.trim() && !sending && convReady
              ? 'bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer'
              : 'bg-muted text-muted-foreground cursor-not-allowed',
          )}
          onClick={() => doSend()}
          disabled={sending || !convReady || !chatInput.trim()}
        >
          <Send className="size-4" />
        </button>
      </div>
    </div>
  )
}


function BabyHeader({ babyId, babyStatus, connected, isZh, tk }) {
  if (!babyStatus) return null
  const days = babyStatus.age_days || 0
  const y = Math.floor(days / 365)
  const m = Math.floor((days % 365) / 30)
  const ageText =
    y > 0 ? `${y}${isZh ? '岁' : 'y'}${m > 0 ? `${m}${isZh ? '月' : 'mo'}` : ''}`
    : m > 0 ? `${m}${isZh ? '个月' : 'mo'}${days % 30}${isZh ? '天' : 'd'}`
    : `${days}${isZh ? '天' : 'd'}`

  return (
    <div className="shrink-0 border-b border-border p-4">
      <div className="flex items-start gap-3">
        <Avatar size="lg">
          <AvatarImage src={portraitUrl(babyId)} />
          <AvatarFallback className={cn('text-xs font-mono font-semibold', avatarPalette(babyId).bg, avatarPalette(babyId).text)}>
            {shortId(babyId)}
          </AvatarFallback>
        </Avatar>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm">{babyStatus.name || babyId}</span>
            <span className="text-xs text-muted-foreground">@{babyStatus.species}</span>
            <span className="text-[10px] px-1.5 py-0.5 bg-primary/10 text-primary rounded-full capitalize">
              {tk ? tk(babyStatus.expression_mode || '') : babyStatus.expression_mode}
            </span>
            <span
              className={cn(
                'ml-auto text-[10px] px-1.5 py-0.5 rounded-full',
                connected ? 'bg-emerald-500/10 text-emerald-500' : 'bg-muted text-muted-foreground',
              )}
              title={connected ? 'SSE connected' : 'SSE disconnected'}
            >
              {connected ? (isZh ? '在线' : 'online') : (isZh ? '离线' : 'offline')}
            </span>
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            {tk ? tk(babyStatus.current_phase?.name || '') : babyStatus.current_phase?.name} · {ageText} · {tk ? tk(babyStatus.attachment_style || 'forming') : babyStatus.attachment_style}
          </div>
        </div>
      </div>
    </div>
  )
}


/** 找最近一条 subtype=need 之后是否尚未有家长回复。 */
function findPendingNeed(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.role === 'parent') return null
    if (m.subtype === 'need') return m
  }
  return null
}
