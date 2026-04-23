/**
 * [INPUT]: react, maplibre-gl, maplibre-gl/dist/maplibre-gl.css
 * [OUTPUT]: WorldMap 组件 —— MapLibre GL + OpenFreeMap positron 底图 + 宝宝散点 + 悬浮卡片 + IP 定位 + 无宝宝时随机高亮
 * [POS]: 世界模块的 2D 世界视图；散点数据来自分页 /babies（+ /cradle/babies 补名字），
 *        进入地图先从 localStorage 缓存渲染，再每 500ms 拉下一页增量合并，末页落 localStorage；
 *        默认选中的散点会异步拉 /baby/{id} 刷新资料卡 name/species/birthplace 等字段。
 * [PROTOCOL]: 变更时更新此头部，然后检查 components/ 与 src/ 的 CLAUDE.md
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { MessageCircle, Network, X } from 'lucide-react'
import ChatPanel from './ChatPanel'
import { DEFAULT_TOUCH_ACTIONS, fetchTouchActions } from './chatHelpers'
import CITY_ZH from '../data/cityZh'
import COUNTRY_ZH from '../data/countryZh'
import { fetchAllPages } from '../utils/fetchAllPages'

const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'
const API = 'http://localhost:8000'
const portraitUrl = (id) => `${API}/cradle/baby/${encodeURIComponent(id)}/portrait`

// 分页与缓存参数：/babies 每页 100，每 500ms 拉一页；缓存 schema 版本用于字段演进时失效。
const BABIES_PAGE_SIZE = 100
const BABIES_PAGE_INTERVAL_MS = 500
const BABIES_CACHE_KEY = 'worldmap:babiesFeatures'
const BABIES_CACHE_VERSION = 1

function readBabiesCache() {
  try {
    const raw = localStorage.getItem(BABIES_CACHE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (parsed?.v !== BABIES_CACHE_VERSION) return []
    return Array.isArray(parsed.features) ? parsed.features : []
  } catch {
    return []
  }
}

function writeBabiesCache(features) {
  try {
    localStorage.setItem(
      BABIES_CACHE_KEY,
      JSON.stringify({ v: BABIES_CACHE_VERSION, ts: Date.now(), features }),
    )
  } catch {
    /* quota exceeded 时降级：静默丢弃缓存，下次进入走纯接口 */
  }
}

/** 合并 /conceive/babies（全量 born 宝宝）+ /cradle/babies（已入篮宝宝，含 name）为 GeoJSON
 *  properties.city 存英文原名，isZh 下的译名由渲染消费层（popup / 右侧卡）按 CITY_ZH 查表
 */
function babiesToFeatures(bornList, cradleList) {
  const cradleById = new Map()
  for (const b of cradleList || []) {
    cradleById.set(b.baby_id, b)
  }
  return (bornList || [])
    .map((b) => {
      const id = b.baby_id || b.id
      if (!id) return null
      const coords = b?.birthplace?.coordinates || {}
      const lng = Number(coords.lng)
      const lat = Number(coords.lat)
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null
      const cradle = cradleById.get(id)
      // 未命名 baby 回退到物种名（首字母大写），与 Cradle BabyCard 的 tk(species) 策略同构，避免暴露原始 ID
      const species = (b.species || '').toString()
      const speciesLabel = species ? species.charAt(0).toUpperCase() + species.slice(1) : ''
      const name = cradle?.name || b.name || speciesLabel || id
      return {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [lng, lat] },
        properties: {
          baby_id: id,
          name,
          city: b?.birthplace?.city || '',
          country: b?.birthplace?.name || '',
          country_code: String(b?.birthplace?.code || '').toUpperCase(),
        },
      }
    })
    .filter(Boolean)
}

/** isZh 下把英文城市名查 CITY_ZH 译成中文，缺失 fallback 英文。 */
function displayCityName(raw, isZh) {
  if (!raw) return ''
  return isZh ? (CITY_ZH[raw] || raw) : raw
}

/** isZh 下按 ISO code 查 COUNTRY_ZH，缺失 fallback 英文 country 名 */
function displayCountryName(country, code, isZh) {
  if (isZh && code && COUNTRY_ZH[code]) return COUNTRY_ZH[code]
  return country || ''
}

// ── 组件内 i18n ─────────────────────────────────────────
// 资料卡按钮 / aria-label / 空占位 / hover popup 标签 全部走 lang 切换
const I18N = {
  en: { interact: 'Interact', collapse: 'Collapse', graph: 'Graph', close: 'Close', empty: '—' },
  zh: { interact: '互动', collapse: '收起', graph: '关系网', close: '关闭', empty: '—' },
}

export default function WorldMap({ lang = 'en' }) {
  const L = I18N[lang] || I18N.en
  const isZh = lang === 'zh'
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const popupRef = useRef(null)
  // 高亮散点的 (lng, lat)；null = 无高亮。渲染走和 babies 同一条 WebGL 管线，永不漂移
  const highlightCoordRef = useRef(null)
  // 高亮环脉冲动画的 requestAnimationFrame id，用于组件卸载时 cancel
  const pulseRafRef = useRef(0)
  // 右侧滑入卡片的当前选中宝宝；null = 卡片收起
  const [selected, setSelected] = useState(null)
  // displayed 跟随 selected，但 selected→null 时延迟 380ms 再清空（与切换宝宝的滑出缓冲对齐），
  // 让旧卡片内容在 CSS transform 滑出动画期间保持挂载可见
  const [displayed, setDisplayed] = useState(null)
  useEffect(() => {
    if (selected) { setDisplayed(selected); return }
    const t = setTimeout(() => setDisplayed(null), 380)
    return () => clearTimeout(t)
  }, [selected])
  // 卡片是否切换到互动对话视图（false = 展示资料 + 操作按钮）
  const [chatOpen, setChatOpen] = useState(false)
  // useEffect 内闭包需要读最新 selected（用于切换宝宝时的滑出→滑入过渡）
  const selectedRef = useRef(null)
  useEffect(() => { selectedRef.current = selected }, [selected])
  // 肢体互动列表：默认值铺底，Hand 按钮首次点击懒加载真实后端数据
  const [touchActions, setTouchActions] = useState(DEFAULT_TOUCH_ACTIONS)
  const touchLoadedRef = useRef(null)  // 记录已为哪个 baby_id 拉过，避免重复请求
  const loadTouchActions = async () => {
    const id = selectedRef.current?.baby_id
    if (!id || touchLoadedRef.current === id) return
    touchLoadedRef.current = id
    const data = await fetchTouchActions(id)
    if (data) setTouchActions(data)
  }
  const navigate = useNavigate()

  useEffect(() => {
    if (!containerRef.current) return

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      center: [10, 30],
      zoom: 1.8,
      minZoom: 1,
      attributionControl: false,
      renderWorldCopies: true,
    })
    mapRef.current = map

    // 串行控制：避免 babies 未加载前 IP locate 就判断"没宝宝"
    let styleLoaded = false
    let babiesFeatures = null  // null = 未加载；[] = 已加载但空

    const ro = new ResizeObserver(() => { try { map.resize() } catch { /* noop */ } })
    ro.observe(containerRef.current)

    const ctrl = new AbortController()
    let geoCancelled = false

    // ── IP 定位端点（并发 race）─────────────────────────────────
    const resolveIp = async () => {
      const endpoints = [
        { url: 'https://ipwho.is/', pick: d => d.success && { lng: d.longitude, lat: d.latitude, code: String(d.country_code || '').toUpperCase() } },
        { url: 'https://ipapi.co/json/', pick: d => !d.error && { lng: d.longitude, lat: d.latitude, code: String(d.country_code || d.country || '').toUpperCase() } },
        { url: 'https://get.geojs.io/v1/ip/geo.json', pick: d => ({ lng: +d.longitude, lat: +d.latitude, code: String(d.country_code || '').toUpperCase() }) },
      ]
      const timeout = setTimeout(() => ctrl.abort(), 1500)
      const probe = ep => fetch(ep.url, { cache: 'force-cache', signal: ctrl.signal })
        .then(r => r.ok ? r.json() : Promise.reject())
        .then(d => {
          const loc = ep.pick(d)
          if (!loc || !Number.isFinite(loc.lat) || !Number.isFinite(loc.lng)) throw new Error('bad')
          return loc
        })
      try {
        // sessionStorage 缓存
        const cached = sessionStorage.getItem('worldmap.geo')
        if (cached) {
          const parsed = JSON.parse(cached)
          if (Number.isFinite(parsed?.lng) && Number.isFinite(parsed?.lat)) {
            clearTimeout(timeout)
            return parsed
          }
        }
        const loc = await Promise.any(endpoints.map(probe))
        clearTimeout(timeout)
        try { sessionStorage.setItem('worldmap.geo', JSON.stringify(loc)) } catch { /* ignore */ }
        return loc
      } catch { clearTimeout(timeout); return null }
    }

    // ── 默认选中的生命体数据从接口获取：异步拉 /baby/{id}，merge 进 selected ──
    // 点击散点的 selected 仍直接用 feature 属性（本地渲染够用，避免每次点击都发请求）。
    const hydrateSelectedFromApi = (babyId) => {
      if (!babyId || geoCancelled) return
      fetch(`${API}/baby/${encodeURIComponent(babyId)}`, { signal: ctrl.signal })
        .then(r => r.ok ? r.json() : null)
        .catch(() => null)
        .then(detail => {
          if (!detail || geoCancelled) return
          setSelected(prev => {
            if (!prev || prev.baby_id !== babyId) return prev  // 用户已切换到别的宝宝
            const bp = detail.birthplace || {}
            return {
              ...prev,
              species: detail.species ?? prev.species,
              sex: detail.sex ?? prev.sex,
              name: detail.name || prev.name,
              city: bp.city ?? prev.city,
              country: bp.name ?? prev.country,
              country_code: String(bp.code || prev.country_code || '').toUpperCase(),
              born_at: detail.born_at ?? prev.born_at,
              detail,
            }
          })
        })
    }

    // ── 决定飞行目的地：有宝宝在 IP 国家 → 飞 IP；否则随机挑一个宝宝，高亮 + 飞它 ──
    const decideAndFly = (ipLoc, features) => {
      if (geoCancelled) return
      if (ipLoc && features && features.length > 0) {
        const sameCountry = features.filter(f => f.properties.country_code && f.properties.country_code === ipLoc.code)
        if (sameCountry.length > 0) {
          map.flyTo({ center: [ipLoc.lng, ipLoc.lat], zoom: 2.5, speed: 1.2, essential: true })
          return
        }
        // 本国无宝宝 → 随机挑一个高亮 + 打开右侧资料卡
        const pick = features[Math.floor(Math.random() * features.length)]
        const [lng, lat] = pick.geometry.coordinates
        const p = pick.properties
        setHighlightMarker(p.baby_id, lng, lat)
        setSelected({ baby_id: p.baby_id, name: p.name, city: p.city, country: p.country, country_code: p.country_code, lng, lat })
        setChatOpen(false)
        map.flyTo({ center: [lng, lat], zoom: 2.5, speed: 1.2, essential: true })
        hydrateSelectedFromApi(p.baby_id)
        return
      }
      // IP 有，没宝宝 → 单飞 IP
      if (ipLoc) {
        map.flyTo({ center: [ipLoc.lng, ipLoc.lat], zoom: 2.5, speed: 1.2, essential: true })
      }
      // IP 都没 → 保持默认视图
    }

    const setHighlightMarker = (_babyId, lng, lat) => {
      // 走和 babies-point 同一条 WebGL 管线：把高亮点写入独立 GeoJSON source
      // 不用 DOM Marker 避免高缩放下 CSS transform 与 tile 坐标管线错位
      highlightCoordRef.current = { lng, lat }
      const src = map.getSource('highlight')
      if (src) {
        src.setData({
          type: 'FeatureCollection',
          features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [lng, lat] }, properties: {} }],
        })
      }
    }

    // ── popup ────────────────────────────────────────────────
    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 14,
      className: 'wm-popup',
      maxWidth: 'none',
    })
    popupRef.current = popup

    const showCard = (lngLat, props) => {
      const city = displayCityName(props.city, isZh)
      const country = displayCountryName(props.country, props.country_code, isZh)
      const sep = isZh ? '，' : ', '
      const place = city
        ? `${city}${country ? sep + country : ''}`
        : country
      popup
        .setLngLat(lngLat)
        .setHTML(`
          <div class="wm-card">
            <img class="wm-card-avatar" src="${portraitUrl(props.baby_id)}" alt="" onerror="this.style.visibility='hidden'" />
            <div class="wm-card-text">
              <div class="wm-card-name">${escapeHtml(props.name)}</div>
              <div class="wm-card-country">${escapeHtml(place)}</div>
            </div>
          </div>
        `)
        .addTo(map)
    }

    // ── 地图 + 样式加载后挂图层 + 交互 ───────────────────────
    const onLoad = () => {
      styleLoaded = true
      map.resize()

      // 海洋配色：OFM positron 默认 water fill = rgb(194,200,202)（#c2c8ca），
      // 调浅一档到 #d6dbdd，看上去更通透、不与陆地灰对比过强
      try { map.setPaintProperty('water', 'fill-color', '#d6dbdd') } catch { /* ignore */ }

      // 标签显示阈值：国家名 ≥ 3.6，城市名（含首都/town）≥ 5.0。
      // 原 OFM positron 的 label_country_* 从 z=0~2 就开始显示，label_city 从 z=3 起；
      // 用 setLayerZoomRange 把 minzoom 上抬，避免小比例尺下标签堆叠。
      const COUNTRY_LAYERS = ['label_country_1', 'label_country_2', 'label_country_3']
      const CITY_LAYERS = ['label_city', 'label_city_capital', 'label_town']
      // 国家名统一换成与海洋注记同系的冷灰蓝，白色 halo 保持可读
      const COUNTRY_TEXT_COLOR = '#7c8ca6'
      const COUNTRY_HALO_COLOR = 'rgba(255,255,255,0.9)'
      // 原 OFM positron 的 text-field 是 case(has(name:nonlatin) → "latin\nnonlatin" : name_en)，
      // 会把印度写成 "India\nभारत" —— 改为始终只取英文/拉丁文。
      const ENGLISH_ONLY_TEXT_FIELD = ['coalesce', ['get', 'name:latin'], ['get', 'name_en'], ['get', 'name']]
      for (const id of COUNTRY_LAYERS) {
        if (!map.getLayer(id)) continue
        map.setLayerZoomRange(id, 3.6, 24)
        try { map.setLayoutProperty(id, 'text-field', ENGLISH_ONLY_TEXT_FIELD) } catch { /* ignore */ }
        try { map.setLayoutProperty(id, 'text-font', ['Noto Sans Regular']) } catch { /* ignore */ }
        try { map.setPaintProperty(id, 'text-color', COUNTRY_TEXT_COLOR) } catch { /* ignore */ }
        try { map.setPaintProperty(id, 'text-halo-color', COUNTRY_HALO_COLOR) } catch { /* ignore */ }
        try { map.setPaintProperty(id, 'text-halo-width', 1.2) } catch { /* ignore */ }
      }
      // 城市名：中国境内显示中文，其他国家显示英文。
      // OpenMapTiles 的 place 要素没有 country_code，但 OSM 的 `name` 字段就是"本地通用名"——
      // 对中国城市而言 `name` 本身即中文，且 `name:zh` 通常与 `name` 相等；
      // 以 `name == name:zh` 作为"这是中国城市"的稳健启发式，是则取 `name:zh`，否则英文回退。
      const CITY_TEXT_FIELD = [
        'case',
        ['all', ['has', 'name:zh'], ['==', ['get', 'name:zh'], ['get', 'name']]],
        ['get', 'name:zh'],
        ['coalesce', ['get', 'name:latin'], ['get', 'name_en'], ['get', 'name']],
      ]
      for (const id of CITY_LAYERS) {
        if (!map.getLayer(id)) continue
        map.setLayerZoomRange(id, 5.0, 24)
        try { map.setLayoutProperty(id, 'text-field', CITY_TEXT_FIELD) } catch { /* ignore */ }
        // 首都原本用 Bold，统一回 Regular 和国家名保持一致纤细感
        try { map.setLayoutProperty(id, 'text-font', ['Noto Sans Regular']) } catch { /* ignore */ }
      }

      // 海洋/河流/水体注记：同样把 "latin + nonlatin" 拼接改为只取英文
      const WATER_LABEL_LAYERS = ['water_name_point_label', 'water_name_line_label', 'waterway_line_label']
      for (const id of WATER_LABEL_LAYERS) {
        if (!map.getLayer(id)) continue
        try { map.setLayoutProperty(id, 'text-field', ENGLISH_ONLY_TEXT_FIELD) } catch { /* ignore */ }
      }

      map.addSource('babies', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })
      // 高亮用独立 source，永远只含 0 或 1 个 feature
      map.addSource('highlight', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })

      // 图层顺序（底 → 顶）：
      //   1. highlight-ring  外环（最底，不会盖住黑色散点）
      //   2. babies-point    所有黑色散点
      //   3. highlight-core  绿色内芯（最上层，盖住被选中 baby 的黑色散点变成绿色）
      // 这样选中态 = 中心变绿 + 外围脉冲，未选中态 = 只有黑色散点
      map.addLayer({
        id: 'highlight-ring',
        type: 'circle',
        source: 'highlight',
        paint: {
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            1, 10, 4, 14, 8, 20, 16, 28,
          ],
          'circle-color': '#10b981',
          'circle-opacity': 0.25,
          'circle-stroke-width': 0,
        },
      })

      map.addLayer({
        id: 'babies-point',
        type: 'circle',
        source: 'babies',
        paint: {
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            1, 4, 4, 6, 8, 9,
          ],
          'circle-color': '#0b0b0c',
          'circle-opacity': 0.82,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 0.8,
        },
      })

      // 内芯必须加在 babies-point 之后，才能盖住被选中 baby 的黑色圆
      map.addLayer({
        id: 'highlight-core',
        type: 'circle',
        source: 'highlight',
        paint: {
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            1, 4, 4, 6, 8, 9,
          ],
          'circle-color': '#10b981',
          'circle-opacity': 1,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1.2,
        },
      })

      // 脉冲动画：1.6s 周期内 opacity 在 [0, 0.35] 呼吸
      let pulseRaf = 0
      const pulseStart = performance.now()
      const pulseTick = (t) => {
        const phase = ((t - pulseStart) % 1600) / 1600
        // ease-out: 开始亮，中段淡到 0，后段保持 0；模拟 box-shadow 扩散感
        const opacity = phase < 0.7 ? 0.35 * (1 - phase / 0.7) : 0
        if (map.getLayer('highlight-ring')) {
          map.setPaintProperty('highlight-ring', 'circle-opacity', opacity)
        }
        pulseRaf = requestAnimationFrame(pulseTick)
      }
      pulseRaf = requestAnimationFrame(pulseTick)
      pulseRafRef.current = pulseRaf

      map.on('mousemove', 'babies-point', (e) => {
        map.getCanvas().style.cursor = 'pointer'
        const f = e.features?.[0]
        if (!f) return
        showCard(f.geometry.coordinates, f.properties)
      })
      map.on('mouseleave', 'babies-point', () => {
        map.getCanvas().style.cursor = ''
        popup.remove()
      })
      // 点击散点：把它设为当前高亮（绿色脉冲）+ 打开右侧详情卡片 + 轻柔飞到该点
      // 若已有卡片显示其他宝宝 → 先完整滑出旧卡再滑入新卡。
      // 这里 380ms = CSS duration-300 (300ms) + React re-render 到 CSS transition 真实起跑的一帧延迟(~16ms)
      // + 观感留白(~60ms)，确保用户看到"完全滑出 → 短暂空场 → 滑入"三段式，而不是尾部未出就反弹
      map.on('click', 'babies-point', (e) => {
        const f = e.features?.[0]
        if (!f) return
        const [lng, lat] = f.geometry.coordinates
        const p = f.properties
        setHighlightMarker(p.baby_id, lng, lat)
        map.easeTo({ center: [lng, lat], duration: 600 })
        setChatOpen(false)
        const next = { baby_id: p.baby_id, name: p.name, city: p.city, country: p.country, country_code: p.country_code, lng, lat }
        const prev = selectedRef.current
        if (prev && prev.baby_id !== p.baby_id) {
          setSelected(null)
          setTimeout(() => setSelected(next), 380)
        } else {
          setSelected(next)
        }
      })
    }
    map.on('load', onLoad)

    // ── 缓存 → 首页 → 后续分页增量加载 ──────────────────────────
    // 流程：
    //   1. 同步读 localStorage 缓存散点 → 地图就绪后立即 setData（用户不用等网络）
    //   2. 拉一次 /cradle/babies 全量（规模小，用于名字增强）
    //   3. /babies 从 page=1 开始，每 BABIES_PAGE_INTERVAL_MS 拉下一页
    //      每页到来时去重合并进 accumulated，setData 一次（散点逐批浮现）
    //   4. 末页（has_more=false）时：以 freshIds 剪掉缓存里已经消失的陈旧条目，落 localStorage
    //   loadBabies() 在"有可用散点"（缓存命中或首页到达）时即 resolve，供 decideAndFly 尽早决策。
    const applySourceData = (features) => {
      const src = map.getSource('babies')
      if (src) src.setData({ type: 'FeatureCollection', features })
    }

    const accumulated = readBabiesCache()
    babiesFeatures = accumulated
    if (styleLoaded) applySourceData(accumulated)
    else map.once('load', () => applySourceData(accumulated))

    const loadBabies = () => new Promise((resolve) => {
      let resolved = false
      const doResolve = () => {
        if (!resolved) { resolved = true; resolve() }
      }
      // 缓存非空 → 立即释放 decideAndFly；后续页数据只是"补完"
      if (accumulated.length > 0) doResolve()

      let cradleList = []
      const freshIds = new Set()
      let page = 1

      const runPage = async () => {
        if (geoCancelled || ctrl.signal.aborted) { doResolve(); return }
        try {
          const resp = await fetch(
            `${API}/babies?page=${page}&page_size=${BABIES_PAGE_SIZE}`,
            { signal: ctrl.signal },
          ).then(r => r.ok ? r.json() : null).catch(() => null)

          if (!resp) { doResolve(); return }

          const newFeatures = babiesToFeatures(resp.babies || [], cradleList)
          for (const f of newFeatures) {
            freshIds.add(f.properties.baby_id)
            const idx = accumulated.findIndex(x => x.properties.baby_id === f.properties.baby_id)
            if (idx >= 0) accumulated[idx] = f
            else accumulated.push(f)
          }
          babiesFeatures = accumulated
          applySourceData(accumulated)

          // 首页到达即释放等待的 decideAndFly（即便缓存之前是空）
          doResolve()

          const hasMore = !!resp.has_more
          if (hasMore) {
            page += 1
            setTimeout(runPage, BABIES_PAGE_INTERVAL_MS)
          } else {
            // 剪掉缓存里但本次 API 没返回的陈旧散点（baby 被删除的情况）
            for (let i = accumulated.length - 1; i >= 0; i--) {
              if (!freshIds.has(accumulated[i].properties.baby_id)) {
                accumulated.splice(i, 1)
              }
            }
            babiesFeatures = accumulated
            applySourceData(accumulated)
            writeBabiesCache(accumulated)
          }
        } catch {
          // 放弃本次循环，不影响已渲染的散点
          doResolve()
        }
      }

      // cradle 列表小，一次拉全；失败降级为空（name 仅影响展示名，不影响坐标渲染）
      fetchAllPages(`${API}/cradle/babies`, { signal: ctrl.signal })
        .then(list => { cradleList = list || [] })
        .catch(() => { cradleList = [] })
        .finally(() => runPage())

      // 兜底：10s 内没有任何页到达也放过 resolve，不阻塞 decideAndFly
      setTimeout(doResolve, 10000)
    })

    // 并发跑：IP + babies，有可用散点就决策
    Promise.all([resolveIp(), loadBabies()]).then(([ipLoc]) => {
      if (geoCancelled) return
      const run = () => decideAndFly(ipLoc, babiesFeatures || [])
      if (styleLoaded) run()
      else map.once('load', run)
    })

    return () => {
      geoCancelled = true
      try { ctrl.abort() } catch { /* ignore */ }
      ro.disconnect()
      popup.remove()
      if (pulseRafRef.current) {
        cancelAnimationFrame(pulseRafRef.current)
        pulseRafRef.current = 0
      }
      map.remove()
      mapRef.current = null
    }
  }, [])

  // 关闭面板只收起资料卡 + 重置聊天视图；高亮脉冲保留
  const closePanel = () => {
    setSelected(null)
    setChatOpen(false)
  }

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', minHeight: 320 }}>
      <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />

      {/* 右侧详情卡片：从右侧过渡滑入/滑出 */}
      <div
        className={[
          'absolute right-4 top-[72px] w-[300px]',
          'bg-white rounded-2xl shadow-[0_10px_40px_rgba(15,23,42,0.18)]',
          'transition-transform duration-300 ease-out',
          'flex flex-col overflow-hidden z-30',
          'max-h-[calc(100%-88px)]',
          selected ? 'translate-x-0' : 'translate-x-[calc(100%+1rem)] pointer-events-none',
        ].join(' ')}
      >
        {displayed && (
          <>
            <button
              type="button"
              onClick={closePanel}
              className="absolute top-2.5 right-2.5 w-6 h-6 rounded-full bg-black/5 hover:bg-black/10 text-slate-600 flex items-center justify-center transition-colors z-10"
              aria-label={L.close}
            >
              <X className="size-3.5" />
            </button>

            {/* 资料头区：头像 + 名字 + 国家 + id，始终显示 */}
            <div className="px-4 pt-5 pb-3 flex items-center gap-3 shrink-0">
              <img
                src={portraitUrl(displayed.baby_id)}
                alt=""
                onError={(e) => { e.currentTarget.style.visibility = 'hidden' }}
                className="w-12 h-12 rounded-full object-cover bg-slate-100 shadow-sm shrink-0"
              />
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-semibold text-slate-900 leading-tight truncate">
                  {displayed.name}
                </div>
                <div className="text-[12px] text-slate-500 truncate">
                  {(() => {
                    const city = displayCityName(displayed.city, isZh)
                    const country = displayCountryName(displayed.country, displayed.country_code, isZh)
                    if (city) return `${city}${country ? (isZh ? `，${country}` : `, ${country}`) : ''}`
                    return country || L.empty
                  })()}
                </div>
                <div className="text-[10px] text-slate-400 font-mono truncate">{displayed.baby_id}</div>
              </div>
            </div>

            {/* 操作按钮：互动为 toggle，点击原地展开下方对话；关系网跳摇篮 */}
            <div className="px-4 pb-3 pt-1 flex gap-2 shrink-0">
              <button
                type="button"
                onClick={() => setChatOpen((v) => !v)}
                className={[
                  'flex-1 h-7 px-2.5 gap-1.5 text-xs rounded-md font-medium flex items-center justify-center transition-colors',
                  chatOpen
                    ? 'bg-primary text-primary-foreground hover:opacity-90'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200',
                ].join(' ')}
              >
                <MessageCircle className="size-3.5" />
                {chatOpen ? L.collapse : L.interact}
              </button>
              <button
                type="button"
                onClick={() => navigate(`/cradle/${encodeURIComponent(displayed.baby_id)}?view=graph`)}
                className="flex-1 h-7 px-2.5 gap-1.5 text-xs rounded-md bg-slate-100 text-slate-700 font-medium flex items-center justify-center hover:bg-slate-200 transition-colors"
              >
                <Network className="size-3.5" />
                {L.graph}
              </button>
            </div>

            {/* 互动对话区：在资料区下方原地展开，不跳转 */}
            <div
              className={[
                'border-t border-slate-100 overflow-hidden transition-[height] duration-300 ease-out',
                chatOpen ? 'h-[340px]' : 'h-0',
              ].join(' ')}
            >
              {chatOpen && (
                <div className="h-full flex">
                  <ChatPanel
                    babyId={displayed.baby_id}
                    babyStatus={null}
                    touchActions={touchActions}
                    loadTouchActions={loadTouchActions}
                    isZh={isZh}
                    tk={(s) => s}
                  />
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;',
  }[c]))
}
