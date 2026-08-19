import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound, Loader2, LogIn, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import AuthLayout from "@/components/AuthLayout";
import GoogleIcon from "@/components/GoogleIcon";
import { useAuth } from "@/lib/AuthContext";
import { useFirebaseAuth } from "@/lib/useFirebaseAuth";
import { safeReturnTo } from "@/lib/authReturnTo";

// The backend verifies a bearer token; it never sees a password. The
// dev-identity list stays available regardless of whether Firebase is
// configured — `run.py` opens several of these at once via `?dev=<subject>`
// to test multiple family members side by side.
const DEV_IDENTITIES = [
  { subject: "sharma-senior", label: "Vikram Sharma — the cared-for person" },
  { subject: "sharma-senior-2", label: "Sunita Sharma — a second cared-for person" },
  { subject: "iyer-senior", label: "Lakshmi Iyer — cared-for person, Iyer family" },
  { subject: "sharma-owner", label: "Anjali Sharma — family owner" },
  { subject: "sharma-caregiver", label: "Rohan Sharma — caregiver, not yet linked" },
];

export default function Login() {
  const navigate = useNavigate();
  const { signIn } = useAuth();
  const { firebaseEnabled, signInWithGoogle, signInWithEmail, registerWithEmail } =
    useFirebaseAuth();
  const returnTo = safeReturnTo();

  const [subject, setSubject] = useState(DEV_IDENTITIES[0].subject);
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState("sign-in"); // sign-in | register
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const run = async (action) => {
    setError("");
    setLoading(true);
    try {
      await action();
      navigate(returnTo, { replace: true });
    } catch (err) {
      setError(err.message || "Could not sign in.");
    } finally {
      setLoading(false);
    }
  };

  const submitDev = (e) => {
    e.preventDefault();
    run(() => signIn(`dev:${subject}`));
  };

  const submitToken = (e) => {
    e.preventDefault();
    if (token.trim()) run(() => signIn(token.trim()));
  };

  const submitEmail = (e) => {
    e.preventDefault();
    if (!email.trim() || !password) return;
    run(() =>
      mode === "register"
        ? registerWithEmail(email.trim(), password)
        : signInWithEmail(email.trim(), password),
    );
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

      {firebaseEnabled && (
        <>
          <Button
            type="button"
            variant="outline"
            className="w-full h-12 font-medium"
            disabled={loading}
            onClick={() => run(signInWithGoogle)}
          >
            <GoogleIcon className="w-4 h-4 mr-2" />
            Continue with Google
          </Button>

          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-border" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-card px-3 text-muted-foreground">or</span>
            </div>
          </div>

          <form className="space-y-3" onSubmit={submitEmail}>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <div className="relative">
                <Mail
                  className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground"
                  aria-hidden="true"
                />
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="pl-10 h-12"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-12"
              />
            </div>
            <Button
              type="submit"
              className="w-full h-12 font-medium"
              disabled={loading || !email.trim() || !password}
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  {mode === "register" ? "Creating account…" : "Signing in…"}
                </>
              ) : mode === "register" ? (
                "Create account"
              ) : (
                "Sign in"
              )}
            </Button>
            <button
              type="button"
              onClick={() => setMode(mode === "register" ? "sign-in" : "register")}
              className="w-full text-center text-xs text-muted-foreground hover:text-foreground"
            >
              {mode === "register"
                ? "Already have an account? Sign in"
                : "New here? Create an account"}
            </button>
          </form>

          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-border" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-card px-3 text-muted-foreground">
                local development identities
              </span>
            </div>
          </div>
        </>
      )}

      <form className="space-y-4" onSubmit={submitDev}>
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

        <Button
          type="submit"
          variant={firebaseEnabled ? "outline" : "default"}
          className="w-full h-12 font-medium"
          disabled={loading}
        >
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

      <form className="space-y-2" onSubmit={submitToken}>
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
          The backend verifies real Firebase ID tokens directly, if you already
          have one from somewhere else.
        </p>
      </form>
    </AuthLayout>
  );
}
