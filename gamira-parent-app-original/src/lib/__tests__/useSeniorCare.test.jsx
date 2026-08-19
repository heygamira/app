import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { useSeniorCare } from '@/lib/useSeniorCare';
import { doses as dosesApi } from '@/api/gamiraClient';

// useSeniorCare is the one hook every live-data screen goes through
// (AGENTS.md), so its loading/empty/error transitions matter more than any
// one screen's markup. `self` never changes across these tests: only how the
// dose list resolves does.
vi.mock('@/lib/AuthContext', () => ({
  useAuth: () => ({ self: { id: 'senior-1', name: 'Priya', timezone: 'UTC' } }),
}));

vi.mock('@/api/gamiraClient', () => ({
  doses: { list: vi.fn() },
  reminders: { list: vi.fn() },
  healthReadings: { list: vi.fn() },
  emergencyContacts: { list: vi.fn() },
}));

// A minimal stand-in for a real screen (Reminders.jsx does the same three-way
// branch): render whatever the hook actually says, so a broken transition
// shows up as visible, wrong text instead of passing silently.
function DosesHarness() {
  const { loading, error, doses } = useSeniorCare({ doses: true });
  if (loading) return <p>Loading care data…</p>;
  if (error) return <p role="alert">{error}</p>;
  if (doses.length === 0) return <p>Nothing is waiting right now.</p>;
  return (
    <ul>
      {doses.map((dose) => (
        <li key={dose.id}>{dose.medication_name}</li>
      ))}
    </ul>
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('useSeniorCare loading/content/error states', () => {
  it('shows a loading indicator while the request is pending', () => {
    dosesApi.list.mockReturnValue(new Promise(() => {})); // never resolves

    render(<DosesHarness />);

    expect(screen.getByText('Loading care data…')).toBeInTheDocument();
  });

  it('renders the real doses once the request resolves', async () => {
    dosesApi.list.mockResolvedValue([
      { id: 'dose-1', medication_name: 'Lisinopril', status: 'due' },
    ]);

    render(<DosesHarness />);

    await waitFor(() => expect(screen.getByText('Lisinopril')).toBeInTheDocument());
    expect(screen.queryByText('Loading care data…')).not.toBeInTheDocument();
  });

  it('renders the empty state when the request resolves with no doses', async () => {
    dosesApi.list.mockResolvedValue([]);

    render(<DosesHarness />);

    await waitFor(() =>
      expect(screen.getByText('Nothing is waiting right now.')).toBeInTheDocument()
    );
    expect(screen.queryByText('Loading care data…')).not.toBeInTheDocument();
  });

  it('shows a visible error message, not a blank screen, when the request rejects', async () => {
    dosesApi.list.mockRejectedValue(new Error('Could not reach Gamira. Check your connection and try again.'));

    render(<DosesHarness />);

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Could not reach Gamira. Check your connection and try again.'
      )
    );
    expect(screen.queryByText('Loading care data…')).not.toBeInTheDocument();
  });
});
