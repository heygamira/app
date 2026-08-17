import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Pill, Plus } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { useSwipeNav } from "@/lib/useSwipeNav";
import { medicinesApi, toMember } from "@/api/dashboardData";
import MemberSelector from "@/components/gamira/MemberSelector";
import MedicineCard from "@/components/gamira/MedicineCard";
import EmptyState from "@/components/gamira/EmptyState";

export default function Medication() {
  const navigate = useNavigate();
  const { seniors } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);
  const memberKey = members.map((m) => m.id).join(",");

  const [medicines, setMedicines] = useState([]);
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
    try {
      setMedicines(await medicinesApi.listForMembers(members));
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
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

  const visible =
    selMember === "all"
      ? medicines
      : medicines.filter((m) => m.family_member_id === selMember);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Medication</h1>
          <p className="text-[13px] text-muted-foreground mt-0.5">Medicines and their dose times</p>
        </div>
        <button
          onClick={() => navigate("/add-medicine")}
          className="w-11 h-11 rounded-2xl bg-primary flex items-center justify-center shadow-float active:scale-95 transition-transform"
          aria-label="Add medicine"
        >
          <Plus className="w-5 h-5 text-white" strokeWidth={2.25} />
        </button>
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
      ) : visible.length === 0 ? (
        <div {...swipe}>
          <EmptyState
            icon={Pill}
            title="No medicines yet"
            description="Add a medicine with its dose times and the doses appear on the Reminders screen."
            actionLabel="Add Medicine"
            onAction={() => navigate("/add-medicine")}
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
            className="space-y-2.5"
            {...swipe}
          >
            {visible.map((m) => (
              <MedicineCard
                key={m.id}
                medicine={m}
                onClick={() => navigate(`/medicine/${m.id}?member=${m.family_member_id}`)}
              />
            ))}
          </motion.div>
        </AnimatePresence>
      )}
    </div>
  );
}
