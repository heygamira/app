import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LogOut, UserCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import AuthLayout from "@/components/AuthLayout";
import { useAuth } from "@/lib/AuthContext";

// Extracts a token whether the person pasted the raw token or the full link
// a family member sent them (https://.../invite/<token>).
function extractToken(input) {
  const trimmed = input.trim();
  if (!trimmed) return "";
  const match = trimmed.match(/\/invite\/([^/?#\s]+)/);
  return match ? decodeURIComponent(match[1]) : trimmed;
}

// Shown to a signed-in user whose account is not yet linked to a cared-for
// person's profile. Being signed in is not the same as being set up: the
// backend has no way to know which senior this device belongs to until an
// invitation says so.
export default function LinkAccount() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [value, setValue] = useState("");

  const go = (event) => {
    event.preventDefault();
    const token = extractToken(value);
    if (token) navigate(`/invite/${encodeURIComponent(token)}`);
  };

  return (
    <AuthLayout
      icon={UserCheck}
      title="Almost there"
      subtitle={
        user?.name
          ? `${user.name}, your account isn't linked to a person's care profile yet.`
          : "Your account isn't linked to a person's care profile yet."
      }
      footer={
        <button
          onClick={() => logout()}
          className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors"
        >
          <LogOut className="w-3.5 h-3.5" /> Sign in as someone else
        </button>
      }
    >
      <p className="text-sm text-muted-foreground">
        Ask the family member who set up Gamira for an invitation link, then
        paste it below.
      </p>
      <form className="mt-4 space-y-3" onSubmit={go}>
        <Label htmlFor="invite-link">Invitation link</Label>
        <Input
          id="invite-link"
          placeholder="Paste the link you were sent"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button type="submit" className="w-full h-12 font-medium" disabled={!value.trim()}>
          Continue
        </Button>
      </form>
    </AuthLayout>
  );
}
