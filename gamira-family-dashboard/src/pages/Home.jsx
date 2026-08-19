import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "@/lib/AuthContext";
import { useSwipeNav } from "@/lib/useSwipeNav";
import { usePoll } from "@/lib/usePoll";
import { careStatusFor } from "@/lib/careStatus";
import { buildFamilySummary } from "@/lib/careSummary";
import { dashboardApi, toMember } from "@/api/dashboardData";
import WelcomeCard from "@/components/gamira/WelcomeCard";
import QuickActions from "@/components/gamira/QuickActions";
import FamilySection from "@/components/gamira/FamilySection";
import ScheduleList from "@/components/gamira/ScheduleList";
import HealthOverview from "@/components/gamira/HealthOverview";
import MedicationStatus from "@/components/gamira/MedicationStatus";
import MemberSelector from "@/components/gamira/MemberSelector";
import AIInsights from "@/components/gamira/AIInsights";
import EmergencyAlerts from "@/components/gamira/EmergencyAlerts";
import WeeklyReport from "@/components/gamira/WeeklyReport";
import UpcomingAppointments from "@/components/gamira/UpcomingAppointments";
import RecentActivity from "@/components/gamira/RecentActivity";
import VoiceAssistant from "@/components/gamira/VoiceAssistant";

const RESOLVED = ["taken", "skipped", "missed"];

function withinDays(value, days) {
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return false;
  return Date.now() - at.getTime() <= days * 24 * 60 * 60 * 1000;
}

// Routine data has no urgency of its own left to justify polling every few
// seconds now that an SOS or a device flag arrives over the live event stream
// (see useAlerts) the instant it happens. A minute-old dose list is a fine
// trade for turning 6×N requests every 5 seconds into 1 every 60.
const HOME_POLL_MS = 60_000;

export default function Home() {
  const navigate = useNavigate();
  const { seniors, activeFamily, selectSenior, activeSeniorId } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);
  const memberKey = members.map((m) => m.id).join(",");
  const familyId = activeFamily?.id;

  const [doses, setDoses] = useState([]);
  const [readings, setReadings] = useState([]);
  const [medicines, setMedicines] = useState([]);
  const [events, setEvents] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);
  const [dir, setDir] = useState(0);

  const load = useCallback(async () => {
    if (!members.length || !familyId) {
      setLoading(false);
      return;
    }
    try {
      const { doses: d, readings: r, medicines: m, events: e, appointments: a, reminders: rem } =
        await dashboardApi.summary(familyId, members);
      setDoses(d);
      setReadings(r);
      setMedicines(m);
      setEvents(e);
      setAppointments(a);
      setReminders(rem);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
    // members is rebuilt on every render; the ids (via memberKey) and the
    // family id are what actually change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memberKey, familyId]);

  useEffect(() => {
    load();
  }, [load]);

  // A safety net, not the primary path: an SOS or a device flag now arrives
  // over the live event stream the instant it happens (see useAlerts), and
  // this just keeps the routine lists from going stale while the screen sits
  // open.
  usePoll(load, HOME_POLL_MS);

  const selected = members.find((m) => m.id === activeSeniorId) || members[0] || null;

  const switchMember = (d) => {
    const idx = members.findIndex((m) => m.id === selected?.id);
    if (idx < 0) return;
    const next = Math.min(members.length - 1, Math.max(0, idx + (d === -1 ? 1 : -1)));
    if (next !== idx) {
      setDir(d);
      selectSenior(members[next].id);
    }
  };
  const swipe = useSwipeNav(switchMember);

  const variants = {
    enter: (d) => ({ x: d === -1 ? 60 : -60, opacity: 0 }),
    center: { x: 0, opacity: 1 },
    exit: (d) => ({ x: d === -1 ? -60 : 60, opacity: 0 }),
  };

  const statusFor = useCallback(
    (memberId) => careStatusFor(doses.filter((dose) => dose.family_member_id === memberId)),
    [doses],
  );

  const selDoses = selected ? doses.filter((d) => d.family_member_id === selected.id) : doses;
  const selReadings = selected ? readings.filter((r) => r.family_member_id === selected.id) : readings;
  const selReminders = selected
    ? reminders.filter((r) => r.family_member_id === selected.id)
    : reminders;

  // Today's schedule: the person's dose events, plus their active reminders.
  const scheduleItems = useMemo(() => {
    const doseRows = selDoses.map((dose) => ({
      id: `dose-${dose.id}`,
      doseId: dose.id,
      title: dose.medication_name || "Medicine",
      subtitle: dose.dose_quantity || selected?.name || "",
      type: "medication",
      time: dose.scheduled_local_time,
      status: dose.status,
    }));
    const reminderRows = selReminders
      .filter((reminder) => reminder.status === "active")
      .map((reminder) => ({
        id: `reminder-${reminder.id}`,
        title: reminder.title,
        subtitle: reminder.instructions || reminder.type,
        type: reminder.type,
        time: reminder.time || "",
        status: "active",
      }));
    return [...doseRows, ...reminderRows].sort((a, b) =>
      String(a.time).localeCompare(String(b.time)),
    );
  }, [selDoses, selReminders, selected]);

  const confirmDose = async (item) => {
    setBusyId(item.doseId);
    try {
      await dosesApi.markTaken(item.doseId);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  };

  const takenToday = selDoses.filter((d) => d.status === "taken").length;
  const missedToday = doses.filter((d) => d.status === "missed");

  const weekEvents = events.filter((event) => withinDays(event.created_date, 7));
  const weekTaken = weekEvents.filter((e) => e.type === "medication_taken").length;
  const weekResolved = weekEvents.filter((e) =>
    RESOLVED.some((status) => e.type === `medication_${status}`),
  ).length;

  const summary = useMemo(
    () => buildFamilySummary({ members, meds: medicines, events, days: 7 }),
    [members, medicines, events],
  );

  const upcoming = appointments.filter((a) => new Date(a.starts_at).getTime() >= Date.now());

  return (
    <div className="space-y-7 select-none" {...swipe}>
      <WelcomeCard />
      <QuickActions />

      {error && (
        <div className="rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      <FamilySection members={members} statusFor={statusFor} loading={loading} />

      {members.length > 0 && (
        <MemberSelector
          members={members}
          value={selected?.id}
          onChange={selectSenior}
          statusFor={statusFor}
        />
      )}

      <AnimatePresence mode="wait" custom={dir}>
        <motion.div
          key={selected?.id || "none"}
          custom={dir}
          variants={variants}
          initial="enter"
          animate="center"
          exit="exit"
          transition={{ duration: 0.28, ease: "easeOut" }}
          className="space-y-7"
        >
          <ScheduleList
            items={scheduleItems}
            loading={loading}
            onConfirm={confirmDose}
            busyId={busyId}
          />
          <HealthOverview
            readings={selReadings}
            memberName={selected?.name}
            memberId={selected?.id}
          />
          <MedicationStatus
            taken={takenToday}
            total={selDoses.length}
            memberName={selected?.name}
            onClick={() => navigate("/medication")}
          />
        </motion.div>
      </AnimatePresence>

      <AIInsights lines={summary.lines} disclaimer={summary.disclaimer} />
      <EmergencyAlerts missed={missedToday} />
      <WeeklyReport taken={weekTaken} resolved={weekResolved} />
      <UpcomingAppointments appointments={upcoming} />
      <RecentActivity events={events} />
      <VoiceAssistant />
    </div>
  );
}
