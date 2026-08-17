// Loading the wake-word bundle that `python main.py export-web` produced.
//
// The model is deliberately not part of the JavaScript build. It is still being
// retrained, and every retrain has to be able to reach the app by copying files
// — not by a rebuild and a redeploy. So:
//
//   public/wake/manifest.json          re-read every time, never cached
//   public/wake/<version>/...          immutable, cached normally
//
// `python main.py export-web --out .../public/wake` rewrites the manifest to
// point at the new version directory. Reload the page and the new model is live.
//
// When this eventually moves behind an API, only BUNDLE_ROOT changes.

import { describeSpecMismatch } from './frontend.js';

export const BUNDLE_ROOT = '/wake';

/** Bundle layouts this build understands. Refuse anything newer. */
const SUPPORTED_BUNDLE_VERSION = 1;

async function fetchJson(url, init) {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

async function fetchFloat32(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return new Float32Array(await response.arrayBuffer());
}

/**
 * Read the manifest and everything the front end needs.
 *
 * Throws with a specific reason rather than returning something half-usable: a
 * model run on features it was not trained on does not fail, it just scores
 * near zero on everything forever, and that is much harder to notice than an
 * error at startup.
 *
 * @param {string} [root]
 * @returns {Promise<{manifest: object, spec: object, filterbank: Float32Array,
 *   window: Float32Array, modelUrl: string}>}
 */
export async function loadWakeBundle(root = BUNDLE_ROOT) {
  // Always revalidated: this is the file that says which model is current.
  const manifest = await fetchJson(`${root}/manifest.json`, { cache: 'no-store' });

  if (manifest.bundle_version > SUPPORTED_BUNDLE_VERSION) {
    throw new Error(
      `wake bundle v${manifest.bundle_version} is newer than this app understands ` +
        `(v${SUPPORTED_BUNDLE_VERSION}); rebuild the app`
    );
  }

  const [spec, filterbank, window] = await Promise.all([
    fetchJson(`${root}/${manifest.frontend}`),
    fetchFloat32(`${root}/${manifest.filterbank}`),
    fetchFloat32(`${root}/${manifest.window}`),
  ]);

  const problem = describeSpecMismatch(spec);
  if (problem) throw new Error(`wake bundle ${manifest.version} is unusable: ${problem}`);

  return { manifest, spec, filterbank, window, modelUrl: `${root}/${manifest.model}` };
}
