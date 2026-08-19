import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Heart } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "@/lib/AuthContext";
import { useSwipeNav } from "@/lib/useSwipeNav";
import { usePoll } from "@/lib/usePoll";
import { healthApi, toMember } from "@/api/dashboardData";

// Slower than the old 5s default now that an SOS or a device flag no longer
// depends on this poll at all (see useAlerts's live event stream) — this
// screen's own job is a trend chart, not urgent detection, and 30s of staleness
// on a reading is not something a family member watching it will notice.
const HEALTH_POLL_MS = 30_000;
import EmptyState from "@/components/gamira/EmptyState";
import MemberSelector from "@/components/gamira/MemberSelector";
import MemberHealthSection from "@/components/gamira/MemberHealthSection";

export default function Health() {
  const navigate = useNavigate();
  const { seniors, activeSeniorId, selectSenior } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);

  const [readings, setReadings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dir, setDir] = useState(0);

  const selected = members.find((m) => m.id === activeSeniorId) || members[0] || null;

  // Only the selected senior, not every member of the family: this used to
  // fetch all of them (healthApi.listForMembers) on every poll tick
  // regardless of which one was actually being viewed — for 4 seniors, 4
  // requests every 30s and up to 800 rows transferred for one visible chart.
  const load = useCallback(async () => {
    if (!selected) {
      setReadings([]);
      setLoading(false);
      return;
    }
    try {
      setReadings(await healthApi.list(selected.id, selected.name, { limit: 200 }));
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => {
    load();
  }, [load]);

  // Readings arrive from a paired watch between renders, so this screen keeps
  // reading while it is open.
  usePoll(load, HEALTH_POLL_MS);

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

  return (
    <div className="space-y-5 select-none" {...swipe}>
      <div>
        <h1 className="text-2xl font-bold text-foreground">Health</h1>
        <p className="text-[13px] text-muted-foreground mt-0.5">
          Readings recorded by your family, newest first
        </p>
      </div>

      {error && (
        <div className="rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="w-8 h-8 border-4 border-secondary border-t-primary rounded-full animate-spin"></div>
        </div>
      ) : members.length === 0 ? (
        <EmptyState
          icon={Heart}
          title="No one added yet"
          description="Add the person you care for to start recording readings."
          actionLabel="Add Member"
          onAction={() => navigate("/add-member")}
        />
      ) : (
        <>
          <MemberSelector members={members} value={selected?.id} onChange={selectSenior} />
          <AnimatePresence mode="wait" custom={dir}>
            {selected && (
              <motion.div
                key={selected.id}
                custom={dir}
                variants={variants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: 0.28, ease: "easeOut" }}
              >
                <MemberHealthSection
                  member={selected}
                  readings={readings}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}
    </div>
  );
}
