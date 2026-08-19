import { Outlet } from 'react-router-dom';
import { useAuth } from '@/lib/AuthContext';
import CreateFamily from '@/pages/CreateFamily';

// A signed-in user with zero families cannot use any family-scoped screen —
// every one of them assumes `activeFamily` exists. Shown after auth so it can
// tell "no family yet" apart from "still checking who you are".
export default function RequireFamily() {
  const { families, isLoadingAuth } = useAuth();

  if (isLoadingAuth) return null;
  if (!families.length) return <CreateFamily />;
  return <Outlet />;
}
