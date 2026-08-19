import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import RequireLinkedSenior from '@/components/RequireLinkedSenior';
import { useAuth } from '@/lib/AuthContext';

// RequireLinkedSenior and the LinkAccount screen it falls back to both read
// useAuth from this module, so mocking it once here drives both.
vi.mock('@/lib/AuthContext', () => ({
  useAuth: vi.fn(),
}));

// A stand-in for the real guarded screens (Home, Health, Reminders, ...): it
// reads `self` the same way they do, so a test can tell whether the guard let
// through the signed-in user's own senior or something else.
function GuardedScreen() {
  const { self } = useAuth();
  return <p>Caring for {self.name}</p>;
}

function renderGuarded() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<RequireLinkedSenior />}>
          <Route path="/" element={<GuardedScreen />} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('RequireLinkedSenior', () => {
  it("renders the guarded screen for the signed-in user's own linked senior", () => {
    useAuth.mockReturnValue({
      self: { id: 'senior-2', name: 'Priya', user_id: 'user-2' },
      isLoadingAuth: false,
    });

    renderGuarded();

    expect(screen.getByText('Caring for Priya')).toBeInTheDocument();
  });

  it('renders the link-account screen, not a fallback senior, when the account is not linked', async () => {
    const logout = vi.fn();
    useAuth.mockReturnValue({
      self: null,
      isLoadingAuth: false,
      user: { name: 'Priya' },
      logout,
    });

    renderGuarded();

    // The bug this guards against: silently falling back to seniors[0] and
    // rendering somebody else's screen instead of asking to link the account.
    expect(screen.queryByText(/Caring for/)).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Almost there' })).toBeInTheDocument();
    expect(
      screen.getByText("Priya, your account isn't linked to a person's care profile yet.")
    ).toBeInTheDocument();

    const input = screen.getByLabelText('Invitation link');
    const continueButton = screen.getByRole('button', { name: 'Continue' });
    expect(continueButton).toBeDisabled();

    await userEvent.type(input, 'https://gamira.app/invite/abc123');
    expect(continueButton).toBeEnabled();
  });

  it('renders nothing while the initial auth check is still pending', () => {
    useAuth.mockReturnValue({
      self: null,
      isLoadingAuth: true,
    });

    const { container } = renderGuarded();

    expect(container).toBeEmptyDOMElement();
  });
});
