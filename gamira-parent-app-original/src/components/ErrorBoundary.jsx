import React from 'react';

/**
 * Keeps a crash from emptying the screen.
 *
 * Without this, a single render error anywhere unmounts the whole tree and
 * leaves a blank page — no schedule, no status, and no SOS button. For an app
 * whose entire reason to exist is being reachable in a hurry by someone who is
 * not going to open a console, a blank screen is the worst possible failure.
 *
 * What it deliberately does not do is pretend to recover. It says something
 * went wrong, in plain words and at the size the rest of the app uses, and
 * offers the one action that reliably helps.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('Gamira crashed while drawing the screen', error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="mx-auto flex min-h-[100dvh] w-full max-w-md flex-col items-center justify-center gap-6 bg-background px-6 text-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            Something went wrong
          </h1>
          <p className="mt-2 text-[17px] leading-snug text-muted-foreground">
            Gamira could not show this screen. Your medicines and reminders are safe
            — nothing has been changed.
          </p>
        </div>

        <button
          type="button"
          onClick={() => window.location.reload()}
          className="h-14 w-full rounded-2xl bg-primary text-lg font-semibold text-primary-foreground transition active:scale-95"
        >
          Try again
        </button>

        <p className="text-[15px] text-muted-foreground">
          If this keeps happening, ask your family to check the app.
        </p>

        {import.meta.env.DEV && (
          <pre className="max-h-48 w-full overflow-auto rounded-xl bg-card p-3 text-left text-[11px] leading-tight text-muted-foreground">
            {this.state.error?.stack || String(this.state.error)}
          </pre>
        )}
      </div>
    );
  }
}
