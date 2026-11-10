import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { reloadOnStaleChunks } from './lib/staleChunks'
import { Root } from './Root.tsx'
import './index.css'

reloadOnStaleChunks()

const root = document.getElementById('root')
if (!root) throw new Error('#root 없음')

createRoot(root).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
