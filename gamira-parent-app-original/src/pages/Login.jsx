import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound, Loader2, LogIn } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import AuthLayout from "@/components/AuthLayout";
import { useAuth } from "@/lib/AuthContext";
import { safeReturnTo } from "@/lib/authReturnTo";

// The backend verifies a bearer token; it never sees a password. Until a
// Firebase project exists, the only way in is a development identity, which the
// backend accepts solely when it runs with AUTH_MODE=dev.
const DEV_IDENTITIES = [
  { subject: "sharma-senior", label: "Vikram Sharma — the cared-for person" },
  { subject: "sharma-owner", label: "Anjali Sharma — family owner" },
  { subject: "sharma-caregiver", label: "Rohan Sharma — caregiver" },
];

export default function Login() {
  const navigate = useNavigate();
  const { signIn } = useAuth();
  const returnTo = safeReturnTo();

  const [subject, setSubject] = useState(DEV_IDENTITIES[0].subject);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (bearer) => {
    setError("");
    setLoading(true);
    try {
      await signIn(bearer);
      navigate(returnTo, { replace: true });
    } catch (err) {
      setError(err.message || "Could not sign in.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      icon={LogIn}
      title="Sign in to Gamira"
      subtitle="Your session is verified by the Gamira backend"
    >
      {error && (
        <div className="mb-4 p-3 rounded-lg bg-destructive/10 text-destructive text-sm">
          {error}
        </div>
      )}

      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          submit(`dev:${subject}`);
        }}
      >
        <div className="space-y-2">
          <Label htmlFor="subject">Development identity</Label>
          <select
            id="subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="h-12 w-full rounded-md border border-border bg-background px-3 text-sm"
          >
            {DEV_IDENTITIES.map((identity) => (
              <option key={identity.subject} value={identity.subject}>
                {identity.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">
            These exist after running the backend seed. They only work while the
            backend runs with <code>AUTH_MODE=dev</code>, and are refused in
            staging and production.
          </p>
        </div>

        <Button type="submit" className="w-full h-12 font-medium" disabled={loading}>
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Signing in…
            </>
          ) : (
            "Continue"
          )}
        </Button>
      </form>

      <div className="relative my-6">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-border" />
        </div>
        <div className="relative flex justify-center text-xs uppercase">
          <span className="bg-card px-3 text-muted-foreground">or</span>
        </div>
      </div>

      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (token.trim()) submit(token.trim());
        }}
      >
        <Label htmlFor="token">Paste an ID token</Label>
        <div className="relative">
          <KeyRound
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            id="token"
            type="password"
            autoComplete="off"
            placeholder="Firebase ID token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="pl-10 h-12"
          />
        </div>
        <Button
          type="submit"
          variant="outline"
          className="w-full h-12 font-medium"
          disabled={loading || !token.trim()}
        >
          Use this token
        </Button>
        <p className="text-xs text-muted-foreground">
          Google and email sign-in arrive with the Firebase project. The backend
          already verifies real Firebase ID tokens.
        </p>
      </form>
    </AuthLayout>
  );
}
