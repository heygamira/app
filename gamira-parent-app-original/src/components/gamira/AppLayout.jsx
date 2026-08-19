import { Outlet } from 'react-router-dom';
import { usePushRegistration } from '@/lib/usePushRegistration';

export default function AppLayout() {
  // No UI here: registration re-runs silently on every load once permission
  // is already granted, and asking out loud only ever happens from the
  // toggle on the Notifications settings page.
  usePushRegistration();

  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <main className="flex-1 overflow-y-auto pb-8">
        <Outlet />
      </main>
    </div>
  );
}
