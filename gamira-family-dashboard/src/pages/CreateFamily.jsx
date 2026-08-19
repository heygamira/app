import React, { useState } from "react";
import { Users, LogOut, Loader2 } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { families as familiesApi } from "@/api/gamiraClient";
import AuthLayout from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Shown instead of the app when a signed-in user belongs to no family yet —
// either their first time here, or an invitation link is what they actually
// needed (an owner can point them at one instead of this).
export default function CreateFamily() {
  const { user, checkUserAuth, logout } = useAuth();
  const [name, setName] = useState(user?.name ? `${user.name.split(" ")[0]}'s family` : "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setError("");
    try {
      await familiesApi.create(name.trim());
      await checkUserAuth();
    } catch (err) {
      setError(err.message || "Could not create your family.");
      setSaving(false);
    }
  };

  return (
    <AuthLayout
      icon={Users}
      title="Welcome to Gamira"
      subtitle="Create your family to start coordinating care"
      footer={
        <button
          onClick={() => logout()}
          className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors"
        >
          <LogOut className="w-3.5 h-3.5" /> Sign in as someone else
        </button>
      }
    >
      {error && (
        <div className="mb-4 p-3 rounded-lg bg-destructive/10 text-destructive text-sm">
          {error}
        </div>
      )}
      <form className="space-y-4" onSubmit={submit}>
        <div className="space-y-2">
          <Label htmlFor="family-name">Family name</Label>
          <Input
            id="family-name"
            autoFocus
            placeholder="e.g. The Sharma family"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            You'll be its owner, and can invite other family members or
            caregivers once it exists.
          </p>
        </div>
        <Button type="submit" className="w-full h-12 font-medium" disabled={saving || !name.trim()}>
          {saving ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Creating…
            </>
          ) : (
            "Create family"
          )}
        </Button>
      </form>
      <p className="mt-4 text-center text-xs text-muted-foreground">
        Invited to join an existing family instead? Open the invitation link
        you were sent — you don't need to create one here.
      </p>
    </AuthLayout>
  );
}
