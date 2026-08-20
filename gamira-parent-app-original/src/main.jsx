import React from 'react'
import ReactDOM from 'react-dom/client'
import { Capacitor } from '@capacitor/core'
import { SplashScreen } from '@capacitor/splash-screen'
import App from '@/App.jsx'
import ErrorBoundary from '@/components/ErrorBoundary.jsx'
import '@/index.css'
import { getStoredTheme, applyTheme } from '@/lib/theme'
import { applyAccessibility } from '@/lib/userSettings'

applyTheme(getStoredTheme())
applyAccessibility()

ReactDOM.createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
)

if (Capacitor.isNativePlatform()) {
  // Two nested rAFs: the first fires before the browser paints this frame's
  // changes, the second after — the earliest point at which the just-mounted
  // app is actually on screen, so the native splash hands off with no gap.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      SplashScreen.hide()
    })
  })
}
