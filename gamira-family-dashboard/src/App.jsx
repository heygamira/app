import { Toaster } from '@/components/ui/toaster';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClientInstance } from '@/lib/query-client';
import { BrowserRouter as Router, Route, Routes, Navigate } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import { AuthProvider } from '@/lib/AuthContext';
import ScrollToTop from './components/ScrollToTop';
import ProtectedRoute from '@/components/ProtectedRoute';
import Layout from '@/components/gamira/Layout';
import { ThemeProvider } from '@/lib/ThemeContext';
import Login from '@/pages/Login';
import Home from '@/pages/Home';
import Health from '@/pages/Health';
import HealthDetail from '@/pages/HealthDetail';
import Reminders from '@/pages/Reminders';
import Family from '@/pages/Family';
import More from '@/pages/More';
import AISummary from '@/pages/AISummary';
import AIAssistant from '@/pages/AIAssistant';
import AddReminder from '@/pages/AddReminder';
import AddMember from '@/pages/AddMember';
import MemberProfile from '@/pages/MemberProfile';
import Medication from '@/pages/Medication';
import AddMedicine from '@/pages/AddMedicine';
import MedicineDetail from '@/pages/MedicineDetail';
import Reports from '@/pages/Reports';
import EmergencySOS from '@/pages/EmergencySOS';
import Timeline from '@/pages/Timeline';
import Notifications from '@/pages/Notifications';
import SmartHome from '@/pages/SmartHome';
import Settings from '@/pages/Settings';
import Privacy from '@/pages/Privacy';
import Subscription from '@/pages/Subscription';
import Support from '@/pages/Support';
import EditProfile from '@/pages/EditProfile';
import About from '@/pages/About';

// Sign-in is the only public route. Everything else sits behind
// ProtectedRoute, which distinguishes "signed out" from "backend unreachable"
// so a failed request never masquerades as an expired session.
const AppRoutes = () => (
  <Routes>
    <Route path="/login" element={<Login />} />
    <Route element={<ProtectedRoute unauthenticatedElement={<Navigate to="/login" replace />} />}>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/health" element={<Health />} />
        <Route path="/health/:metric" element={<HealthDetail />} />
        <Route path="/reminders" element={<Reminders />} />
        <Route path="/family" element={<Family />} />
        <Route path="/more" element={<More />} />
        <Route path="/ai-summary" element={<AISummary />} />
        <Route path="/ai-assistant" element={<AIAssistant />} />
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
    <Route path="*" element={<PageNotFound />} />
  </Routes>
);

function App() {
  return (
    <AuthProvider>
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
