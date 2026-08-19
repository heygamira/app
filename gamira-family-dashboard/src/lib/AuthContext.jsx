import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { onIdTokenChanged } from 'firebase/auth';
import { gamira } from '@/api/gamiraClient';
import { auth as firebaseAuth, firebaseEnabled } from '@/lib/firebase';

const AuthContext = createContext(null);

const ACTIVE_SENIOR_KEY = 'gamira_active_senior_id';
const ACTIVE_FAMILY_KEY = 'gamira_active_family_id';

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
  // Every senior across every family the user belongs to. Almost nothing
  // should read this directly — `seniors` below is the same list narrowed to
  // the active family, which is what every screen actually means by "family
  // member". Consuming `allSeniors` while switching families showed a Sharma
  // parent's grid growing to include an Iyer parent the moment `/me` returned
  // a second family.
  const [allSeniors, setAllSeniors] = useState([]);
  const [activeSeniorId, setActiveSeniorId] = useState(() => {
    try {
      return localStorage.getItem(ACTIVE_SENIOR_KEY);
    } catch {
      return null;
    }
  });
  const [activeFamilyId, setActiveFamilyId] = useState(() => {
    try {
      return localStorage.getItem(ACTIVE_FAMILY_KEY);
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
    setAllSeniors(session.seniors || []);
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

  // Re-fetches `/me` without touching `isLoadingAuth`. `checkUserAuth` toggling
  // that flag is exactly right for the initial "are we signed in" check — but
  // a screen that is itself gated on `isLoadingAuth` (ProtectedRoute renders
  // its fallback, not the route, while it is true) unmounts every time it
  // calls `checkUserAuth` to pick up a session change it just caused. If that
  // screen's own mount effect is what triggers the refresh, the remount fires
  // the effect again, which calls it again — an infinite mount/unmount loop.
  // `AcceptInvite` is exactly that screen: use this there, and anywhere a
  // mount effect (not a one-off click handler that then navigates away) needs
  // fresh session data.
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

  // Keep a valid selection whenever the visible families change, defaulting
  // to the first one. This is the only place that decides which family is
  // active — everything else reads it from context.
  useEffect(() => {
    if (!families.length) return;
    if (!families.some((family) => family.id === activeFamilyId)) {
      setActiveFamilyId(families[0].id);
    }
  }, [families, activeFamilyId]);

  const activeFamily = useMemo(
    () => families.find((family) => family.id === activeFamilyId) || families[0] || null,
    [families, activeFamilyId],
  );

  // `/me` returns every senior across every family the user belongs to in one
  // list, so this is the narrowing every screen actually wants.
  const seniors = useMemo(
    () =>
      activeFamily ? allSeniors.filter((senior) => senior.family_id === activeFamily.id) : [],
    [allSeniors, activeFamily],
  );

  const selectFamily = useCallback((familyId) => {
    setActiveFamilyId(familyId);
    try {
      if (familyId) localStorage.setItem(ACTIVE_FAMILY_KEY, familyId);
      else localStorage.removeItem(ACTIVE_FAMILY_KEY);
    } catch {
      /* private browsing */
    }
  }, []);

  // Keep a valid selection whenever the visible people change — including
  // when switching family, since a senior selected in one family is not a
  // valid selection in another.
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
    setAllSeniors([]);
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
      activeFamily,
      activeFamilyId,
      selectFamily,
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
      refreshSession,
      updateProfile,
    }),
    [
      user,
      families,
      memberships,
      seniors,
      activeFamily,
      activeFamilyId,
      selectFamily,
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
      refreshSession,
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
