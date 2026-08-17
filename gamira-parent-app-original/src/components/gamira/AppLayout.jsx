import { Outlet } from 'react-router-dom';

export default function AppLayout() {
  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <main className="flex-1 overflow-y-auto pb-8">
        <Outlet />
      </main>
    </div>
  );
}
