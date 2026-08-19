import { useCallback } from 'react';
import {
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
} from 'firebase/auth';
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

  const signInWithGoogle = useCallback(
    () => withIdToken(signInWithPopup(auth, googleProvider)),
    [withIdToken],
  );

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
