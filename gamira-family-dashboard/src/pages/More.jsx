import React from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Brain,
  ChevronRight,
  Clock,
  CreditCard,
  FileText,
  Home,
  Info,
  LifeBuoy,
  Lock,
  LogOut,
  MessageCircle,
  Pill,
  Settings,
  ShieldAlert,
  Sparkles,
  Users,
} from "lucide-react";
import { useAuth } from "@/lib/AuthContext";

const rowMotion = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 320, damping: 26 } },
};

const MODULES = [
  { label: "Medication", path: "/medication", icon: Pill },
  { label: "Timeline", path: "/timeline", icon: Clock },
  { label: "Ask about today", path: "/ai-assistant", icon: Brain },
  // Where the family can read — and remove — what Gamira has picked up.
  { label: "What Gamira remembers", path: "/gamira-memory", icon: Sparkles },
  // The reasoning behind a "might like a call" nudge. Without it the
  // notification asks a family to trust a judgement they cannot inspect.
  { label: "What Gamira noticed", path: "/gamira-noticed", icon: MessageCircle },
  { label: "Reports", path: "/reports", icon: FileText },
  { label: "Emergency", path: "/emergency", icon: ShieldAlert },
  { label: "Smart Home", path: "/smart-home", icon: Home },
];

const ACCOUNT = [
  { label: "Family access", path: "/family-access", icon: Users },
  { label: "Settings", path: "/settings", icon: Settings },
  { label: "Privacy", path: "/privacy", icon: Lock },
  { label: "Plans", path: "/subscription", icon: CreditCard },
  { label: "Support", path: "/support", icon: LifeBuoy },
];

export default function More() {
  const navigate = useNavigate();
  const { logout } = useAuth();

  const Group = ({ title, list }) => (
    <div>
      <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1">
        {title}
      </p>
      <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50 overflow-hidden">
        {list.map((item) => {
          const Icon = item.icon;
          return (
            <motion.button
              key={item.label}
              variants={rowMotion}
              initial="hidden"
              animate="show"
              whileHover={{ x: 2 }}
              whileTap={{ scale: 0.985 }}
              onClick={() => navigate(item.path)}
              className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-secondary/30 transition-colors"
            >
              <div className="w-9 h-9 rounded-xl bg-secondary flex items-center justify-center">
                <Icon className="w-[18px] h-[18px] text-foreground" strokeWidth={2} />
              </div>
              <span className="flex-1 text-left text-[14px] font-medium text-foreground">{item.label}</span>
              <ChevronRight className="w-4 h-4 text-muted-foreground" strokeWidth={2} />
            </motion.button>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">More</h1>
        <p className="text-[13px] text-muted-foreground mt-0.5">Tools, settings and account</p>
      </div>

      <Group title="Care" list={MODULES} />
      <Group title="Account" list={ACCOUNT} />

      <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50 overflow-hidden">
        <motion.button
          variants={rowMotion}
          initial="hidden"
          animate="show"
          whileHover={{ x: 2 }}
          whileTap={{ scale: 0.985 }}
          onClick={() => navigate("/about")}
          className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-secondary/30 transition-colors"
        >
          <div className="w-9 h-9 rounded-xl bg-secondary flex items-center justify-center">
            <Info className="w-[18px] h-[18px] text-foreground" strokeWidth={2} />
          </div>
          <span className="flex-1 text-left text-[14px] font-medium text-foreground">About Gamira</span>
          <ChevronRight className="w-4 h-4 text-muted-foreground" strokeWidth={2} />
        </motion.button>

        <motion.button
          variants={rowMotion}
          initial="hidden"
          animate="show"
          whileHover={{ x: 2 }}
          whileTap={{ scale: 0.985 }}
          onClick={() => logout()}
          className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-destructive/5 transition-colors"
        >
          <div className="w-9 h-9 rounded-xl bg-destructive/10 flex items-center justify-center">
            <LogOut className="w-[18px] h-[18px] text-destructive" strokeWidth={2} />
          </div>
          <span className="flex-1 text-left text-[14px] font-medium text-destructive">Sign out</span>
        </motion.button>
      </div>
    </div>
  );
}
