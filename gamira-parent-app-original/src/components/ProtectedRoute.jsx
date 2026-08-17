import { Outlet } from 'react-router-dom';
import { useAuth } from '@/lib/AuthContext';

const DefaultFallback = () => (
  <div className="fixed inset-0 flex items-center justify-center">
    <div className="w-8 h-8 border-4 border-secondary border-t-primary rounded-full animate-spin"></div>
  </div>
);

export default function ProtectedRoute({ fallback = <DefaultFallback />, unauthenticatedElement }) {
  const { isAuthenticated, isLoadingAuth, authChecked, authError, checkUserAuth } = useAuth();

  if (isLoadingAuth || !authChecked) {
    return fallback;
  }

  // A backend or network failure is not a sign-in problem, so it must not send
  // the user to a login screen that cannot fix it.
  if (authError && authError.type !== 'auth_required') {
    return (
      <div className="fixed inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="text-lg font-semibold text-foreground">Gamira is unreachable</p>
        <p className="max-w-sm text-[15px] text-muted-foreground">{authError.message}</p>
        <button
          onClick={checkUserAuth}
          className="h-14 rounded-2xl bg-primary px-8 text-base font-semibold text-primary-foreground"
        >
          Try again
        </button>
      </div>
    );
  }

  if (!isAuthenticated) {
    return unauthenticatedElement;
  }

  return <Outlet />;
}
