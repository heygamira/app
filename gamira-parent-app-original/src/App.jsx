import { Toaster } from '@/components/ui/toaster';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClientInstance } from '@/lib/query-client';
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import { AuthProvider } from '@/lib/AuthContext';
import ScrollToTop from './components/ScrollToTop';
import AndroidBackButtonEffect from '@/components/AndroidBackButtonEffect';
import NativePushNavigation from '@/components/NativePushNavigation';
import ProtectedRoute from '@/components/ProtectedRoute';
import RedirectToLogin from '@/components/RedirectToLogin';
import RequireLinkedSenior from '@/components/RequireLinkedSenior';
import AppLayout from '@/components/gamira/AppLayout';
import VoiceProvider from '@/lib/VoiceContext';
import { I18nProvider } from '@/lib/i18n';
import AcceptInvite from '@/pages/AcceptInvite';
import Home from '@/pages/Home';
import Health from '@/pages/Health';
import Reminders from '@/pages/Reminders';
import Family from '@/pages/Family';
import Login from '@/pages/Login';
import Settings from '@/pages/Settings';
import Profile from '@/pages/settings/Profile';
import Language from '@/pages/settings/Language';
import Voice from '@/pages/settings/Voice';
import Emergency from '@/pages/settings/Emergency';
import AccessibilityPage from '@/pages/settings/Accessibility';
import ContactSupport from '@/pages/settings/ContactSupport';
import AboutGamira from '@/pages/settings/AboutGamira';
import Theme from '@/pages/settings/Theme';
import Memory from '@/pages/settings/Memory';
import FamilyNotices from '@/pages/settings/FamilyNotices';
import Notifications from '@/pages/settings/Notifications';

// Sign-in is the only public route. ProtectedRoute distinguishes "signed out"
// from "backend unreachable", so a failed request never looks like an expired
// session to someone who cannot troubleshoot it.
const AppRoutes = () => (
  <Routes>
    <Route path="/login" element={<Login />} />
    <Route element={<ProtectedRoute unauthenticatedElement={<RedirectToLogin />} />}>
      <Route path="/invite/:token" element={<AcceptInvite />} />
      {/* Nothing past this point can assume a screen has a person to show
          until the signed-in account is actually linked to one. */}
      <Route element={<RequireLinkedSenior />}>
        {/* Voice wraps every signed-in screen, not just Home. It used to be
            mounted inside the home page, so navigating anywhere tore down the
            microphone and the wake-word detector — an app meant to be run by
            voice had voice on one screen out of six. */}
        <Route element={<VoiceProvider />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Home />} />
          <Route path="/health" element={<Health />} />
          <Route path="/reminders" element={<Reminders />} />
          <Route path="/family" element={<Family />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
        <Route path="/settings/profile" element={<Profile />} />
        <Route path="/settings/language" element={<Language />} />
        <Route path="/settings/voice" element={<Voice />} />
        <Route path="/settings/emergency" element={<Emergency />} />
        <Route path="/settings/accessibility" element={<AccessibilityPage />} />
        <Route path="/settings/contact-support" element={<ContactSupport />} />
        <Route path="/settings/about" element={<AboutGamira />} />
        <Route path="/settings/theme" element={<Theme />} />
        <Route path="/settings/memory" element={<Memory />} />
        <Route path="/settings/family-notices" element={<FamilyNotices />} />
        <Route path="/settings/notifications" element={<Notifications />} />
        </Route>
      </Route>
    </Route>
    <Route path="*" element={<PageNotFound />} />
  </Routes>
);

function App() {
  return (
    <AuthProvider>
      <QueryClientProvider client={queryClientInstance}>
        <Router>
          <ScrollToTop />
          <AndroidBackButtonEffect />
          <NativePushNavigation />
          <I18nProvider>
            <AppRoutes />
          </I18nProvider>
        </Router>
        <Toaster />
      </QueryClientProvider>
    </AuthProvider>
  );
}

export default App;
