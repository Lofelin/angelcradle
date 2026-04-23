/**
 * [INPUT]: react, @/lib/utils
 * [OUTPUT]: ConsolePanel 通用控制台面板组件
 * [POS]: 子宫和摇篮共用的终端风格控制台壳
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */
import { forwardRef } from 'react'
import { cn } from '@/lib/utils'

/**
 * 终端风格控制台面板
 * @param {object} props
 * @param {React.ReactNode} props.header - 顶栏状态指示器内容
 * @param {React.ReactNode} props.headerRight - 顶栏右侧附加内容（如全屏按钮）
 * @param {React.ReactNode} props.children - 日志内容
 * @param {React.ReactNode} props.footer - 底部附加区域（如关键事件）
 * @param {string} props.className - 外层额外 class
 * @param {number} props.headerHeight - 顶栏高度，默认 32
 */
const ConsolePanel = forwardRef(({ header, headerRight, children, footer, className, headerHeight = 32 }, ref) => (
  <div className={cn(
    "flex flex-col bg-[#1C1C1C] overflow-hidden shadow-[0_4px_24px_rgba(0,0,0,0.3),0_0_0_0.5px_rgba(255,255,255,0.08)_inset]",
    className,
  )}>
    {/* 顶栏 */}
    <div
      className="bg-[#2D2D2D] border-b border-[#1a1a1a] flex items-center px-3.5 shrink-0 relative"
      style={{ height: headerHeight }}
    >
      <div className="text-xs text-[#999] flex-1 min-w-0 flex justify-center">
        {header}
      </div>
      {headerRight && (
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center">
          {headerRight}
        </div>
      )}
    </div>
    {/* 日志区 */}
    <div className="console" ref={ref}>
      {children}
    </div>
    {/* 底部（关键事件等） */}
    {footer}
  </div>
))

ConsolePanel.displayName = 'ConsolePanel'

export default ConsolePanel
