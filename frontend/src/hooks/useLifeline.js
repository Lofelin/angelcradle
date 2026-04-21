/**
 * [INPUT]: react（useEffect/useRef/useState）
 * [OUTPUT]: useLifeline(babyId, { onEvent, enabled }) hook — 订阅单个宝宝的 lifeline SSE
 * [POS]: frontend hooks 层，供 Cradle.jsx 消费控制台日志流；与 useConversation 通道独立
 * [PROTOCOL]: 变更时更新此头部，然后检查 hooks/CLAUDE.md 与 src/CLAUDE.md
 */
import { useEffect, useRef, useState } from 'react'

const API = 'http://localhost:8000'
// localStorage 游标 key（与旧 Cradle.jsx 保持兼容：lastSeq_{babyId}）
const seqKey = (babyId) => `lastSeq_${babyId}`

/**
 * 订阅 /cradle/{babyId}/lifeline 的 SSE（后端已通过 _LIFELINE_BLOCKLIST 过滤
 * interaction / conversation_message / baby_need / need_responded / heartbeat_*）。
 *
 * @param {string|null} babyId - 目标宝宝，null 时不连接
 * @param {{
 *   onEvent: (data: object) => void,  // 每条 SSE 事件的回调（纯函数，hook 内部不做 reducer）
 *   enabled?: boolean,                 // 条件启用（默认 true）
 *   reconnectMs?: number,              // 错误后重连间隔（默认 3000）
 * }} options
 * @returns {{ connected: boolean }}
 */
export function useLifeline(babyId, { onEvent, enabled = true, reconnectMs = 3000 } = {}) {
  const [connected, setConnected] = useState(false)
  // 用 ref 追踪回调，避免每次回调变引用时重建连接
  const onEventRef = useRef(onEvent)
  useEffect(() => { onEventRef.current = onEvent }, [onEvent])

  useEffect(() => {
    if (!enabled || !babyId) return

    let closed = false
    let src = null
    let reconnectTimer = null

    const connect = () => {
      if (closed) return
      const seq = parseInt(localStorage.getItem(seqKey(babyId)) || '0', 10)
      src = new EventSource(`${API}/cradle/${babyId}/lifeline?after_seq=${seq}`)
      src.onopen = () => setConnected(true)
      src.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          if (data.seq) {
            localStorage.setItem(seqKey(babyId), String(data.seq))
          }
          if (onEventRef.current) onEventRef.current(data)
        } catch {
          /* ignore malformed */
        }
      }
      src.onerror = () => {
        setConnected(false)
        src.close()
        if (!closed) reconnectTimer = setTimeout(connect, reconnectMs)
      }
    }

    connect()
    return () => {
      closed = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (src) src.close()
      setConnected(false)
    }
  }, [babyId, enabled, reconnectMs])

  return { connected }
}
