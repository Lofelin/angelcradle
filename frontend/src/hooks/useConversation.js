/**
 * [INPUT]: react（useState/useEffect/useRef/useCallback）
 * [OUTPUT]: useConversation(convId) hook — 订阅单个会话 SSE + 发送家长消息
 * [POS]: frontend hooks 层，供 ChatPanel / GroupChatPanel 消费；与 useLifeline 对齐的 SSE 订阅抽象
 * [PROTOCOL]: 变更时更新此头部，然后检查 hooks/CLAUDE.md 与 src/CLAUDE.md
 */
import { useCallback, useEffect, useRef, useState } from 'react'

const API = 'http://localhost:8000'

/**
 * @param {string|null} convId - 会话 ID，null 时不建立连接
 * @returns {{
 *   meta: object|null,           // 会话元信息（participants/kind/display_name/...）
 *   messages: Array,             // 已接收消息（按 seq 升序去重）
 *   connected: boolean,          // SSE 连接状态
 *   sending: boolean,            // 家长发送中
 *   error: string|null,          // 最近一次错误
 *   send: (payload) => Promise,  // 家长发消息
 *   rename: (name) => Promise,   // 重命名会话
 *   reload: () => void,          // 强制重载 meta
 * }}
 */
export function useConversation(convId) {
  const [meta, setMeta] = useState(null)
  const [messages, setMessages] = useState([])
  const [connected, setConnected] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)

  // 用 ref 跟踪已见 seq，避免 StrictMode 双渲染导致重复
  const seenSeqRef = useRef(new Set())
  const sourceRef = useRef(null)

  // 加载会话元信息
  const loadMeta = useCallback(async () => {
    if (!convId) return
    try {
      const r = await fetch(`${API}/conversations/${encodeURIComponent(convId)}`)
      if (!r.ok) throw new Error(await r.text())
      setMeta(await r.json())
    } catch (e) {
      setError(String(e.message || e))
    }
  }, [convId])

  // convId 变化：REST 拉历史 + SSE 订阅增量
  const lastSeqRef = useRef(0)

  useEffect(() => {
    seenSeqRef.current = new Set()
    setMessages([])
    setMeta(null)
    setError(null)
    lastSeqRef.current = 0
    if (!convId) return

    let closed = false
    let reconnectTimer = null

    // Phase 1: REST 一次性拉全量历史（瞬间到位，无逐条滚动）
    // Phase 2: SSE 从最新 seq 订阅增量（仅新消息触发滚动）
    const init = async () => {
      loadMeta()
      try {
        const r = await fetch(
          `${API}/conversations/${encodeURIComponent(convId)}/messages?after_seq=0`,
        )
        if (r.ok) {
          const { messages: history } = await r.json()
          if (!closed && history?.length > 0) {
            for (const m of history) {
              if (m.seq != null) seenSeqRef.current.add(m.seq)
            }
            lastSeqRef.current = history[history.length - 1].seq || 0
            setMessages(history)
          }
        }
      } catch { /* SSE 兜底 */ }
      if (!closed) connect()
    }

    const connect = () => {
      if (closed) return
      const src = new EventSource(
        `${API}/conversations/${encodeURIComponent(convId)}/stream?after_seq=${lastSeqRef.current}`,
      )
      sourceRef.current = src
      src.onopen = () => setConnected(true)
      src.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          const s = msg.seq
          if (s == null) return
          if (seenSeqRef.current.has(s)) return
          seenSeqRef.current.add(s)
          lastSeqRef.current = Math.max(lastSeqRef.current, s)
          setMessages((prev) => {
            if (prev.length === 0 || prev[prev.length - 1].seq < s) {
              return [...prev, msg]
            }
            const copy = [...prev, msg]
            copy.sort((a, b) => (a.seq || 0) - (b.seq || 0))
            return copy
          })
        } catch {
          /* ignore malformed */
        }
      }
      src.onerror = () => {
        setConnected(false)
        src.close()
        if (!closed) reconnectTimer = setTimeout(connect, 3000)
      }
    }

    init()
    return () => {
      closed = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (sourceRef.current) sourceRef.current.close()
      setConnected(false)
    }
  }, [convId, loadMeta])

  // 家长发消息
  const send = useCallback(
    async ({ content, action_type = 'message', touch_key = null } = {}) => {
      if (!convId) throw new Error('No active conversation')
      if (!content && action_type !== 'touch') throw new Error('content required')
      setSending(true)
      setError(null)
      try {
        const r = await fetch(
          `${API}/conversations/${encodeURIComponent(convId)}/messages`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content, action_type, touch_key }),
          },
        )
        if (!r.ok) throw new Error(await r.text())
        // messages 由 SSE 推送，这里不重复 set
        return await r.json()
      } catch (e) {
        setError(String(e.message || e))
        throw e
      } finally {
        setSending(false)
      }
    },
    [convId],
  )

  // 重命名
  const rename = useCallback(
    async (displayName) => {
      if (!convId) throw new Error('No active conversation')
      const r = await fetch(
        `${API}/conversations/${encodeURIComponent(convId)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ display_name: displayName }),
        },
      )
      if (!r.ok) throw new Error(await r.text())
      const m = await r.json()
      setMeta(m)
      return m
    },
    [convId],
  )

  return { meta, messages, connected, sending, error, send, rename, reload: loadMeta }
}


/**
 * 便捷：通过 (participants, kind, displayName?) 建会话并返回 conv_id。
 * 调用方通常再把 conv_id 传给 useConversation。
 */
export async function createConversation({ participants, kind, displayName }) {
  const r = await fetch(`${API}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      participants,
      kind,
      display_name: displayName ?? null,
    }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}


/** 按 baby_id 列出该 baby 参与的会话。 */
export async function listConversations(babyId) {
  const url = babyId
    ? `${API}/conversations?baby_id=${encodeURIComponent(babyId)}`
    : `${API}/conversations`
  const r = await fetch(url)
  if (!r.ok) throw new Error(await r.text())
  const { conversations } = await r.json()
  return conversations
}
