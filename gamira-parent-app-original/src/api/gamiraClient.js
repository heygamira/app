// The single HTTP client for the Gamira backend.
//
// Every screen goes through this module. Pages must not call fetch directly:
// authentication, the error shape and the family/senior context all live here.

const API_BASE = import.meta.env.VITE_GAMIRA_API_URL || '/api/v1';
const TOKEN_KEY = 'gamira_access_token';

export class ApiError extends Error {
  constructor({ status, code, message, details = {}, requestId = '' }) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details || {};
    this.requestId = requestId || '';
  }

  get isAuthError() {
    return this.status === 401 || this.status === 403;
  }
}

const storage = {
  get() {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token) {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* private browsing */
    }
  },
};

/**
 * @typedef {object} RequestOptions
 * @property {string} [method]
 * @property {unknown} [body]
 * @property {string} [idempotencyKey]
 * @property {AbortSignal} [signal]
 * @property {boolean} [keepalive] let the request outlive the page that sent it
 */

/**
 * @param {string} path
 * @param {RequestOptions} [options]
 * @returns {Promise<any>}
 */
async function request(
  path,
  { method = 'GET', body, idempotencyKey, signal, keepalive = false } = {},
) {
  const token = storage.get();
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      signal,
      // `keepalive` lets a request outlive the page that started it, which is
      // the only way a request sent while closing a tab actually goes out.
      keepalive,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    // A network failure is not the same as a rejected request, and screens
    // need to be able to offer a retry rather than a sign-in prompt.
    throw new ApiError({
      status: 0,
      code: 'network_unavailable',
      message: 'Could not reach Gamira. Check your connection and try again.',
      details: { cause: String(cause) },
    });
  }

  if (response.status === 204) return null;

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = payload?.error || {};
    throw new ApiError({
      status: response.status,
      code: error.code || 'request_failed',
      message: error.message || `Request failed (${response.status})`,
      details: error.details,
      requestId: error.request_id || response.headers.get('X-Request-Id'),
    });
  }
  return payload;
}

// --------------------------------------------------------------------------
// Session
// --------------------------------------------------------------------------

export const auth = {
  getToken: () => storage.get(),
  setToken: (token) => storage.set(token),
  clearToken: () => storage.set(null),
  isAuthenticated: () => Boolean(storage.get()),

  // Local development only. AUTH_MODE=dev on the backend accepts these; with
  // AUTH_MODE=firebase they are rejected, so nothing here weakens production.
  signInWithDevToken(subject, email, name) {
    const parts = ['dev', subject, email || '', name || ''].filter(
      (part, index) => index < 2 || part
    );
    storage.set(parts.join(':'));
    return auth.me();
  },

  me: () => request('/me'),
  updateMe: (patch) => request('/me', { method: 'PATCH', body: patch }),
  logout() {
    storage.set(null);
  },
};

// --------------------------------------------------------------------------
// Resources
// --------------------------------------------------------------------------

export const families = {
  create: (name) => request('/families', { method: 'POST', body: { name } }),
  get: (familyId) => request(`/families/${familyId}`),
  update: (familyId, patch) =>
    request(`/families/${familyId}`, { method: 'PATCH', body: patch }),
  members: (familyId) => request(`/families/${familyId}/members`),
  invite: (familyId, body) =>
    request(`/families/${familyId}/invitations`, { method: 'POST', body }),
  acceptInvitation: (token) =>
    request(`/invitations/${encodeURIComponent(token)}/accept`, { method: 'POST' }),
  removeMember: (familyId, membershipId) =>
    request(`/families/${familyId}/members/${membershipId}`, { method: 'DELETE' }),
  notes: (familyId, seniorId) =>
    request(`/families/${familyId}/notes${seniorId ? `?senior_id=${seniorId}` : ''}`),
  createNote: (familyId, body) =>
    request(`/families/${familyId}/notes`, { method: 'POST', body }),
};

export const seniors = {
  list: (familyId) => request(`/families/${familyId}/seniors`),
  create: (familyId, body) =>
    request(`/families/${familyId}/seniors`, { method: 'POST', body }),
  get: (seniorId) => request(`/seniors/${seniorId}`),
  update: (seniorId, patch) =>
    request(`/seniors/${seniorId}`, { method: 'PATCH', body: patch }),
  archive: (seniorId) => request(`/seniors/${seniorId}`, { method: 'DELETE' }),
  /**
   * Today's doses, active reminders, emergency contacts and pending
   * wellbeing checks, in one request. What VoiceContext polls instead of
   * the four endpoints above separately.
   */
  summary: (seniorId) => request(`/seniors/${seniorId}/summary`),
};

export const medications = {
  list: (seniorId) => request(`/seniors/${seniorId}/medications`),
  create: (seniorId, body) =>
    request(`/seniors/${seniorId}/medications`, { method: 'POST', body }),
  get: (medicationId) => request(`/medications/${medicationId}`),
  update: (medicationId, patch) =>
    request(`/medications/${medicationId}`, { method: 'PATCH', body: patch }),
  archive: (medicationId) =>
    request(`/medications/${medicationId}/archive`, { method: 'POST' }),
  addSchedule: (medicationId, body) =>
    request(`/medications/${medicationId}/schedules`, { method: 'POST', body }),
  updateSchedule: (scheduleId, patch) =>
    request(`/medication-schedules/${scheduleId}`, { method: 'PATCH', body: patch }),
  deleteSchedule: (scheduleId) =>
    request(`/medication-schedules/${scheduleId}`, { method: 'DELETE' }),
};

export const doses = {
  /**
   * @param {string} seniorId
   * @param {{from?: string, to?: string}} [range]
   */
  list: (seniorId, { from, to } = {}) => {
    const query = new URLSearchParams();
    if (from) query.set('from', from);
    if (to) query.set('to', to);
    const suffix = query.toString() ? `?${query}` : '';
    return request(`/seniors/${seniorId}/doses${suffix}`);
  },
  // The idempotency key means a double tap, an offline replay or a retried
  // request all resolve to the same dose instead of recording it twice.
  markTaken: (doseEventId, body = {}) =>
    request(`/dose-events/${doseEventId}/taken`, {
      method: 'POST',
      body: { source: 'parent_app', ...body },
      idempotencyKey: `taken:${doseEventId}`,
    }),
  markSkipped: (doseEventId, body = {}) =>
    request(`/dose-events/${doseEventId}/skipped`, {
      method: 'POST',
      body: { source: 'parent_app', ...body },
      idempotencyKey: `skipped:${doseEventId}`,
    }),
};

export const reminders = {
  list: (seniorId) => request(`/seniors/${seniorId}/reminders`),
  create: (seniorId, body) =>
    request(`/seniors/${seniorId}/reminders`, { method: 'POST', body }),
  update: (reminderId, patch) =>
    request(`/reminders/${reminderId}`, { method: 'PATCH', body: patch }),
  remove: (reminderId) => request(`/reminders/${reminderId}`, { method: 'DELETE' }),
};

export const timeline = {
  /**
   * @param {string} seniorId
   * @param {{limit?: number, before?: string}} [options]
   */
  list: (seniorId, { limit = 50, before } = {}) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (before) query.set('before', before);
    return request(`/seniors/${seniorId}/timeline?${query}`);
  },
};

export const healthReadings = {
  /**
   * @param {string} seniorId
   * @param {{metric?: string, limit?: number}} [options]
   */
  list: (seniorId, { metric, limit = 100 } = {}) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (metric) query.set('metric', metric);
    return request(`/seniors/${seniorId}/health-readings?${query}`);
  },
  create: (seniorId, body) =>
    request(`/seniors/${seniorId}/health-readings`, { method: 'POST', body }),
  /**
   * Several readings in one request — a flushed batch from a paired watch,
   * not one round trip per metric per tick.
   *
   * @param {string} seniorId
   * @param {object[]} readings
   */
  createBulk: (seniorId, readings) =>
    request(`/seniors/${seniorId}/health-readings/bulk`, {
      method: 'POST',
      body: { readings },
    }),
};

export const deviceFlags = {
  /**
   * A paired device (today: the watch relay) reporting that a reading left a
   * band it configured — not an SOS, and not Gamira's own judgement.
   *
   * @param {string} seniorId
   * @param {object} body
   */
  raise: (seniorId, body) =>
    request(`/seniors/${seniorId}/device-flags`, { method: 'POST', body }),
};

export const notifications = {
  list: ({ unreadOnly = false, limit = 50 } = {}) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (unreadOnly) query.set('unread_only', 'true');
    return request(`/notifications?${query}`);
  },
  markOpened: (notificationId) =>
    request(`/notifications/${notificationId}/opened`, { method: 'POST' }),
};

export const sos = {
  /**
   * Raise an emergency alert.
   *
   * This records the press and shows it to every other member of the family
   * inside Gamira. It does not call anyone, message anyone or contact
   * emergency services — the screen that uses this must say so, and must still
   * offer the phone call.
   *
   * @param {string} seniorId
   * @param {{source?: 'parent_app'|'watch', note?: string}} [body]
   */
  raise: (seniorId, body = {}) =>
    request(`/seniors/${seniorId}/sos`, {
      method: 'POST',
      body: { source: 'parent_app', ...body },
    }),
};

export const emergencyContacts = {
  list: (seniorId) => request(`/seniors/${seniorId}/emergency-contacts`),
  create: (seniorId, body) =>
    request(`/seniors/${seniorId}/emergency-contacts`, { method: 'POST', body }),
  update: (contactId, patch) =>
    request(`/emergency-contacts/${contactId}`, { method: 'PATCH', body: patch }),
  remove: (contactId) =>
    request(`/emergency-contacts/${contactId}`, { method: 'DELETE' }),
};

export const appointments = {
  list: (seniorId) => request(`/seniors/${seniorId}/appointments`),
  create: (seniorId, body) =>
    request(`/seniors/${seniorId}/appointments`, { method: 'POST', body }),
  update: (appointmentId, patch) =>
    request(`/appointments/${appointmentId}`, { method: 'PATCH', body: patch }),
};

export const alerts = {
  get: (alertId) => request(`/alerts/${alertId}`),
  events: (alertId) => request(`/alerts/${alertId}/events`),
  list: (seniorId, { openOnly = false } = {}) =>
    request(`/seniors/${seniorId}/alerts${openOnly ? '?open_only=true' : ''}`),
  acknowledge: (alertId, note) =>
    request(`/alerts/${alertId}/acknowledge`, { method: 'POST', body: { note } }),
  resolve: (alertId, resolution) =>
    request(`/alerts/${alertId}/resolve`, { method: 'POST', body: { resolution } }),
  /**
   * Withdraw an alert that should not have been raised.
   *
   * A reason is required by the backend and is not optional here either: an
   * alert that vanishes with no explanation is worse for the family than the
   * false alarm was. The cared-for person may cancel their own; anybody else
   * needs write access.
   */
  cancel: (alertId, reason) =>
    request(`/alerts/${alertId}/cancel`, { method: 'POST', body: { reason } }),
};

/**
 * Questions Gamira owes this person because a device flagged one of their
 * readings.
 *
 * The watch draws its own lines and says so; nothing here is a clinical
 * judgement by Gamira or by the backend, and the wording on screen has to keep
 * saying whose judgement it is.
 */
export const wellbeingChecks = {
  list: (seniorId, { pendingOnly = true } = {}) =>
    request(
      `/seniors/${seniorId}/wellbeing-checks?pending_only=${pendingOnly ? 'true' : 'false'}`
    ),
  /** Answer by tapping, for anybody who cannot or would rather not speak. */
  answer: (checkId, alright) =>
    request(`/wellbeing-checks/${checkId}/answer`, {
      method: 'POST',
      body: { alright },
    }),
};

export const devices = {
  list: () => request('/devices'),
  register: (body) => request('/devices', { method: 'POST', body }),
  revoke: (deviceId) => request(`/devices/${deviceId}`, { method: 'DELETE' }),
};

/**
 * The AI layer.
 *
 * Voice used to be minted by a separate local server that authenticated nobody.
 * It now comes through here, with the normal bearer token, and the backend
 * decides the model, the system instruction, the tool catalogue and which
 * person the session is about. The browser only obeys what it is handed.
 */
export const ai = {
  /**
   * Start an authenticated Live voice session.
   *
   * Returns `{ session_id, token, model, api_version, expires_at,
   * connect_before, senior_id, senior_name, tools }`. The token is a one-use
   * ephemeral credential; the permanent Gemini key never reaches this app.
   *
   * @param {{seniorId?: string, provisional?: boolean}} [options]
   */
  createLiveSession: ({ seniorId, provisional = false } = {}) =>
    request('/ai/live-sessions', {
      method: 'POST',
      body: {
        ...(seniorId ? { senior_id: seniorId } : {}),
        ...(provisional ? { provisional: true } : {}),
      },
    }),

  /**
   * Turn a speculative session into a real one.
   *
   * The wake word opens a session as soon as the score says "probably" so the
   * connection is ready if it turns out to be one; this is called once it is
   * confirmed. Until then the session costs no hourly quota and expires on its
   * own. No new token is issued — the browser already connected with the one it
   * has.
   */
  promoteLiveSession: (sessionId) =>
    request(`/ai/live-sessions/${sessionId}/promote`, { method: 'POST' }),

  /**
   * Keep what was said in a voice conversation.
   *
   * Batched by the caller, so this is a request every few seconds rather than
   * one per fragment. `final` marks the flush that happens as the session ends,
   * which needs `keepalive` for the same reason the close does — a request
   * started while a page is going away is otherwise cancelled.
   *
   * @param {string} sessionId
   * @param {Array<{role: string, text: string}>} turns
   * @param {{final?: boolean}} [options]
   */
  storeTranscript: (sessionId, turns, { final = false } = {}) =>
    request(`/ai/live-sessions/${sessionId}/transcript`, {
      method: 'POST',
      body: { turns },
      keepalive: final,
    }),

  /**
   * Release a session's slot. Idempotent, and safe to fire while unloading.
   *
   * `keepalive` matters here: only two sessions may be open at once, and a
   * close that is cancelled because the tab went away leaves one of those two
   * slots held for the full half hour — which locks the microphone out of the
   * next visit.
   */
  closeLiveSession: (sessionId) =>
    request(`/ai/live-sessions/${sessionId}/close`, {
      method: 'POST',
      keepalive: true,
    }),

  /**
   * Forward one Live message's function calls for the backend to run.
   *
   * Several calls may arrive in one message, so this takes an array and
   * returns one result per call, each carrying its own id and name back.
   *
   * @param {string} sessionId
   * @param {Array<{id: string, name: string, arguments: object}>} calls
   */
  sendToolCalls: (sessionId, calls) =>
    request(`/ai/live-sessions/${sessionId}/tool-calls`, {
      method: 'POST',
      body: { calls },
    }),

  // A person approved the exact action they were shown. The backend re-checks
  // permission and then runs it; nothing was changed before this.
  confirmAction: (decisionId) =>
    request(`/ai/actions/${decisionId}/confirm`, { method: 'POST' }),
  rejectAction: (decisionId) =>
    request(`/ai/actions/${decisionId}/reject`, { method: 'POST' }),
  getAction: (decisionId) => request(`/ai/actions/${decisionId}`),

  /**
   * What Gamira remembers about this person.
   *
   * Shown to them on their own device, because a companion that keeps notes
   * about somebody they cannot read is a different and worse thing. There is
   * no create: memories are Gamira's, and anything a person wrote themselves
   * is a note with an author.
   */
  listMemories: (seniorId) => request(`/ai/seniors/${seniorId}/memories`),

  /**
   * What Gamira has told this person's family about them.
   *
   * She says it to them first — the backend refuses to send anything she did
   * not mention out loud — and this is how "openly" survives the conversation
   * ending. One row per notice, however many people it reached.
   */
  listFamilyNotices: (seniorId) =>
    request(`/ai/seniors/${seniorId}/family-notices`),
  forgetMemory: (memoryId) =>
    request(`/ai/memories/${memoryId}`, { method: 'DELETE' }),

  requestSummary: (seniorId, range = {}) =>
    request('/ai/summaries', {
      method: 'POST',
      body: { senior_id: seniorId, ...range },
    }),
  getSummary: (summaryId) => request(`/ai/summaries/${summaryId}`),
  listSummaries: (seniorId) => request(`/ai/seniors/${seniorId}/summaries`),
  getJob: (jobId) => request(`/ai/jobs/${jobId}`),
  chat: (seniorId, message, conversationId) =>
    request('/ai/chat', {
      method: 'POST',
      body: { senior_id: seniorId, message, conversation_id: conversationId },
    }),
};

export const gamira = {
  request,
  auth,
  families,
  seniors,
  medications,
  doses,
  reminders,
  timeline,
  healthReadings,
  deviceFlags,
  notifications,
  sos,
  alerts,
  wellbeingChecks,
  emergencyContacts,
  appointments,
  devices,
  ai,
};

export default gamira;
