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
 */

/**
 * @param {string} path
 * @param {RequestOptions} [options]
 * @returns {Promise<any>}
 */
async function request(path, { method = 'GET', body, idempotencyKey, signal } = {}) {
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
   * @param {{seniorId?: string}} [options]
   */
  createLiveSession: ({ seniorId } = {}) =>
    request('/ai/live-sessions', {
      method: 'POST',
      body: seniorId ? { senior_id: seniorId } : {},
    }),

  closeLiveSession: (sessionId) =>
    request(`/ai/live-sessions/${sessionId}/close`, { method: 'POST' }),

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
  notifications,
  sos,
  alerts,
  emergencyContacts,
  appointments,
  devices,
  ai,
};

export default gamira;
