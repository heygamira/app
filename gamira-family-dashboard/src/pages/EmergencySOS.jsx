import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Phone, Plus, ShieldAlert, Trash2, User } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { contactsApi, toMember } from "@/api/dashboardData";
import PageHeader from "@/components/gamira/PageHeader";
import EmptyState from "@/components/gamira/EmptyState";
import MemberSelector from "@/components/gamira/MemberSelector";

export default function EmergencySOS() {
  const navigate = useNavigate();
  const { seniors, activeSeniorId, selectSenior } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);

  const [contacts, setContacts] = useState([]);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [relationship, setRelationship] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const memberId = activeSeniorId || members[0]?.id;
  const selected = members.find((m) => m.id === memberId) || null;

  const load = useCallback(async () => {
    if (!memberId) return;
    try {
      setContacts(await contactsApi.list(memberId));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, [memberId]);

  useEffect(() => {
    load();
  }, [load]);

  const addContact = async () => {
    if (!name.trim() || !phone.trim() || !memberId) return;
    setSaving(true);
    try {
      await contactsApi.create(memberId, {
        name: name.trim(),
        phone: phone.trim(),
        relationship,
        isPrimary: contacts.length === 0,
      });
      setName("");
      setPhone("");
      setRelationship("");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (contactId) => {
    try {
      await contactsApi.remove(contactId);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const primary = contacts.find((c) => c.is_primary) || contacts[0] || null;

  return (
    <div>
      <PageHeader title="Emergency" subtitle="Who to call, and how fast" backTo="/more" />

      {/* An SOS button that only writes a database row would be the most
          dangerous thing in this app: someone would press it in a real
          emergency and wait. Until Gamira can actually notify anyone, this
          screen dials a person directly. */}
      <div className="p-5 rounded-[24px] bg-destructive/5 border border-destructive/20">
        <div className="flex items-start gap-3">
          <ShieldAlert className="w-6 h-6 text-destructive shrink-0" />
          <div>
            <p className="text-[14px] font-semibold text-foreground">
              Gamira does not contact emergency services
            </p>
            <p className="text-[12px] text-muted-foreground mt-1 leading-relaxed">
              In an emergency, call your local emergency number. The button below
              dials the primary contact saved on this phone — it does not send an
              alert, and nobody is notified in the background.
            </p>
          </div>
        </div>

        {primary ? (
          <a
            href={`tel:${primary.phone}`}
            className="mt-4 w-full flex items-center justify-center gap-2 py-4 rounded-2xl bg-destructive text-white text-[16px] font-bold shadow-float active:scale-[0.99] transition-transform"
          >
            <Phone className="w-5 h-5" /> Call {primary.name}
          </a>
        ) : (
          <p className="mt-4 text-[12px] font-medium text-muted-foreground text-center">
            Add a contact below to enable one-tap dialling.
          </p>
        )}
      </div>

      {error && (
        <div className="mt-4 rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      {members.length > 1 && (
        <div className="mt-5">
          <MemberSelector members={members} value={memberId} onChange={selectSenior} />
        </div>
      )}

      <section className="mt-5">
        <h3 className="text-base font-bold text-foreground mb-3">
          Contacts{selected ? ` for ${selected.name}` : ""}
        </h3>

        {contacts.length === 0 ? (
          <EmptyState icon={Phone} title="No contacts yet" description="Add the person to call first." />
        ) : (
          <div className="space-y-2.5">
            {contacts.map((c) => (
              <div
                key={c.id}
                className="flex items-center gap-3 p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50"
              >
                <a
                  href={`tel:${c.phone}`}
                  className="w-10 h-10 rounded-2xl bg-destructive/10 flex items-center justify-center shrink-0"
                  aria-label={`Call ${c.name}`}
                >
                  <Phone className="w-5 h-5 text-destructive" />
                </a>
                <div className="flex-1 min-w-0">
                  <p className="text-[13px] font-semibold text-foreground">
                    {c.name}
                    {c.is_primary && <span className="ml-2 text-[10px] text-primary">Primary</span>}
                  </p>
                  <p className="text-[11px] text-muted-foreground truncate">
                    {[c.relationship_label, c.phone].filter(Boolean).join(" · ")}
                  </p>
                </div>
                <button onClick={() => remove(c.id)} aria-label={`Remove ${c.name}`}>
                  <Trash2 className="w-4 h-4 text-muted-foreground" />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="mt-3 p-4 bg-white rounded-[18px] shadow-soft border border-border/50 space-y-2">
          <div className="flex gap-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name"
              className="flex-1 px-3 py-2.5 rounded-xl bg-white border border-border text-[13px]"
            />
            <input
              value={relationship}
              onChange={(e) => setRelationship(e.target.value)}
              placeholder="Relation"
              className="w-28 px-3 py-2.5 rounded-xl bg-white border border-border text-[13px]"
            />
          </div>
          <div className="flex gap-2">
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              inputMode="tel"
              placeholder="Phone"
              className="flex-1 px-3 py-2.5 rounded-xl bg-white border border-border text-[13px]"
            />
            <button
              onClick={addContact}
              disabled={saving || !name.trim() || !phone.trim() || !memberId}
              className="px-4 rounded-xl bg-primary text-primary-foreground text-[13px] font-semibold flex items-center gap-1 disabled:opacity-50"
            >
              <Plus className="w-4 h-4" /> Add
            </button>
          </div>
        </div>
      </section>

      <section className="mt-5">
        <h3 className="text-base font-bold text-foreground mb-3">Medical ID</h3>
        {members.length === 0 ? (
          <EmptyState
            icon={User}
            title="No one added yet"
            description="A medical ID needs a person on file."
            actionLabel="Add Member"
            onAction={() => navigate("/add-member")}
          />
        ) : (
          <div className="space-y-2.5">
            {members.map((m) => (
              <div key={m.id} className="p-4 bg-white rounded-[18px] shadow-soft border border-border/50">
                <p className="text-[13px] font-semibold text-foreground">{m.name}</p>
                <p className="text-[11px] text-muted-foreground">
                  Blood: {m.blood_group || "not recorded"}
                  {m.age != null ? ` · Age ${m.age}` : ""}
                </p>
                {m.conditions.length > 0 && (
                  <p className="text-[11px] text-muted-foreground">Conditions: {m.conditions.join(", ")}</p>
                )}
                {m.allergies.length > 0 && (
                  <p className="text-[11px] text-muted-foreground">Allergies: {m.allergies.join(", ")}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
