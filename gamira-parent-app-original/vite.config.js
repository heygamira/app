import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const projectRoot = path.dirname(fileURLToPath(import.meta.url))

// Testing on a real phone needs https: browsers only give a page the
// microphone on a secure origin, and http://192.168.x.x is not one. `run.py`
// generates a self-signed certificate and passes it through these variables;
// without them the dev server stays on plain http, as before.
const certFile = process.env.GAMIRA_TLS_CERT
const keyFile = process.env.GAMIRA_TLS_KEY
const https =
  certFile && keyFile && fs.existsSync(certFile) && fs.existsSync(keyFile)
    ? { cert: fs.readFileSync(certFile), key: fs.readFileSync(keyFile) }
    : undefined

// https://vite.dev/config/
export default defineConfig({
  resolve: {
    // The removed Base44 plugin used to supply this alias.
    alias: {
      '@': path.resolve(projectRoot, 'src'),
    },
  },
  server: {
    port: 5173,
    https,
    proxy: {
      // Keeps the browser on one origin in development.
      //
      // 127.0.0.1 rather than localhost: on a machine where localhost resolves
      // to ::1 first, this proxy cannot reach a uvicorn bound to 127.0.0.1.
      // Set GAMIRA_API_TARGET when the backend runs on another port.
      '/api': {
        target: process.env.GAMIRA_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // The Gemini token server, which stays bound to localhost and holds the
      // API key. Reaching it through here means a phone on the network can
      // start a voice session without the key server being exposed at all,
      // and an https page never has to fetch an http endpoint.
      '/gemini-token': {
        target: process.env.GAMIRA_TOKEN_TARGET || 'http://127.0.0.1:8787',
        changeOrigin: true,
        rewrite: (requestPath) => requestPath.replace(/^\/gemini-token/, ''),
      },
    },
  },
  plugins: [react()],
});
