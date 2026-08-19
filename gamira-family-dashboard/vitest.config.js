import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const projectRoot = path.dirname(fileURLToPath(import.meta.url))

// Mirrors the `@` -> `src` alias in vite.config.js so test files can import
// the same way the app does.
export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(projectRoot, 'src'),
    },
  },
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    // Every test file imports describe/it/expect/vi explicitly from 'vitest'
    // rather than relying on injected globals, so this stays false.
    globals: false,
  },
})
