import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { gamira } from '@/api/gamiraClient';

const AuthContext = createContext(null);

// Local-only escape hatch: set VITE_BYPASS_AUTH=true and VITE_DEV_AUTH_SUBJECT
// in .env.local to sign in against a backend running with AUTH_MODE=dev.
const BYPASS_AUTH = import.meta.env.VITE_BYPASS_AUTH === 'true';
const DEV_SUBJECT = import.meta.env.VITE_DEV_AUTH_SUBJECT || 'sharma-senior';

/**
 * `?dev=<subject>` signs this window in as that development identity.
 *
 * One dev server can then serve several windows that are different people —
 * how `run.py` opens two Parent Apps at once. Development builds only, and the
 * backend still refuses `dev:` tokens outside local and test.
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

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [seniors, setSeniors] = useState([]);
  const [families, setFamilies] = useState([]);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoadingAuth, setIsLoadingAuth] = useState(true);
  const [authError, setAuthError] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);

  const applySession = useCallback((session) => {
    setUser(session.user);
    setFamilies(session.families || []);
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

  const signIn = useCallback(
    async (token) => {
      gamira.auth.setToken(token);
      await checkUserAuth();
    },
    [checkUserAuth]
  );

  const logout = useCallback((shouldRedirect = true) => {
    gamira.auth.logout();
    setUser(null);
    setFamilies([]);
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
    [applySession]
  );

  // The Parent App is the senior's own device. Their profile is the one linked
  // to the signed-in user; if the family has not linked one yet, fall back to
  // the first visible person so the screens still have something to show.
  const self = useMemo(() => {
    if (!user) return null;
    return seniors.find((senior) => senior.user_id === user.id) || seniors[0] || null;
  }, [seniors, user]);

  const value = useMemo(
    () => ({
      user,
      families,
      seniors,
      self,
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
      seniors,
      self,
      isAuthenticated,
      isLoadingAuth,
      authError,
      authChecked,
      signIn,
      logout,
      navigateToLogin,
      checkUserAuth,
      updateProfile,
    ]
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
