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

  // A backend or network failure is not a sign-in problem: sending the user to
  // the login screen would hide the real cause and lose their place.
  if (authError && authError.type !== 'auth_required') {
    return (
      <div className="fixed inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="text-[15px] font-semibold text-foreground">Gamira is unreachable</p>
        <p className="max-w-sm text-[13px] text-muted-foreground">{authError.message}</p>
        <button
          onClick={checkUserAuth}
          className="rounded-2xl bg-primary px-5 py-2.5 text-[14px] font-semibold text-primary-foreground"
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
