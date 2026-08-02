import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// theme.css must load before index.css — it declares the design tokens that
// every rule in index.css resolves against (docs/webapp/DESIGN-SYSTEM.md).
import './theme.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
