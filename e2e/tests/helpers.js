// Shared helpers for the Gamira e2e suite. Kept deliberately small: each
// spec should still read like it is driving a real browser, not hiding
// behind a page-object framework.

// Mirrors playwright.config.js. Not imported from there to keep this module
// usable from a plain `request` fixture without pulling in `defineConfig`.
export const API_BASE_URL = 'http://127.0.0.1:8020';
export const API_PREFIX = '/api/v1';

/**
 * `?dev=<subject>` signs the current tab in as that development identity —
 * only honoured by the app when the Vite dev server is running in dev mode,
 * and only accepted by the backend when it is running with AUTH_MODE=dev.
 * See AuthContext.jsx's `devSubjectFromUrl()` in both frontends.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string} subject - e.g. "sharma-owner" or a freshly generated one.
 * @param {{ path?: string }} [options] - path (with optional query string)
 *   to sign in from, relative to the project's baseURL. Defaults to "/".
 */
export async function signInAs(page, subject, { path = '/' } = {}) {
  const separator = path.includes('?') ? '&' : '?';
  await page.goto(`${path}${separator}dev=${encodeURIComponent(subject)}`);
  await waitForAuthResolved(page);
}

/**
 * Waits out `ProtectedRoute`'s own loading spinner (`isLoadingAuth ||
 * !authChecked`), which is the one thing every screen behind it — signed out,
 * onboarding, fully set up — has in common right after a fresh sign-in. Each
 * spec then asserts on whatever that particular identity actually lands on.
 *
 * Resolves immediately if the spinner was never on the page at all (a fast
 * local backend can beat the first paint), and waits for it to be removed if
 * it was — never a fixed sleep either way.
 *
 * @param {import('@playwright/test').Page} page
 */
export async function waitForAuthResolved(page) {
  await page
    .locator('div.border-t-primary.animate-spin')
    .first()
    .waitFor({ state: 'detached', timeout: 30_000 });
}

/**
 * A subject string no seed data and no earlier test run could have used,
 * for scenarios that need a genuinely never-seen identity (onboarding,
 * invite-accept). `AUTH_MODE=dev` auto-provisions a `User` row for whatever
 * subject shows up first, so nothing needs to pre-create this.
 *
 * @param {string} label - short, readable tag for whoever reads a failure.
 */
export function freshSubject(label) {
  return `e2e-${label}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Calls the backend directly with a dev bearer token, bypassing the browser
 * entirely. Used for setup that the UI can drive but that would make a test
 * about invitation-acceptance also a test of, say, the "add a family member"
 * form — two different things worth failing separately.
 *
 * @param {import('@playwright/test').APIRequestContext} request
 * @param {string} subject - signs the request in as `dev:<subject>`.
 * @param {string} method
 * @param {string} path - starting with "/", relative to /api/v1.
 * @param {object} [body]
 */
export async function apiAs(request, subject, method, path, body) {
  const response = await request.fetch(`${API_BASE_URL}${API_PREFIX}${path}`, {
    method,
    headers: { Authorization: `Bearer dev:${subject}` },
    data: body,
  });
  if (!response.ok()) {
    const text = await response.text().catch(() => '');
    throw new Error(
      `${method} ${path} as dev:${subject} failed: ${response.status()} ${text}`,
    );
  }
  return response.status() === 204 ? null : response.json();
}
