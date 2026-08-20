import { useEffect, useState } from 'react';
import { Network } from '@capacitor/network';

/**
 * Whether the device currently has a network connection.
 *
 * Backed by `@capacitor/network` rather than raw `navigator.onLine`/
 * `online`/`offline` listeners: its web implementation is a thin wrapper
 * around those same browser APIs (so it costs nothing for the Vite web
 * build), but it also reflects real connectivity inside the Android WebView,
 * where `navigator.onLine` can report `true` on a Wi-Fi network with no
 * actual internet.
 */
export function useOnlineStatus() {
  const [online, setOnline] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Network.getStatus().then(({ connected }) => {
      if (!cancelled) setOnline(connected);
    });

    const listenerHandle = Network.addListener('networkStatusChange', ({ connected }) => {
      setOnline(connected);
    });

    return () => {
      cancelled = true;
      listenerHandle.then((handle) => handle.remove());
    };
  }, []);

  return online;
}

export default useOnlineStatus;
