import { Outlet } from 'react-router-dom';
import { useAuth } from '@/lib/AuthContext';
import LinkAccount from '@/pages/LinkAccount';

// Every care screen assumes `self` is the signed-in user's own linked senior
// profile. Gating here means those screens never have to guess whether that
// assumption held, and a not-yet-linked account gets an explicit next step
// instead of silently seeing whichever person the family added first.
export default function RequireLinkedSenior() {
  const { self, isLoadingAuth } = useAuth();

  if (isLoadingAuth) return null;
  if (!self) return <LinkAccount />;
  return <Outlet />;
}
