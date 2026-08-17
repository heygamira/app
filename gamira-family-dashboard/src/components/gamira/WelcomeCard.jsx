import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import {
  Sparkles,
  Plus,
  Sun,
  CloudSun,
  CloudFog,
  CloudRain,
  CloudSnow,
  CloudLightning,
  Moon,
} from "lucide-react";

const condMap = (code) => {
  if (code == null) return { icon: CloudSun, label: "—" };
  if (code === 0) return { icon: Sun, label: "Clear" };
  if (code <= 3) return { icon: CloudSun, label: "Partly Cloudy" };
  if (code <= 48) return { icon: CloudFog, label: "Fog" };
  if (code <= 67) return { icon: CloudRain, label: "Rain" };
  if (code <= 77) return { icon: CloudSnow, label: "Snow" };
  if (code <= 82) return { icon: CloudRain, label: "Showers" };
  return { icon: CloudLightning, label: "Storm" };
};

const timeOfDay = () => {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return { key: "morning", label: "Good Morning" };
  if (h >= 12 && h < 17) return { key: "afternoon", label: "Good Afternoon" };
  if (h >= 17 && h < 20) return { key: "evening", label: "Good Evening" };
  return { key: "night", label: "Good Night" };
};

export default function WelcomeCard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [weather, setWeather] = useState(null);

  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const { latitude, longitude } = pos.coords;
        try {
          const [w, g] = await Promise.all([
            fetch(
              `https://api.open-meteo.com/v1/forecast?latitude=${latitude}&longitude=${longitude}&current=temperature_2m,weather_code`
            ).then((r) => r.json()),
            fetch(
              `https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${latitude}&longitude=${longitude}&localityLanguage=en`
            ).then((r) => r.json()),
          ]);
          setWeather({
            temp: Math.round(w.current?.temperature_2m),
            code: w.current?.weather_code,
            place: g.city || g.locality || g.principalSubdivision || "Your area",
          });
        } catch (e) {
          /* keep null */
        }
      },
      () => {},
      { enableHighAccuracy: false, timeout: 8000 }
    );
  }, []);

  const tod = timeOfDay();
  const name = user?.name || user?.full_name;
  const cond = condMap(weather?.code);
  const code = weather?.code;
  const iconByTime = tod.key === "night" ? Moon : tod.key === "morning" || tod.key === "afternoon" ? Sun : CloudSun;
  let CondIcon = iconByTime;
  if (code != null) {
    if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) CondIcon = CloudRain;
    else if (code >= 71 && code <= 77) CondIcon = CloudSnow;
    else if (code >= 95) CondIcon = CloudLightning;
  }
  const iconColor =
    CondIcon === Moon ? "text-amber-300"
      : CondIcon === CloudRain ? "text-sky-500"
        : CondIcon === CloudSnow ? "text-sky-300"
          : "text-amber-500";

  return (
    <div className={`relative overflow-hidden rounded-[24px] shadow-card gradient-${tod.key}`}>
      <div className="absolute -right-8 -top-10 w-40 h-40 rounded-full bg-white/30 blur-2xl" />
      <div className="absolute right-20 bottom-0 w-24 h-24 rounded-full bg-primary/10 blur-xl" />

      <div className="relative flex items-stretch justify-between gap-4 p-6">
        {/* Left — Greeting + Buttons */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-primary/80">
            {tod.label}
            {name ? `, ${name}` : ""}
          </p>
          <h2 className="mt-1 text-xl font-bold leading-tight text-foreground">
            Your family is doing well today.
          </h2>
          <p className="mt-1.5 text-[13px] text-muted-foreground leading-relaxed">
            Stay connected. We've got you covered.
          </p>

          <div className="mt-4 flex flex-wrap gap-2.5">
            <button
              onClick={() => navigate("/ai-summary")}
              className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-2xl bg-primary text-primary-foreground text-[13px] font-semibold shadow-float hover:bg-primary/90 transition-colors active:scale-[0.98]"
            >
              <Sparkles className="w-4 h-4" strokeWidth={2} />
              AI Summary
            </button>
            <button
              onClick={() => navigate("/add-reminder")}
              className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-2xl bg-white text-foreground text-[13px] font-semibold border border-border shadow-soft hover:bg-secondary/50 transition-colors active:scale-[0.98]"
            >
              <Plus className="w-4 h-4" strokeWidth={2} />
              Add Reminder
            </button>
          </div>
        </div>

        {/* Right — Weather */}
        <div className="flex flex-col items-center justify-center text-center w-[92px] shrink-0">
          <div className="w-16 h-16 flex items-center justify-center">
            <CondIcon className={`w-14 h-14 ${iconColor}`} strokeWidth={1.25} />
          </div>
          <p className="text-2xl font-bold text-foreground leading-none mt-1">
            {weather ? `${weather.temp}°` : "—"}
          </p>
          <p className="text-[11px] font-medium text-muted-foreground mt-1">{cond.label}</p>
          <p className="text-[10px] text-muted-foreground/80 mt-0.5 text-center leading-tight max-w-[92px] truncate">
            {weather?.place || "Locating..."}
          </p>
        </div>
      </div>
    </div>
  );
}