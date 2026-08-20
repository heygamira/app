import { lazy, Suspense, useEffect } from 'react';
import { Capacitor } from '@capacitor/core';
import { SplashScreen } from '@capacitor/splash-screen';
import { Toaster } from '@/components/ui/toaster';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClientInstance } from '@/lib/query-client';
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import { AuthProvider, useAuth } from '@/lib/AuthContext';
import ScrollToTop from './components/ScrollToTop';
import ProtectedRoute from '@/components/ProtectedRoute';
import RedirectToLogin from '@/components/RedirectToLogin';
import RequireFamily from '@/components/RequireFamily';
import Layout from '@/components/gamira/Layout';
import { ThemeProvider } from '@/lib/ThemeContext';
import Login from '@/pages/Login';

// Native only: capacitor.config.ts sets launchAutoHide false so the splash
// stays up past Capacitor's own load event, through the first paint of an
// unauthenticated/empty screen, until the real auth state is known.
function SplashGate() {
  const { authChecked } = useAuth();
  useEffect(() => {
    if (authChecked && Capacitor.isNativePlatform()) {
      SplashScreen.hide();
    }
  }, [authChecked]);
  return null;
}

// Lazy-loaded: everything behind sign-in. Login stays a static import so the
// one public route has no extra network round trip; every other page is its
// own chunk, fetched when its route is first visited. Route changes shared
// the same 1.58 MB bundle before this.
const AcceptInvite = lazy(() => import('@/pages/AcceptInvite'));
const InviteMember = lazy(() => import('@/pages/InviteMember'));
const FamilyAccess = lazy(() => import('@/pages/FamilyAccess'));
const Home = lazy(() => import('@/pages/Home'));
const Health = lazy(() => import('@/pages/Health'));
const HealthDetail = lazy(() => import('@/pages/HealthDetail'));
const Reminders = lazy(() => import('@/pages/Reminders'));
const Family = lazy(() => import('@/pages/Family'));
const More = lazy(() => import('@/pages/More'));
const AISummary = lazy(() => import('@/pages/AISummary'));
const AIAssistant = lazy(() => import('@/pages/AIAssistant'));
const GamiraMemory = lazy(() => import('@/pages/GamiraMemory'));
const GamiraNoticed = lazy(() => import('@/pages/GamiraNoticed'));
const AddReminder = lazy(() => import('@/pages/AddReminder'));
const AddMember = lazy(() => import('@/pages/AddMember'));
const MemberProfile = lazy(() => import('@/pages/MemberProfile'));
const Medication = lazy(() => import('@/pages/Medication'));
const AddMedicine = lazy(() => import('@/pages/AddMedicine'));
const MedicineDetail = lazy(() => import('@/pages/MedicineDetail'));
const Reports = lazy(() => import('@/pages/Reports'));
const EmergencySOS = lazy(() => import('@/pages/EmergencySOS'));
const Timeline = lazy(() => import('@/pages/Timeline'));
const Notifications = lazy(() => import('@/pages/Notifications'));
const SmartHome = lazy(() => import('@/pages/SmartHome'));
const Settings = lazy(() => import('@/pages/Settings'));
const Privacy = lazy(() => import('@/pages/Privacy'));
const Subscription = lazy(() => import('@/pages/Subscription'));
const Support = lazy(() => import('@/pages/Support'));
const EditProfile = lazy(() => import('@/pages/EditProfile'));
const About = lazy(() => import('@/pages/About'));

const RouteFallback = () => (
  <div className="fixed inset-0 flex items-center justify-center">
    <div className="w-8 h-8 border-4 border-secondary border-t-primary rounded-full animate-spin"></div>
  </div>
);

// Sign-in is the only public route. Everything else sits behind
// ProtectedRoute, which distinguishes "signed out" from "backend unreachable"
// so a failed request never masquerades as an expired session.
const AppRoutes = () => (
  <Suspense fallback={<RouteFallback />}>
  <Routes>
    <Route path="/login" element={<Login />} />
    <Route element={<ProtectedRoute unauthenticatedElement={<RedirectToLogin />} />}>
      <Route path="/invite/:token" element={<AcceptInvite />} />
      <Route element={<RequireFamily />}>
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />
          <Route path="/health" element={<Health />} />
          <Route path="/health/:metric" element={<HealthDetail />} />
          <Route path="/reminders" element={<Reminders />} />
          <Route path="/family" element={<Family />} />
          <Route path="/family-access" element={<FamilyAccess />} />
          <Route path="/invite-member" element={<InviteMember />} />
          <Route path="/more" element={<More />} />
          <Route path="/ai-summary" element={<AISummary />} />
          <Route path="/ai-assistant" element={<AIAssistant />} />
          <Route path="/gamira-memory" element={<GamiraMemory />} />
          <Route path="/gamira-noticed" element={<GamiraNoticed />} />
          <Route path="/add-reminder" element={<AddReminder />} />
          <Route path="/add-member" element={<AddMember />} />
          <Route path="/member/:id" element={<MemberProfile />} />
          <Route path="/member/:id/edit" element={<AddMember />} />
          <Route path="/medication" element={<Medication />} />
          <Route path="/add-medicine" element={<AddMedicine />} />
          <Route path="/medicine/:id" element={<MedicineDetail />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/emergency" element={<EmergencySOS />} />
          <Route path="/timeline" element={<Timeline />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/smart-home" element={<SmartHome />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/subscription" element={<Subscription />} />
          <Route path="/support" element={<Support />} />
          <Route path="/profile" element={<EditProfile />} />
          <Route path="/about" element={<About />} />
        </Route>
      </Route>
    </Route>
    <Route path="*" element={<PageNotFound />} />
  </Routes>
  </Suspense>
);

function App() {
  return (
    <AuthProvider>
      <SplashGate />
      <QueryClientProvider client={queryClientInstance}>
        <Router>
          <ScrollToTop />
          <ThemeProvider>
            <AppRoutes />
          </ThemeProvider>
        </Router>
        <Toaster />
      </QueryClientProvider>
    </AuthProvider>
  );
}

export default App;
