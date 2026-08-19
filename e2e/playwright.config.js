// @ts-check
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

const e2eDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(e2eDir, '..');

const API_PORT = 8020;
const API_BASE_URL = `http://127.0.0.1:${API_PORT}`;
const DASHBOARD_URL = 'http://localhost:5174';
const PARENT_APP_URL = 'http://localhost:5173';

// Reused by every webServer entry below so all three processes agree on
// which disposable backend they are talking about.
const commonServerEnv = {
  GAMIRA_API_TARGET: API_BASE_URL,
};

export default defineConfig({
  testDir: path.join(e2eDir, 'tests'),
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // One worker: all three webServer processes share one disposable SQLite
  // file, and several specs mutate global-ish state (family membership,
  // invitations). Nothing here is designed to be safe under concurrent runs
  // against the same backend.
  workers: 1,
  reporter: [['html', { open: 'never' }]],
  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'family-dashboard',
      testMatch: ['family-switch.spec.js', 'invite-accept.spec.js', 'onboarding.spec.js'],
      use: {
        ...devices['Desktop Chrome'],
        baseURL: DASHBOARD_URL,
      },
    },
    {
      name: 'parent-app',
      testMatch: ['senior-link.spec.js'],
      use: {
        ...devices['Desktop Chrome'],
        baseURL: PARENT_APP_URL,
        // The parent app's voice layer asks for the microphone on some
        // paths; granting it up front means a headless run never sits on an
        // OS permission prompt it cannot answer.
        permissions: ['microphone'],
      },
    },
  ],

  webServer: [
    {
      // Runs migrate, seed, then execs uvicorn — see the script for why this
      // is Node rather than a shell one-liner. Playwright only ever polls
      // GET /health, which uvicorn does not answer until both prior steps
      // have already succeeded.
      command: `node "${path.join(e2eDir, 'scripts', 'start-backend.mjs')}"`,
      cwd: e2eDir,
      url: `${API_BASE_URL}/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: {
        AUTH_MODE: 'dev',
        APP_ENV: 'test',
        FCM_PROVIDER: 'fake',
        DATABASE_URL: `sqlite+aiosqlite:///${path
          .join(e2eDir, '.data', 'gamira_e2e.db')
          .split(path.sep)
          .join('/')}`,
        E2E_API_PORT: String(API_PORT),
      },
    },
    {
      // The real Vite dev server, not `vite preview` — the `?dev=<subject>`
      // sign-in bypass only works when `import.meta.env.DEV` is true.
      command: 'npm run dev',
      cwd: path.join(repoRoot, 'gamira-family-dashboard'),
      url: DASHBOARD_URL,
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
      env: commonServerEnv,
    },
    {
      command: 'npm run dev',
      cwd: path.join(repoRoot, 'gamira-parent-app-original'),
      url: PARENT_APP_URL,
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
      env: commonServerEnv,
    },
  ],
});
