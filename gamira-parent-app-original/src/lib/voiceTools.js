// Which Live tools run in this browser, and which go to the backend.
//
// The server owns the real catalogue: it declares the tools into the ephemeral
// token and stores a snapshot on the session, and it refuses any call whose
// name was not in that snapshot. This file is the *client* half of the same
// division — the small set of tools that do something to this app rather than
// to the record.
//
// Everything here is an allowlist. A name that is not in CLIENT_TOOLS is
// forwarded to the backend, and a name the backend does not know is refused
// there. There is no path by which a spoken sentence reaches an arbitrary
// route, URL or handler.

/**
 * Tools this app executes itself. Navigation and opening things — nothing that
 * changes a record, and nothing that acts without the person.
 *
 * `confirm: true` means the app must ask before doing it, because it either
 * leaves Gamira (the dialer) or opens an emergency flow.
 */
export const CLIENT_TOOLS = {
  navigate_to_screen: { confirm: false },
  open_dose_details: { confirm: false },
  open_reminder_details: { confirm: false },
  // Everyday things that need no record and change nothing.
  get_current_time: { confirm: false },
  get_weather: { confirm: false },
  end_conversation: { confirm: false },
  // Opens the SOS screen and starts a countdown the person can cancel. It
  // still raises nothing outside this app: an in-app alert their family sees,
  // and then the dialer, exactly as pressing the button does.
  prepare_sos: { confirm: true },
  prepare_call_contact: { confirm: true },
};

// The screens a voice command may open, mirroring the server's own list. A
// screen the model names that is not here is an invalid argument, not a guess.
export const SCREEN_ROUTES = {
  home: '/',
  health: '/health',
  reminders: '/reminders',
  family: '/family',
  settings: '/settings',
};

export const isClientTool = (name) =>
  Object.prototype.hasOwnProperty.call(CLIENT_TOOLS, name);

export const clientToolNeedsConfirmation = (name) =>
  Boolean(CLIENT_TOOLS[name]?.confirm);

/** A structured error in the same shape the backend returns. */
export const toolError = (code, message, extra = {}) => ({
  status: 'error',
  error: code,
  message,
  ...extra,
});

export const toolOk = (payload = {}) => ({ status: 'ok', ...payload });

/**
 * Where this device is, or null.
 *
 * Resolves to null rather than rejecting on refusal or timeout: somebody
 * declining location should get "I cannot check the weather", not an error.
 */
function currentPosition(timeoutMs = 8000) {
  if (!navigator.geolocation) return Promise.resolve(null);
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
      () => resolve(null),
      { timeout: timeoutMs, maximumAge: 15 * 60 * 1000 }
    );
  });
}

/**
 * WMO weather codes in words. The same vocabulary the family dashboard uses.
 *
 * Plain descriptions only — nothing here should read as advice about whether
 * it is a good idea to go outside.
 */
function describeWeatherCode(code) {
  if (code === null || code === undefined) return 'unknown';
  if (code === 0) return 'clear';
  if (code <= 2) return 'partly cloudy';
  if (code === 3) return 'cloudy';
  if (code <= 48) return 'foggy';
  if (code <= 57) return 'drizzle';
  if (code <= 67) return 'rain';
  if (code <= 77) return 'snow';
  if (code <= 82) return 'rain showers';
  if (code <= 86) return 'snow showers';
  return 'a thunderstorm';
}

/**
 * @typedef {object} CheckedCall
 * @property {boolean} ok
 * @property {string} id     the model's call id, or '' if it sent none
 * @property {string} name   the tool name, or '' if it sent none
 * @property {object} args   the arguments, empty when the call is unusable
 * @property {string} [reason] why it was rejected
 */

/**
 * Is this a usable function call?
 *
 * Model output, so nothing about it is assumed: a call needs a name, an id to
 * answer against, and arguments that are a plain object.
 *
 * @param {any} call
 * @returns {CheckedCall}
 */
export function validateFunctionCall(call) {
  const id = typeof call?.id === 'string' ? call.id : '';
  const name = typeof call?.name === 'string' ? call.name : '';

  if (!name) return { ok: false, reason: 'missing_name', id, name, args: {} };
  // Without an id there is nothing to send the answer back against, and a
  // response matched to the wrong call is worse than no response at all.
  if (!id) return { ok: false, reason: 'missing_call_id', id, name, args: {} };

  const raw = call.args ?? call.arguments ?? {};
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ok: false, reason: 'invalid_arguments', id, name, args: {} };
  }
  return { ok: true, id, name, args: raw };
}

/**
 * Build the dispatcher the voice session uses for client-only tools.
 *
 * Every handler is named here. The dispatcher takes a tool name and looks it
 * up; it never builds a route, a URL or a function name from what the model
 * said.
 *
 * @param {object} handlers
 * @param {(path: string) => void} handlers.navigate
 * @param {(id: string) => void} [handlers.openDose]
 * @param {(id: string) => void} [handlers.openReminder]
 * @param {() => void} [handlers.openSos]
 * @param {(contactId: string) => {name?: string, phone?: string} | null} [handlers.openDialer]
 * @param {() => void} [handlers.endConversation]  close the session and stop listening
 * @param {string | null} [handlers.timezone]  the cared-for person's timezone
 */
export function createUiDispatcher({
  navigate,
  openDose,
  openReminder,
  openSos,
  openDialer,
  endConversation,
  timezone = null,
}) {
  return async function dispatch(name, args) {
    switch (name) {
      case 'navigate_to_screen': {
        const route = SCREEN_ROUTES[args.screen];
        if (!route) {
          return toolError(
            'invalid_arguments',
            'That is not a screen I can open.',
            { field: 'screen', reason: 'not_in_enum' }
          );
        }
        navigate(route);
        return toolOk({ screen: args.screen, message: `Opened ${args.screen}.` });
      }

      case 'open_dose_details': {
        if (!openDose) return toolError('dependency_unavailable', 'That screen is not open.');
        openDose(args.dose_event_id);
        navigate(SCREEN_ROUTES.reminders);
        return toolOk({ message: 'Showing that dose on screen.' });
      }

      case 'open_reminder_details': {
        if (!openReminder) {
          return toolError('dependency_unavailable', 'That screen is not open.');
        }
        openReminder(args.reminder_id);
        navigate(SCREEN_ROUTES.reminders);
        return toolOk({ message: 'Showing that reminder on screen.' });
      }

      case 'get_current_time': {
        const now = new Date();
        const zone = timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
        const fmt = (options) =>
          new Intl.DateTimeFormat('en-GB', { timeZone: zone, ...options }).format(now);
        return toolOk({
          time: fmt({ hour: 'numeric', minute: '2-digit', hour12: true }),
          weekday: fmt({ weekday: 'long' }),
          date: fmt({ day: 'numeric', month: 'long', year: 'numeric' }),
          iso: now.toISOString(),
          timezone: zone,
        });
      }

      case 'get_weather': {
        const where = await currentPosition();
        if (!where) {
          return toolError(
            'dependency_unavailable',
            'I cannot tell where they are, so I cannot check the weather.'
          );
        }
        try {
          const response = await fetch(
            'https://api.open-meteo.com/v1/forecast' +
              `?latitude=${where.latitude}&longitude=${where.longitude}` +
              '&current=temperature_2m,apparent_temperature,weather_code'
          );
          if (!response.ok) throw new Error(String(response.status));
          const body = await response.json();
          const current = body?.current || {};
          return toolOk({
            temperature_c: current.temperature_2m ?? null,
            feels_like_c: current.apparent_temperature ?? null,
            conditions: describeWeatherCode(current.weather_code),
          });
        } catch {
          return toolError('dependency_unavailable', 'I could not reach the weather service.');
        }
      }

      case 'end_conversation': {
        if (!endConversation) {
          return toolError('dependency_unavailable', 'I cannot close this from here.');
        }
        // Deferred a beat so this response reaches the model — and so the
        // goodbye it already spoke finishes playing — before the socket goes.
        setTimeout(endConversation, 1200);
        return toolOk({ message: 'Saying goodbye and closing the session.' });
      }

      case 'prepare_sos': {
        if (!openSos) {
          return toolError('dependency_unavailable', 'The SOS screen is not available here.');
        }
        openSos();
        // Deliberate wording. The countdown is running, and what it will do is
        // raise an in-app alert — nothing more. Anything vaguer would let the
        // model imply that help is coming.
        return toolOk({
          message:
            'The emergency screen is open and counting down. It will alert their ' +
            'family inside Gamira unless they cancel. Nobody outside the app has ' +
            'been contacted, and no call has been placed.',
        });
      }

      case 'prepare_call_contact': {
        if (!openDialer) {
          return toolError('dependency_unavailable', 'This device cannot place calls.');
        }
        const contact = openDialer(args.contact_id);
        if (!contact) {
          return toolError('not_found', 'I could not find that contact.');
        }
        return toolOk({
          contact_name: contact.name || null,
          message: 'The dialer is open. They still press the call button.',
        });
      }

      default:
        // Unreachable through the session, which checks isClientTool first.
        return toolError('unknown_tool', 'I do not have a tool by that name.');
    }
  };
}
