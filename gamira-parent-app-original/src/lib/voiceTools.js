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
  // Opens the real SOS confirmation. It does not raise anything: the person
  // presses the red button themselves, exactly as they would without voice.
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
 */
export function createUiDispatcher({
  navigate,
  openDose,
  openReminder,
  openSos,
  openDialer,
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

      case 'prepare_sos': {
        if (!openSos) {
          return toolError('dependency_unavailable', 'The SOS screen is not available here.');
        }
        openSos();
        // Deliberate wording: the screen is open, and that is all. Saying
        // anything else would let the model imply help is coming.
        return toolOk({
          message:
            'The emergency screen is open. They still have to press it themselves — ' +
            'Gamira has not contacted anyone.',
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
