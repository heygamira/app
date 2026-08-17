import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { gamira } from '@/api/gamiraClient';

const AuthContext = createContext(null);

const ACTIVE_SENIOR_KEY = 'gamira_active_senior_id';

// Local-only escape hatch: set VITE_BYPASS_AUTH=true and VITE_DEV_AUTH_SUBJECT
// in .env.local to sign in against a backend running with AUTH_MODE=dev. The
// backend refuses that mode in staging and production, so this cannot become a
// way into real data.
const BYPASS_AUTH = import.meta.env.VITE_BYPASS_AUTH === 'true';
const DEV_SUBJECT = import.meta.env.VITE_DEV_AUTH_SUBJECT || 'sharma-owner';

/**
 * `?dev=<subject>` signs this window in as that development identity.
 *
 * One dev server can then serve several windows that are different people —
 * how `run.py` opens a dashboard and a second family member's view at once.
 * Development builds only, and the backend still refuses `dev:` tokens outside
 * local and test.
 *
 * @returns {string | null}
 */
function devSubjectFromUrl() {
  if (!import.meta.env.DEV) return null;
  try {
    return new URLSearchParams(window.location.search).get('dev');
  } catch {
    return null;
  }
}

// The backend is the source of truth for a user's fields. These aliases exist
// only so presentation components can keep using the names they already have.
function normalizeUser(user) {
  if (!user) return null;
  return {
    ...user,
    name: user.display_name,
    full_name: user.display_name,
    photo_url: user.avatar_url,
  };
}

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [families, setFamilies] = useState([]);
  const [memberships, setMemberships] = useState([]);
  const [seniors, setSeniors] = useState([]);
  const [activeSeniorId, setActiveSeniorId] = useState(() => {
    try {
      return localStorage.getItem(ACTIVE_SENIOR_KEY);
    } catch {
      return null;
    }
  });

  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoadingAuth, setIsLoadingAuth] = useState(true);
  const [authError, setAuthError] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);

  const applySession = useCallback((session) => {
    setUser(normalizeUser(session.user));
    setFamilies(session.families || []);
    setMemberships(session.memberships || []);
    setSeniors(session.seniors || []);
    setIsAuthenticated(true);
    setAuthError(null);
  }, []);

  const checkUserAuth = useCallback(async () => {
    setIsLoadingAuth(true);
    try {
      const urlSubject = devSubjectFromUrl();
      if (urlSubject) {
        applySession(await gamira.auth.signInWithDevToken(urlSubject));
      } else if (BYPASS_AUTH && !gamira.auth.isAuthenticated()) {
        applySession(await gamira.auth.signInWithDevToken(DEV_SUBJECT));
      } else if (!gamira.auth.isAuthenticated()) {
        setIsAuthenticated(false);
        setAuthError({ type: 'auth_required', message: 'Please sign in to continue.' });
      } else {
        applySession(await gamira.auth.me());
      }
    } catch (error) {
      setIsAuthenticated(false);
      setUser(null);
      if (error.isAuthError) {
        // A rejected token is not worth keeping; clearing it avoids a loop of
        // failing requests on every screen.
        gamira.auth.clearToken();
        setAuthError({ type: 'auth_required', message: 'Please sign in again.' });
      } else {
        setAuthError({
          type: error.code === 'network_unavailable' ? 'offline' : 'unknown',
          message: error.message,
        });
      }
    } finally {
      setIsLoadingAuth(false);
      setAuthChecked(true);
    }
  }, [applySession]);

  useEffect(() => {
    checkUserAuth();
  }, [checkUserAuth]);

  // Keep a valid selection whenever the visible people change.
  useEffect(() => {
    if (!seniors.length) return;
    if (!seniors.some((senior) => senior.id === activeSeniorId)) {
      setActiveSeniorId(seniors[0].id);
    }
  }, [seniors, activeSeniorId]);

  const selectSenior = useCallback((seniorId) => {
    setActiveSeniorId(seniorId);
    try {
      if (seniorId) localStorage.setItem(ACTIVE_SENIOR_KEY, seniorId);
      else localStorage.removeItem(ACTIVE_SENIOR_KEY);
    } catch {
      /* private browsing */
    }
  }, []);

  const signIn = useCallback(
    async (token) => {
      gamira.auth.setToken(token);
      await checkUserAuth();
    },
    [checkUserAuth],
  );

  const logout = useCallback(async (shouldRedirect = true) => {
    gamira.auth.logout();
    setUser(null);
    setFamilies([]);
    setMemberships([]);
    setSeniors([]);
    setIsAuthenticated(false);
    setAuthError({ type: 'auth_required', message: 'You are signed out.' });
    if (shouldRedirect) window.location.assign('/login');
  }, []);

  const navigateToLogin = useCallback(() => {
    window.location.assign('/login');
  }, []);

  const updateProfile = useCallback(
    async (patch) => {
      const session = await gamira.auth.updateMe(patch);
      applySession(session);
      return session;
    },
    [applySession],
  );

  const value = useMemo(
    () => ({
      user,
      families,
      memberships,
      seniors,
      activeFamily: families[0] || null,
      activeSenior: seniors.find((senior) => senior.id === activeSeniorId) || null,
      activeSeniorId,
      selectSenior,
      isAuthenticated,
      isLoadingAuth,
      authError,
      authChecked,
      signIn,
      logout,
      navigateToLogin,
      checkUserAuth,
      updateProfile,
    }),
    [
      user,
      families,
      memberships,
      seniors,
      activeSeniorId,
      selectSenior,
      isAuthenticated,
      isLoadingAuth,
      authError,
      authChecked,
      signIn,
      logout,
      navigateToLogin,
      checkUserAuth,
      updateProfile,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export default AuthContext;
