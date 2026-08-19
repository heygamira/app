import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AuthProvider, useAuth } from '@/lib/AuthContext';
import { gamira } from '@/api/gamiraClient';

// AuthContext only reaches into `gamira.auth`, so that's all this mock needs
// to provide. `me()` stands in for the `/me` session fetch `checkUserAuth`
// makes on mount.
vi.mock('@/api/gamiraClient', () => ({
  gamira: {
    auth: {
      isAuthenticated: vi.fn(() => true),
      me: vi.fn(),
      getToken: vi.fn(),
      setToken: vi.fn(),
      clearToken: vi.fn(),
      logout: vi.fn(),
      signInWithDevToken: vi.fn(),
      updateMe: vi.fn(),
    },
  },
}));

const ACTIVE_FAMILY_KEY = 'gamira_active_family_id';

// Two families whose seniors overlap in id-space only by coincidence of
// shape — Family A (Sharma) has two seniors, Family B (Iyer) has one. This
// is the exact shape of the bug described in AuthContext.jsx's comment on
// `allSeniors`: reading the unnarrowed list would show all three regardless
// of which family is active.
const twoFamilySession = {
  user: { id: 'user-1', display_name: 'Asha Rao', avatar_url: null },
  families: [
    { id: 'fam-a', name: 'Sharma Family' },
    { id: 'fam-b', name: 'Iyer Family' },
  ],
  memberships: [],
  seniors: [
    { id: 'sen-a1', family_id: 'fam-a', name: 'Grandma Sharma' },
    { id: 'sen-a2', family_id: 'fam-a', name: 'Grandpa Sharma' },
    { id: 'sen-b1', family_id: 'fam-b', name: 'Grandma Iyer' },
  ],
};

function Consumer() {
  const { seniors, families, activeFamily, selectFamily, isLoadingAuth } = useAuth();

  if (isLoadingAuth) return <p>Loading…</p>;

  return (
    <div>
      <p data-testid="active-family-name">{activeFamily ? activeFamily.name : 'none'}</p>
      <ul>
        {seniors.map((senior) => (
          <li key={senior.id}>{senior.name}</li>
        ))}
      </ul>
      {families.map((family) => (
        <button key={family.id} onClick={() => selectFamily(family.id)}>
          Switch to {family.name}
        </button>
      ))}
    </div>
  );
}

function renderWithProvider() {
  return render(
    <AuthProvider>
      <Consumer />
    </AuthProvider>,
  );
}

beforeEach(() => {
  gamira.auth.me.mockReset();
  gamira.auth.isAuthenticated.mockReturnValue(true);
  localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe('AuthContext seniors narrowing', () => {
  it('exposes seniors narrowed to only the active family, not every family', async () => {
    gamira.auth.me.mockResolvedValue(twoFamilySession);

    renderWithProvider();

    await waitFor(() => {
      expect(screen.getByTestId('active-family-name')).toHaveTextContent('Sharma Family');
    });
    expect(screen.getByText('Grandma Sharma')).toBeInTheDocument();
    expect(screen.getByText('Grandpa Sharma')).toBeInTheDocument();
    expect(screen.queryByText('Grandma Iyer')).not.toBeInTheDocument();
  });

  it('selectFamily switches the active family, narrows seniors to match, and persists the choice', async () => {
    gamira.auth.me.mockResolvedValue(twoFamilySession);

    renderWithProvider();
    await waitFor(() => {
      expect(screen.getByTestId('active-family-name')).toHaveTextContent('Sharma Family');
    });

    fireEvent.click(screen.getByText('Switch to Iyer Family'));

    await waitFor(() => {
      expect(screen.getByTestId('active-family-name')).toHaveTextContent('Iyer Family');
    });
    expect(screen.getByText('Grandma Iyer')).toBeInTheDocument();
    expect(screen.queryByText('Grandma Sharma')).not.toBeInTheDocument();
    expect(screen.queryByText('Grandpa Sharma')).not.toBeInTheDocument();
    expect(localStorage.getItem(ACTIVE_FAMILY_KEY)).toBe('fam-b');
  });

  it('recovers to a valid family when the persisted active family id no longer matches any fetched family', async () => {
    // Stands in for a caregiver who switched families last session and has
    // since been removed from (or never belonged to) "fam-ghost".
    localStorage.setItem(ACTIVE_FAMILY_KEY, 'fam-ghost');
    gamira.auth.me.mockResolvedValue(twoFamilySession);

    renderWithProvider();

    await waitFor(() => {
      expect(screen.getByTestId('active-family-name')).toHaveTextContent('Sharma Family');
    });
    expect(screen.getByText('Grandma Sharma')).toBeInTheDocument();
    expect(screen.getByText('Grandpa Sharma')).toBeInTheDocument();
    expect(screen.queryByText('Grandma Iyer')).not.toBeInTheDocument();
  });
});
