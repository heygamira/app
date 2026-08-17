import React from "react";
import { useNavigate } from "react-router-dom";
import { MessageCircleQuestion } from "lucide-react";

// The voice companion belongs to the Parent App and is not built yet. This
// card no longer offers one; it opens the screen that answers from records.
export default function VoiceAssistant() {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate("/ai-assistant")}
      className="w-full flex items-center gap-3 p-4 rounded-[20px] gradient-gamira text-white shadow-float active:scale-[0.99] transition-transform"
    >
      <div className="w-11 h-11 rounded-2xl bg-white/20 flex items-center justify-center shrink-0">
        <MessageCircleQuestion className="w-5 h-5 text-white" strokeWidth={2} />
      </div>
      <div className="flex-1 text-left">
        <p className="text-[14px] font-semibold">Ask about today</p>
        <p className="text-[12px] text-white/80">Answered from your family&apos;s records</p>
      </div>
    </button>
  );
}
