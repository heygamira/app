import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { onIdTokenChanged } from 'firebase/auth';
import { gamira } from '@/api/gamiraClient';
import { auth as firebaseAuth, firebaseEnabled } from '@/lib/firebase';

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

  // Re-fetches `/me` without touching `isLoadingAuth`. `checkUserAuth`
  // toggling that flag is right for the initial "are we signed in" check —
  // but a screen gated on `isLoadingAuth` (ProtectedRoute renders its
  // fallback, not the route, while it is true) unmounts every time it calls
  // `checkUserAuth` to pick up a session change it just caused. If that
  // screen's own mount effect is what triggers the refresh, the remount
  // fires the effect again, which calls it again — an infinite mount/unmount
  // loop. `AcceptInvite` is exactly that screen.
  const refreshSession = useCallback(async () => {
    if (!gamira.auth.isAuthenticated()) return;
    applySession(await gamira.auth.me());
  }, [applySession]);

  useEffect(() => {
    checkUserAuth();
  }, [checkUserAuth]);

  // A Firebase ID token expires hourly; the SDK refreshes it in the
  // background and reports the new one here. Re-arm the stored bearer token
  // so a long-open tab doesn't start failing requests once the old one
  // expires. Left alone entirely while a `dev:` session is active, so this
  // can never clobber a dev-identity sign-in with a stale Firebase session
  // left over in the browser from a previous visit.
  useEffect(() => {
    if (!firebaseEnabled || !firebaseAuth) return undefined;
    return onIdTokenChanged(firebaseAuth, async (firebaseUser) => {
      if (!firebaseUser) return;
      const current = gamira.auth.getToken();
      if (current && current.startsWith('dev:')) return;
      gamira.auth.setToken(await firebaseUser.getIdToken());
    });
  }, []);

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

  // The Parent App is the senior's own device: it must show the profile
  // actually linked to the signed-in user, never merely the first one a
  // family happens to have. Falling back to `seniors[0]` here used to mean a
  // second cared-for person's Parent App silently showed the first person's
  // record until someone linked their account — wrong, and unnoticed because
  // it never errored. `RequireLinkedSenior` gates every screen that reads
  // this on it being non-null.
  const self = useMemo(() => {
    if (!user) return null;
    return seniors.find((senior) => senior.user_id === user.id) || null;
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
      refreshSession,
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
      refreshSession,
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
