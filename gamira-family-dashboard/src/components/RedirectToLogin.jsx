import { Navigate, useLocation } from 'react-router-dom';

// A plain `<Navigate to="/login" />` drops wherever the user was trying to
// go, which breaks an invitation link opened while signed out: they'd land
// on the dashboard home instead of accepting the invite they clicked.
export default function RedirectToLogin() {
  const location = useLocation();
  const returnTo = encodeURIComponent(`${location.pathname}${location.search}`);
  return <Navigate to={`/login?returnTo=${returnTo}`} replace />;
}
