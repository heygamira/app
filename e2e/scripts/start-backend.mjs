#!/usr/bin/env node
// Brings up a disposable Gamira backend for the Playwright suite: migrate,
// seed, then exec uvicorn in the foreground so Playwright's `webServer`
// health check only ever needs to poll GET /health.
//
// Runnable two ways:
//   - as a Playwright `webServer.command` (env vars come from playwright.config.js)
//   - standalone: `node e2e/scripts/start-backend.mjs` (sane defaults below)
//
// Deliberately three sequential steps rather than one shell one-liner: each
// step's failure needs to be attributable (did seeding fail, or did the
// server itself fail to import?) and `&&` chains behave differently across
// PowerShell, cmd.exe and POSIX shells — spawning each step from Node sidesteps
// that entirely.

import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const e2eDir = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(e2eDir, '..');
const backendDir = path.join(repoRoot, 'gamira-backend');
const dataDir = path.join(e2eDir, '.data');

if (!existsSync(backendDir)) {
  console.error(`[start-backend] gamira-backend not found at ${backendDir}`);
  process.exit(1);
}

mkdirSync(dataDir, { recursive: true });

// Forward-slashed even on Windows: SQLAlchemy's sqlite URL expects
// `sqlite+aiosqlite:///C:/absolute/path/to.db` (three slashes, then the
// absolute path), not a backslash-laden Windows path.
const dbFile = path.join(dataDir, 'gamira_e2e.db').split(path.sep).join('/');
const defaultDatabaseUrl = `sqlite+aiosqlite:///${dbFile}`;

const port = process.env.E2E_API_PORT || '8020';
const host = '127.0.0.1';

const env = {
  ...process.env,
  APP_ENV: process.env.APP_ENV || 'test',
  AUTH_MODE: process.env.AUTH_MODE || 'dev',
  FCM_PROVIDER: process.env.FCM_PROVIDER || 'fake',
  DATABASE_URL: process.env.DATABASE_URL || defaultDatabaseUrl,
};

// Prefer the backend's own virtualenv (`gamira-backend/.venv`) so this never
// depends on whatever happens to be first on PATH. Falls back to a bare
// `python` for an environment where deps were installed globally instead.
const venvPython =
  process.platform === 'win32'
    ? path.join(backendDir, '.venv', 'Scripts', 'python.exe')
    : path.join(backendDir, '.venv', 'bin', 'python');
const pythonExe = existsSync(venvPython) ? venvPython : 'python';

console.log(`[start-backend] python: ${pythonExe}`);
console.log(`[start-backend] database: ${env.DATABASE_URL}`);
console.log(`[start-backend] cwd: ${backendDir}`);

function runStep(label, args) {
  console.log(`[start-backend] ${label}: ${pythonExe} ${args.join(' ')}`);
  const result = spawnSync(pythonExe, args, {
    cwd: backendDir,
    env,
    stdio: 'inherit',
  });
  if (result.error) {
    console.error(`[start-backend] ${label} failed to start: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) {
    console.error(`[start-backend] ${label} exited with code ${result.status}`);
    process.exit(result.status ?? 1);
  }
}

// 1. Migrate.
runStep('alembic upgrade head', ['-m', 'alembic', 'upgrade', 'head']);

// 2. Seed. `--reset` so re-running this suite (or a previous crashed run)
// against the same on-disk .data/gamira_e2e.db always starts from the exact
// same fixture data instead of accumulating leftovers between runs.
runStep('seed', ['-m', 'app.db.seed', '--reset']);

// 3. Serve, in the foreground, as this process's child — so Playwright
// tearing down the process it spawned (this script) takes uvicorn down with
// it rather than leaking an orphaned server bound to :8020.
console.log(`[start-backend] starting uvicorn on ${host}:${port}`);
const server = spawn(
  pythonExe,
  ['-m', 'uvicorn', 'app.main:app', '--host', host, '--port', port],
  { cwd: backendDir, env, stdio: 'inherit' },
);

server.on('exit', (code) => {
  process.exit(code ?? 0);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    server.kill(signal);
  });
}
