import * as React from 'react';

// Minimal shadcn-shaped toast store. The project does not depend on
// @radix-ui/react-toast, so the queue lives here and <Toaster /> renders it.
const TOAST_LIMIT = 3;
const TOAST_DURATION = 4000;

let count = 0;
let memoryState = { toasts: [] };
const listeners = new Set();
const timeouts = new Map();

function setState(next) {
  memoryState = next;
  listeners.forEach((listener) => listener(memoryState));
}

export function dismiss(toastId) {
  const timeout = timeouts.get(toastId);
  if (timeout) {
    clearTimeout(timeout);
    timeouts.delete(toastId);
  }
  setState({
    toasts: memoryState.toasts.filter((t) => t.id !== toastId),
  });
}

export function toast({ title, description, variant = 'default', duration = TOAST_DURATION }) {
  count += 1;
  const id = String(count);
  const entry = { id, title, description, variant };

  setState({
    toasts: [entry, ...memoryState.toasts].slice(0, TOAST_LIMIT),
  });

  if (duration > 0) {
    timeouts.set(
      id,
      setTimeout(() => dismiss(id), duration),
    );
  }

  return { id, dismiss: () => dismiss(id) };
}

export function useToast() {
  const [state, setLocalState] = React.useState(memoryState);

  React.useEffect(() => {
    listeners.add(setLocalState);
    return () => {
      listeners.delete(setLocalState);
    };
  }, []);

  return { ...state, toast, dismiss };
}
