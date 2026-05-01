'use client';
import { useEffect, useRef } from 'react';
import { toast } from 'sonner';

const OFFLINE_TOAST_ID = 'network-offline';

export function useNetworkStatus() {
  const offlineToastShown = useRef(false);

  useEffect(() => {
    function handleOffline() {
      if (offlineToastShown.current) return;
      offlineToastShown.current = true;
      toast.error('You are offline. Check your connection.', {
        id: OFFLINE_TOAST_ID,
        duration: Infinity,
        icon: '📡',
      });
    }

    function handleOnline() {
      if (!offlineToastShown.current) return;
      toast.dismiss(OFFLINE_TOAST_ID);
      offlineToastShown.current = false;
      toast.success("You're back online.", { duration: 3000, icon: '✅' });
    }

    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);

    if (!navigator.onLine) handleOffline();

    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, []);
}
