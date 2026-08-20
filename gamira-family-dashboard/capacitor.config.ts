import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.gamira.dashboard',
  appName: 'Gamira Family',
  webDir: 'dist',
  plugins: {
    // `signInWithPopup` (used on the web build) does not work inside an
    // embedded WebView — Google blocks OAuth there. This routes Google
    // sign-in through the native Credential Manager / Google Sign-In SDK
    // instead, which needs android/app/google-services.json to exist (see
    // useFirebaseAuth.js).
    FirebaseAuthentication: {
      providers: ['google.com'],
    },
    // Held open past Capacitor's own load event until the auth check
    // resolves (see App.jsx's SplashGate) — otherwise the splash hides into a
    // flash of an unauthenticated/empty screen before the real one is ready.
    SplashScreen: {
      launchAutoHide: false,
    },
  },
};

export default config;
