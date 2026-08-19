import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const projectRoot = path.dirname(fileURLToPath(import.meta.url))

// Mirrors the `@` -> `src` alias in vite.config.js. The dev-server https/proxy
// block and the onnxruntime-web `optimizeDeps.exclude` there are both
// Vite-dev-server concerns that vitest never goes through, so they are not
// reproduced here. `@vitejs/plugin-react` is kept, same as vite.config.js,
// so .jsx test files get the automatic JSX runtime instead of needing `React`
// in scope.
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
    globals: false,
  },
})
