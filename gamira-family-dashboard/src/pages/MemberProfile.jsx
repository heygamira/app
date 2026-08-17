import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  Calendar,
  Clock,
  Droplet,
  Heart,
  Pencil,
  Phone,
  Pill,
  StickyNote,
  Trash2,
} from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import {
  appointmentsApi,
  contactsApi,
  dosesApi,
  healthApi,
  medicinesApi,
  membersApi,
  notesApi,
  timelineApi,
  toMember,
} from "@/api/dashboardData";
import { buildCareSummary } from "@/lib/careSummary";
import PageHeader from "@/components/gamira/PageHeader";
import EmptyState from "@/components/gamira/EmptyState";
import { careStatusFor, careStatusMeta, initialOf } from "@/lib/careStatus";

const TABS = ["Overview", "Health", "Medicines", "Appointments", "Timeline", "Emergency", "Notes", "Summary"];

export default function MemberProfile() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { seniors, activeFamily, checkUserAuth } = useAuth();

  const member = useMemo(() => seniors.map(toMember).find((m) => m.id === id) || null, [seniors, id]);

  const [medicines, setMedicines] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [events, setEvents] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [readings, setReadings] = useState([]);
  const [notes, setNotes] = useState([]);
  const [doses, setDoses] = useState([]);
  const [tab, setTab] = useState("Overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [meds, appts, timeline, cts, reads, dose] = await Promise.all([
        medicinesApi.list(id, member?.name),
        appointmentsApi.list(id),
        timelineApi.list(id, member?.name, { limit: 50 }),
        contactsApi.list(id),
        healthApi.list(id, member?.name, { limit: 100 }),
        dosesApi.today(id),
      ]);
      setMedicines(meds);
      setAppointments(appts);
      setEvents(timeline);
      setContacts(cts);
      setReadings(reads);
      setDoses(dose);
      if (activeFamily) setNotes(await notesApi.list(activeFamily.id, id).catch(() => []));
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, member?.name, activeFamily?.id]);

  useEffect(() => {
    load();
  }, [load]);

  const remove = async () => {
    try {
      await membersApi.remove(id);
      await checkUserAuth();
      navigate("/family");
    } catch (err) {
      setError(err.message);
    }
  };

  const summary = useMemo(
    () => buildCareSummary({ member, meds: medicines, records: readings, events, days: 7 }),
    [member, medicines, readings, events],
  );

  if (loading && !member) {
    return (
      <div className="h-64 flex items-center justify-center">
        <div className="w-8 h-8 border-4 border-secondary border-t-primary rounded-full animate-spin" />
      </div>
    );
  }

  if (!member) {
    return (
      <div>
        <PageHeader title="Member" backTo="/family" />
        <p className="text-center text-muted-foreground py-20">
          {error || "This person is not in one of your families."}
        </p>
      </div>
    );
  }

  const status = careStatusMeta(careStatusFor(doses));

  return (
    <div>
      <PageHeader
        title={member.name}
        subtitle={[member.role, member.age ? `Age ${member.age}` : null].filter(Boolean).join(" · ")}
        backTo="/family"
      />

      {error && (
        <div className="mb-4 rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      <div className="flex flex-col items-center text-center p-5 bg-white rounded-[24px] shadow-card border border-border/50">
        <div className="w-20 h-20 rounded-full overflow-hidden ring-4 ring-secondary/60 bg-secondary flex items-center justify-center">
          {member.photo_url ? (
            <img src={member.photo_url} alt={member.name} className="w-full h-full object-cover" />
          ) : (
            <span className="text-[26px] font-bold text-muted-foreground">{initialOf(member.name)}</span>
          )}
        </div>
        <h2 className="mt-3 text-lg font-bold text-foreground">{member.name}</h2>
        <p className="text-[13px] text-muted-foreground">{member.role || "Family"}</p>
        <span className={`mt-2 px-3 py-1 rounded-full text-[11px] font-semibold ${status.pill}`}>
          {status.label}
        </span>

        <div className="grid grid-cols-3 gap-2 w-full mt-4">
          <Stat label="Blood" value={member.blood_group || "—"} />
          <Stat label="Age" value={member.age != null ? String(member.age) : "—"} />
          <Stat label="Timezone" value={(member.timezone || "").split("/").pop() || "—"} />
        </div>

        <div className="grid grid-cols-2 gap-2 w-full mt-3">
          <button
            onClick={() => navigate(`/member/${id}/edit`)}
            className="flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-secondary text-[12px] font-semibold text-foreground"
          >
            <Pencil className="w-4 h-4" /> Edit
          </button>
          <button
            onClick={remove}
            className="flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-destructive/10 text-[12px] font-semibold text-destructive"
          >
            <Trash2 className="w-4 h-4" /> Archive
          </button>
        </div>
      </div>

      <div className="flex gap-2 mt-5 overflow-x-auto no-scrollbar">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-full text-[13px] font-semibold whitespace-nowrap ${
              tab === t ? "bg-primary text-white" : "bg-white text-muted-foreground border border-border"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {tab === "Overview" && (
          <div className="space-y-2.5">
            <InfoRow icon={Droplet} title="Blood group" value={member.blood_group || "Not recorded"} />
            <InfoRow icon={Heart} title="Conditions" value={member.conditions.join(", ") || "None recorded"} />
            <InfoRow icon={Pill} title="Allergies" value={member.allergies.join(", ") || "None recorded"} />
            <InfoRow icon={Phone} title="Phone" value={member.phone || "Not recorded"} />
            <InfoRow icon={Clock} title="Notes" value={member.notes || "No notes"} />
          </div>
        )}

        {tab === "Health" &&
          (readings.length === 0 ? (
            <EmptyState
              icon={Heart}
              title="No readings recorded"
              description="Add one from the Health screen."
              actionLabel="Go to Health"
              onAction={() => navigate("/health")}
            />
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {readings.slice(0, 8).map((r) => (
                <div key={r.id} className="p-4 bg-white rounded-[18px] shadow-soft border border-border/50">
                  <p className="text-[11px] text-muted-foreground">{r.label}</p>
                  <p className="text-lg font-bold text-foreground mt-1">
                    {r.value} {r.unit}
                  </p>
                  <p className="text-[10px] text-muted-foreground/80 mt-1">
                    {new Date(r.recorded_at).toLocaleDateString()}
                  </p>
                </div>
              ))}
            </div>
          ))}

        {tab === "Medicines" &&
          (medicines.length === 0 ? (
            <EmptyState
              icon={Pill}
              title="No medicines"
              description="Add a medicine and its dose times."
              actionLabel="Add Medicine"
              onAction={() => navigate(`/add-medicine?member=${id}`)}
            />
          ) : (
            <div className="space-y-2.5">
              {medicines.map((m) => (
                <Link
                  key={m.id}
                  to={`/medicine/${m.id}?member=${id}`}
                  className="flex items-center gap-3 p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50"
                >
                  <div className="w-10 h-10 rounded-2xl bg-primary/10 flex items-center justify-center shrink-0">
                    <Pill className="w-5 h-5 text-primary" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-[13px] font-semibold text-foreground truncate">{m.name}</p>
                    <p className="text-[11px] text-muted-foreground truncate">
                      {[m.dosage, m.frequency].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                </Link>
              ))}
            </div>
          ))}

        {tab === "Appointments" &&
          (appointments.length === 0 ? (
            <EmptyState icon={Calendar} title="No appointments" description="Scheduled visits appear here." />
          ) : (
            <div className="space-y-2.5">
              {appointments.map((a) => (
                <div key={a.id} className="p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50">
                  <p className="text-[13px] font-semibold text-foreground">{a.title}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {[a.clinician, a.location].filter(Boolean).join(" · ") || "No location recorded"}
                  </p>
                  <p className="text-[11px] text-primary mt-0.5">
                    {new Date(a.starts_at).toLocaleString()} · {a.status}
                  </p>
                </div>
              ))}
            </div>
          ))}

        {tab === "Timeline" &&
          (events.length === 0 ? (
            <EmptyState icon={Clock} title="No events" description="Recorded actions appear here." />
          ) : (
            <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50">
              {events.map((e) => (
                <div key={e.id} className="flex items-center gap-3 px-4 py-3">
                  <span className="w-2 h-2 rounded-full bg-primary shrink-0" />
                  <p className="flex-1 text-[13px] text-foreground truncate">{e.title}</p>
                  <span className="text-[11px] text-muted-foreground shrink-0">
                    {new Date(e.created_date).toLocaleDateString()}
                  </span>
                </div>
              ))}
            </div>
          ))}

        {tab === "Emergency" &&
          (contacts.length === 0 ? (
            <EmptyState
              icon={Phone}
              title="No emergency contacts"
              description="Add contacts on the Emergency screen."
              actionLabel="Open Emergency"
              onAction={() => navigate("/emergency")}
            />
          ) : (
            <div className="space-y-2.5">
              {contacts.map((c) => (
                <a
                  key={c.id}
                  href={`tel:${c.phone}`}
                  className="flex items-center gap-3 p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50"
                >
                  <div className="w-10 h-10 rounded-2xl bg-destructive/10 flex items-center justify-center shrink-0">
                    <Phone className="w-5 h-5 text-destructive" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-[13px] font-semibold text-foreground">
                      {c.name}
                      {c.is_primary && <span className="ml-2 text-[10px] text-primary">Primary</span>}
                    </p>
                    <p className="text-[11px] text-muted-foreground truncate">
                      {[c.relationship_label, c.phone].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                </a>
              ))}
            </div>
          ))}

        {tab === "Notes" &&
          (notes.length === 0 ? (
            <EmptyState icon={StickyNote} title="No notes" description="Family notes about this person appear here." />
          ) : (
            <div className="space-y-2.5">
              {notes.map((n) => (
                <div key={n.id} className="p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50">
                  <p className="text-[13px] font-semibold text-foreground">{n.title}</p>
                  <p className="text-[12px] text-muted-foreground mt-0.5 whitespace-pre-wrap">{n.content}</p>
                  <p className="text-[10px] text-muted-foreground/80 mt-1.5">
                    {new Date(n.created_at).toLocaleString()} · {n.category}
                  </p>
                </div>
              ))}
            </div>
          ))}

        {tab === "Summary" && (
          <div className="p-4 bg-white rounded-[20px] shadow-soft border border-border/50">
            <ul className="space-y-2">
              {summary.lines.map((line, i) => (
                <li key={i} className="text-[13px] text-foreground leading-relaxed">
                  {line}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[11px] text-muted-foreground leading-relaxed">{summary.disclaimer}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="flex flex-col items-center py-2.5 rounded-xl bg-secondary/40">
      <span className="text-[14px] font-bold text-foreground">{value}</span>
      <span className="text-[10px] text-muted-foreground">{label}</span>
    </div>
  );
}

function InfoRow({ icon: Icon, title, value }) {
  return (
    <div className="flex items-center gap-3 p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50">
      <div className="w-9 h-9 rounded-xl bg-secondary flex items-center justify-center shrink-0">
        <Icon className="w-[18px] h-[18px] text-foreground" strokeWidth={2} />
      </div>
      <div className="min-w-0">
        <p className="text-[11px] text-muted-foreground">{title}</p>
        <p className="text-[13px] font-medium text-foreground">{value}</p>
      </div>
    </div>
  );
}
