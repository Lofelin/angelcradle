import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import './i18n'
import App from './App.jsx'
import SampleGraphPreview from './components/SampleGraphPreview.jsx'

// 调试入口:
//   ?sample=womb   → 孕育图样本（add-womb-conception-graph）
//   ?sample=cradle → 摇篮图样本（add-cradle-growth-graph 批次 1 落地的 138/194 sample）
const _sample = new URLSearchParams(window.location.search).get('sample')
const isSamplePreview = _sample === 'womb' || _sample === 'cradle'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {isSamplePreview ? (
      <SampleGraphPreview kind={_sample} />
    ) : (
      <BrowserRouter>
        <App />
      </BrowserRouter>
    )}
  </StrictMode>,
)
