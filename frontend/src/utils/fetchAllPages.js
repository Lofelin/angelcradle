/**
 * [INPUT]: 原生 fetch
 * [OUTPUT]: fetchAllPages(url, { pageSize, signal, max }) — 返回扁平聚合后的 babies 列表
 * [POS]: 前端分页聚合工具；后端 /babies 与 /cradle/babies 已改为分页（每页上限 100），
 *        本 helper 在请求方合并全部页，保持调用方（Cradle/WorldMap）原有"拿到完整列表"语义。
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */

const DEFAULT_PAGE_SIZE = 100
// 安全闸门：最多拉 1000 页（= 10 万条），防止后端异常导致无限翻页
const MAX_PAGES_DEFAULT = 1000

/**
 * 分页聚合 fetcher。按 page_size 翻页直到 has_more=false 或 total_pages 耗尽。
 *
 * 响应契约（后端）：
 *   { babies: [...], page, page_size, total, total_pages, has_more }
 *
 * 失败返回空数组（与旧 .catch(() => ({ babies: [] })) 行为对齐）。
 */
export async function fetchAllPages(
  baseUrl,
  { pageSize = DEFAULT_PAGE_SIZE, signal, maxPages = MAX_PAGES_DEFAULT } = {}
) {
  const join = baseUrl.includes('?') ? '&' : '?'
  const all = []
  let page = 1
  try {
    // 先取第 1 页拿到 total_pages，再按页号并发拉剩余页
    const firstUrl = `${baseUrl}${join}page=1&page_size=${pageSize}`
    const firstResp = await fetch(firstUrl, { signal })
    if (!firstResp.ok) return []
    const first = await firstResp.json()
    const firstList = first.babies || []
    all.push(...firstList)

    const totalPages = Number(first.total_pages || 0)
    if (totalPages <= 1) return all

    const last = Math.min(totalPages, maxPages)
    const tail = []
    for (page = 2; page <= last; page += 1) {
      const url = `${baseUrl}${join}page=${page}&page_size=${pageSize}`
      tail.push(
        fetch(url, { signal })
          .then(r => (r.ok ? r.json() : { babies: [] }))
          .then(j => j.babies || [])
          .catch(() => [])
      )
    }
    const chunks = await Promise.all(tail)
    for (const c of chunks) all.push(...c)
    return all
  } catch {
    return all
  }
}
