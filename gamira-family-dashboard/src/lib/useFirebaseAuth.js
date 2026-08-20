import { useCallback } from 'react';
import {
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
} from 'firebase/auth';
import { Capacitor } from '@capacitor/core';
import { FirebaseAuthentication } from '@capacitor-firebase/authentication';
import { auth, googleProvider, firebaseEnabled } from '@/lib/firebase';
import { useAuth } from '@/lib/AuthContext';

// Wraps Firebase's own sign-in calls and hands the resulting ID token to the
// same `signIn(token)` the dev-identity path already uses — the backend
// verifies a bearer token, it doesn't care which identity provider minted it.
export function useFirebaseAuth() {
  const { signIn } = useAuth();

  const withIdToken = useCallback(
    async (credentialPromise) => {
      const credential = await credentialPromise;
      const idToken = await credential.user.getIdToken();
      await signIn(idToken);
    },
    [signIn],
  );

  // `signInWithPopup` cannot work inside a Capacitor WebView — Google
  // blocks OAuth there ("disallowed_useragent") — so the native app goes
  // through the platform's own Credential Manager / Google Sign-In SDK
  // instead, via `@capacitor-firebase/authentication`. That plugin signs
  // into a *native* Firebase Auth session; `getIdToken()` reads the token
  // back out of it, and from there it's the same `signIn(idToken)` the web
  // path already uses — the backend does not know or care which route it
  // came by.
  const signInWithGoogle = useCallback(async () => {
    if (Capacitor.isNativePlatform()) {
      await FirebaseAuthentication.signInWithGoogle();
      const { token } = await FirebaseAuthentication.getIdToken();
      await signIn(token);
      return;
    }
    return withIdToken(signInWithPopup(auth, googleProvider));
  }, [withIdToken, signIn]);

  const signInWithEmail = useCallback(
    (email, password) => withIdToken(signInWithEmailAndPassword(auth, email, password)),
    [withIdToken],
  );

  const registerWithEmail = useCallback(
    (email, password) => withIdToken(createUserWithEmailAndPassword(auth, email, password)),
    [withIdToken],
  );

  return { firebaseEnabled, signInWithGoogle, signInWithEmail, registerWithEmail };
}

export default useFirebaseAuth;
