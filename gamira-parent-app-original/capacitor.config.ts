import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.gamira.parent',
  appName: 'Gamira',
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
  },
};

export default config;
