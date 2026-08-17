import React, { useCallback, useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Clock } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { useSwipeNav } from "@/lib/useSwipeNav";
import { timelineApi, toMember } from "@/api/dashboardData";
import MemberSelector from "@/components/gamira/MemberSelector";
import EmptyState from "@/components/gamira/EmptyState";
import TimelineItem from "@/components/gamira/TimelineItem";

export default function Timeline() {
  const { seniors } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);
  const memberKey = members.map((m) => m.id).join(",");

  const [events, setEvents] = useState([]);
  const [selMember, setSelMember] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dir, setDir] = useState(0);

  const memberItems = [{ id: "all" }, ...members];

  const load = useCallback(async () => {
    if (!members.length) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const scope =
        selMember === "all" ? members : members.filter((m) => m.id === selMember);
      setEvents(await timelineApi.listForMembers(scope, { limit: 100 }));
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memberKey, selMember]);

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

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Family Timeline</h1>
        <p className="text-[13px] text-muted-foreground mt-0.5">
          Every recorded action, newest first
        </p>
      </div>

      {members.length > 0 && (
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
      )}

      {error && (
        <div className="rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-2.5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 rounded-[18px] bg-white/60 animate-pulse" />
          ))}
        </div>
      ) : events.length === 0 ? (
        <div {...swipe}>
          <EmptyState
            icon={Clock}
            title="No events yet"
            description="Confirming a dose or adding a reading writes an entry here."
          />
        </div>
      ) : (
        <AnimatePresence mode="wait" custom={dir}>
          <motion.div
            key={selMember}
            custom={dir}
            variants={variants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ duration: 0.28, ease: "easeOut" }}
            className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50"
            {...swipe}
          >
            {events.map((event) => (
              <TimelineItem key={event.id} event={event} />
            ))}
          </motion.div>
        </AnimatePresence>
      )}
    </div>
  );
}
