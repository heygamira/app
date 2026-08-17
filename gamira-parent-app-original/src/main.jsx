import React from 'react'
import ReactDOM from 'react-dom/client'
import App from '@/App.jsx'
import '@/index.css'
import { getStoredTheme, applyTheme } from '@/lib/theme'
import { applyAccessibility } from '@/lib/userSettings'

applyTheme(getStoredTheme())
applyAccessibility()

ReactDOM.createRoot(document.getElementById('root')).render(
  <App />
)
