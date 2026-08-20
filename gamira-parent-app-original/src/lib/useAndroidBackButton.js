import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Capacitor } from '@capacitor/core';
import { App as CapApp } from '@capacitor/app';
import { toast } from '@/components/ui/use-toast';

const EXIT_CONFIRM_WINDOW_MS = 2000;
// The two routes with no natural "back" target in this app's hub-and-spoke
// navigation (Home, and the pre-auth screen) — pressing back here means exit,
// not navigate(-1).
const EXIT_ROUTES = new Set(['/', '/login']);

export function useAndroidBackButton() {
  const navigate = useNavigate();
  const location = useLocation();
  // Registered once below; reads fresh location/armed state via refs rather
  // than re-subscribing the native listener on every navigation.
  const locationRef = useRef(location);
  locationRef.current = location;
  const armedRef = useRef(false);

  useEffect(() => {
    if (!Capacitor.isNativePlatform() || Capacitor.getPlatform() !== 'android') return undefined;

    const subPromise = CapApp.addListener('backButton', () => {
      if (!EXIT_ROUTES.has(locationRef.current.pathname)) {
        navigate(-1);
        return;
      }
      if (armedRef.current) {
        CapApp.exitApp();
        return;
      }
      armedRef.current = true;
      const { dismiss } = toast({ title: 'Press back again to exit' });
      setTimeout(() => {
        armedRef.current = false;
        dismiss();
      }, EXIT_CONFIRM_WINDOW_MS);
    });

    return () => {
      subPromise.then((sub) => sub.remove());
    };
  }, [navigate]);
}

export default useAndroidBackButton;
