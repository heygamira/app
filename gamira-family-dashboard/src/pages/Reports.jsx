import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Download, FileBarChart } from "lucide-react";
import { jsPDF } from "jspdf";
import { Capacitor } from "@capacitor/core";
import { Filesystem, Directory } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";
import { useAuth } from "@/lib/AuthContext";
import { useSwipeNav } from "@/lib/useSwipeNav";
import { healthApi, medicinesApi, timelineApi, toMember } from "@/api/dashboardData";
import { buildCareSummary, buildFamilySummary } from "@/lib/careSummary";
import PageHeader from "@/components/gamira/PageHeader";
import MemberSelector from "@/components/gamira/MemberSelector";
import EmptyState from "@/components/gamira/EmptyState";

const PERIODS = [
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

function withinDays(value, days) {
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return false;
  return Date.now() - at.getTime() <= days * 24 * 60 * 60 * 1000;
}

export default function Reports() {
  const navigate = useNavigate();
  const { seniors } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);
  const memberKey = members.map((m) => m.id).join(",");

  const [medicines, setMedicines] = useState([]);
  const [readings, setReadings] = useState([]);
  const [events, setEvents] = useState([]);
  const [selMember, setSelMember] = useState("all");
  const [days, setDays] = useState(7);
  const [error, setError] = useState("");
  const [dir, setDir] = useState(0);

  const memberItems = [{ id: "all" }, ...members];

  const load = useCallback(async () => {
    if (!members.length) return;
    try {
      const [meds, reads, timeline] = await Promise.all([
        medicinesApi.listForMembers(members),
        healthApi.listForMembers(members, { limit: 200 }),
        timelineApi.listForMembers(members, { limit: 200 }),
      ]);
      setMedicines(meds);
      setReadings(reads);
      setEvents(timeline);
      setError("");
    } catch (err) {
      setError(err.message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memberKey]);

  useEffect(() => {
    load();
  }, [load]);

  const switchMember = (d) => {
    const idx = memberItems.findIndex((m) => m.id === selMember);
    if (idx < 0) return;
    const next = Math.min(memberItems.length - 1, Math.max(0, idx + (d === -1 ? 1 : -1)));
    if (next !== idx) {
      setDir(d);
      setSelMember(memberItems[next].id);
    }
  };
  const swipe = useSwipeNav(switchMember);

  const variants = {
    enter: (d) => ({ x: d === -1 ? 60 : -60, opacity: 0 }),
    center: { x: 0, opacity: 1 },
    exit: (d) => ({ x: d === -1 ? -60 : 60, opacity: 0 }),
  };

  const selected = selMember === "all" ? null : members.find((m) => m.id === selMember) || null;
  const scopedMeds = selected ? medicines.filter((m) => m.family_member_id === selected.id) : medicines;
  const scopedReadings = selected ? readings.filter((r) => r.family_member_id === selected.id) : readings;
  const scopedEvents = (selected ? events.filter((e) => e.family_member_id === selected.id) : events).filter(
    (e) => withinDays(e.created_date, days),
  );

  const taken = scopedEvents.filter((e) => e.type === "medication_taken").length;
  const skipped = scopedEvents.filter((e) => e.type === "medication_skipped").length;
  const missed = scopedEvents.filter((e) => e.type === "medication_missed").length;
  const resolved = taken + skipped + missed;
  const confirmed = resolved ? Math.round((taken / resolved) * 100) : 0;

  const summary = useMemo(
    () =>
      selected
        ? buildCareSummary({ member: selected, meds: scopedMeds, records: scopedReadings, events: scopedEvents, days })
        : buildFamilySummary({ members, meds: medicines, events: scopedEvents, days }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selected, scopedMeds, scopedReadings, scopedEvents, members, medicines, days],
  );

  const exportPDF = async () => {
    const doc = new jsPDF();
    let y = 20;
    doc.setFontSize(18);
    doc.text("Gamira care report", 14, y);
    y += 10;
    doc.setFontSize(12);
    doc.text(`${selected ? selected.name : "Whole family"} · last ${days} days`, 14, y);
    y += 8;
    doc.text(`Generated ${new Date().toLocaleString()}`, 14, y);
    y += 6;
    doc.line(14, y, 196, y);
    y += 10;

    doc.setFontSize(13);
    doc.text("Doses", 14, y);
    y += 8;
    doc.setFontSize(11);
    doc.text(`${taken} confirmed, ${skipped} skipped, ${missed} missed`, 18, y);
    y += 12;

    doc.setFontSize(13);
    doc.text("Medicines", 14, y);
    y += 8;
    doc.setFontSize(11);
    if (scopedMeds.length === 0) {
      doc.text("None recorded", 18, y);
      y += 7;
    } else {
      scopedMeds.forEach((m) => {
        doc.text(`- ${m.name}${m.dosage ? ` (${m.dosage})` : ""} — ${m.frequency}`, 18, y);
        y += 7;
      });
    }
    y += 5;

    doc.setFontSize(13);
    doc.text("Summary", 14, y);
    y += 8;
    doc.setFontSize(11);
    summary.lines.forEach((line) => {
      doc.splitTextToSize(line, 175).forEach((wrapped) => {
        doc.text(wrapped, 18, y);
        y += 7;
      });
    });
    y += 4;
    doc.setFontSize(9);
    doc.splitTextToSize(summary.disclaimer, 175).forEach((wrapped) => {
      doc.text(wrapped, 14, y);
      y += 5;
    });

    const fileName = `gamira-report-${selected ? selected.name.replace(/\s+/g, "-").toLowerCase() : "family"}.pdf`;

    if (Capacitor.isNativePlatform()) {
      // A browser-style download doesn't work inside a WebView — there's no
      // Downloads folder to drop it into. Write it to the app's cache and
      // hand it to the native share sheet instead, same as any other native
      // app's "export" action.
      const base64 = doc.output("datauristring").split(",")[1];
      await Filesystem.writeFile({ path: fileName, data: base64, directory: Directory.Cache });
      const { uri } = await Filesystem.getUri({ path: fileName, directory: Directory.Cache });
      await Share.share({ title: "Gamira Report", url: uri });
      return;
    }

    doc.save(fileName);
  };

  return (
    <div>
      <PageHeader title="Reports" subtitle="Counted from recorded care" backTo="/more" />

      {error && (
        <div className="mb-4 rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      {members.length === 0 ? (
        <EmptyState
          icon={FileBarChart}
          title="Nothing to report yet"
          description="Add the person you care for to build a report."
          actionLabel="Add Member"
          onAction={() => navigate("/add-member")}
        />
      ) : (
        <>
          <MemberSelector
            members={members}
            value={selMember}
            allowAll
            onChange={(id) => {
              const idx = memberItems.findIndex((m) => m.id === id);
              const cur = memberItems.findIndex((m) => m.id === selMember);
              setDir(idx > cur ? -1 : 1);
              setSelMember(id);
            }}
          />

          <AnimatePresence mode="wait" custom={dir}>
            <motion.div
              key={`${selMember}-${days}`}
              custom={dir}
              variants={variants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.28, ease: "easeOut" }}
              {...swipe}
            >
              <div className="flex gap-2 mt-4">
                {PERIODS.map((p) => (
                  <button
                    key={p.days}
                    onClick={() => setDays(p.days)}
                    className={`px-4 py-2 rounded-full text-[13px] font-semibold ${
                      days === p.days
                        ? "bg-primary text-white"
                        : "bg-white border border-border text-muted-foreground"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>

              <div className="grid grid-cols-2 gap-3 mt-4">
                <Stat label="Confirmed" value={`${taken}`} />
                <Stat label="Skipped" value={`${skipped}`} />
                <Stat label="Missed" value={`${missed}`} />
                <Stat label="Confirmed rate" value={resolved ? `${confirmed}%` : "—"} />
              </div>

              <div className="mt-4 p-4 bg-white rounded-[20px] shadow-soft border border-border/50">
                <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                  Summary
                </p>
                <ul className="space-y-2">
                  {summary.lines.map((line, i) => (
                    <li key={i} className="text-[13px] text-foreground leading-relaxed">
                      {line}
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-[11px] text-muted-foreground leading-relaxed">
                  {summary.disclaimer}
                </p>
              </div>

              <button
                onClick={exportPDF}
                className="mt-4 w-full py-3.5 rounded-2xl bg-white border border-border text-[14px] font-semibold flex items-center justify-center gap-2"
              >
                <Download className="w-4 h-4" /> Download PDF
              </button>
            </motion.div>
          </AnimatePresence>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="p-4 bg-white rounded-[18px] shadow-soft border border-border/50">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="text-xl font-bold text-foreground mt-1">{value}</p>
    </div>
  );
}
