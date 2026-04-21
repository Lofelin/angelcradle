/**
 * [INPUT]: react, lucide-react, @/lib/utils, @/components/ui/*, hooks/useConversation, ./MessageBubble, ./chatHelpers
 * [OUTPUT]: GroupChatPanel — 多宝宝群聊面板（group 会话）
 * [POS]: 摇篮 tab 聊天区，由选中多个宝宝后创建群触发；独立于 ChatPanel（单聊）
 * [PROTOCOL]: 变更时更新此头部，然后检查 src/CLAUDE.md
 */
import { useEffect, useRef, useState } from 'react'
import { Pencil, Send } from 'lucide-react'

import { Avatar, AvatarImage, AvatarFallback, AvatarGroup } from '@/components/ui/avatar'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

import { useConversation } from '../hooks/useConversation'
import MessageBubble from './MessageBubble'
import { shortId, avatarPalette, portraitUrl } from './chatHelpers'

/**
 * @param {{
 *   convId: string,
 *   isZh: boolean,
 *   onClose?: () => void,   // 关闭按钮回调（交给 Cradle.jsx 管理路由/state）
 * }} props
 */
export default function GroupChatPanel({ convId, isZh, onClose }) {
  const [chatInput, setChatInput] = useState('')
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const inputRef = useRef(null)
  const scrollRef = useRef(null)

  const { meta, messages, connected, sending, error, send, rename } = useConversation(convId)

  // meta 变化时同步草稿
  useEffect(() => {
    if (meta?.display_name) setNameDraft(meta.display_name)
  }, [meta?.display_name])

  // 自动滚底
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages.length])

  const doSend = async () => {
    const content = chatInput.trim()
    if (!content) return
    try {
      await send({ content })
      setChatInput('')
    } catch {
      /* error 已写入 hook */
    }
  }

  const saveRename = async () => {
    const nn = nameDraft.trim()
    if (!nn || nn === meta?.display_name) {
      setEditingName(false)
      return
    }
    try {
      await rename(nn)
    } finally {
      setEditingName(false)
    }
  }

  const participants = meta?.participants || []
  const icebreakerDone = meta?.icebreaker_done

  return (
    <div className="flex-[4] flex flex-col bg-card border border-border rounded-lg overflow-hidden min-h-0">
      {/* 群头部：头像组 + 可编辑群名 */}
      <div className="shrink-0 border-b border-border p-4">
        <div className="flex items-center gap-3">
          <AvatarGroup>
            {participants.slice(0, 4).map((bid) => (
              <Avatar key={bid}>
                <AvatarImage src={portraitUrl(bid)} />
                <AvatarFallback
                  className={cn(
                    'text-[9px] font-mono tracking-tighter font-semibold',
                    avatarPalette(bid).bg,
                    avatarPalette(bid).text,
                  )}
                >
                  {shortId(bid)}
                </AvatarFallback>
              </Avatar>
            ))}
          </AvatarGroup>
          <div className="flex-1 min-w-0">
            {editingName ? (
              <Input
                autoFocus
                className="h-7 text-sm"
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onBlur={saveRename}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); saveRename() }
                  if (e.key === 'Escape') { setNameDraft(meta?.display_name || ''); setEditingName(false) }
                }}
              />
            ) : (
              <div className="flex items-center gap-1.5">
                <span className="font-semibold text-sm truncate">
                  {meta?.display_name || (isZh ? '(未命名群)' : '(unnamed group)')}
                </span>
                <button
                  className="text-muted-foreground hover:text-foreground cursor-pointer"
                  onClick={() => setEditingName(true)}
                  title={isZh ? '重命名' : 'Rename'}
                >
                  <Pencil className="size-3" />
                </button>
              </div>
            )}
            <div className="text-xs text-muted-foreground">
              {participants.length} {isZh ? '位宝宝' : 'babies'}
              {' · '}
              <span
                className={connected ? 'text-emerald-500' : 'text-muted-foreground'}
              >
                {connected ? (isZh ? '在线' : 'online') : (isZh ? '离线' : 'offline')}
              </span>
              {icebreakerDone ? '' : ` · ${isZh ? '等待首次破冰' : 'awaiting icebreaker'}`}
            </div>
          </div>
          {onClose && (
            <button
              className="text-xs text-muted-foreground hover:text-foreground cursor-pointer px-2 py-1 rounded border border-border"
              onClick={onClose}
            >
              {isZh ? '关闭' : 'Close'}
            </button>
          )}
        </div>
      </div>

      {/* 消息区 */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-2">
            <span className="text-sm">
              {isZh
                ? '说点什么打破冷场 —— 宝宝们会挨个回应'
                : 'Say something to break the ice — babies will respond one by one'}
            </span>
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.seq} msg={m} isZh={isZh} />
        ))}
        {sending && (
          <div className="text-[11px] text-muted-foreground italic animate-pulse pl-11">
            {isZh ? '宝宝们正在回应...' : 'Babies responding...'}
          </div>
        )}
        {error && (
          <div className="text-xs text-red-400 px-2 py-1 bg-red-500/10 rounded">
            {error}
          </div>
        )}
      </div>

      {/* 输入 */}
      <div className="shrink-0 border-t border-border p-3 flex items-center gap-2">
        <Input
          ref={inputRef}
          type="text"
          className="flex-1 h-9 rounded-md"
          placeholder={isZh ? '对孩子们说点什么...' : 'Say something to the kids...'}
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              doSend()
            }
          }}
          disabled={sending || !meta}
        />
        <button
          className={cn(
            'w-9 h-9 rounded-md flex items-center justify-center transition-colors shrink-0',
            chatInput.trim() && !sending && meta
              ? 'bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer'
              : 'bg-muted text-muted-foreground cursor-not-allowed',
          )}
          onClick={doSend}
          disabled={sending || !meta || !chatInput.trim()}
        >
          <Send className="size-4" />
        </button>
      </div>
    </div>
  )
}
