import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { families as familiesApi } from "@/api/gamiraClient";
import AuthLayout from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";

// A token is single-use, so a second call for the same token always fails —
// even a *correct* second call, from an effect re-run or a fast back/forward
// hop that remounts this screen while the first call is still in flight.
// Memoizing the request by token means every caller within this page load
// shares the one real network call instead of racing a duplicate against it.
const acceptRequests = new Map();
function acceptInvitationOnce(token) {
  if (!acceptRequests.has(token)) {
    acceptRequests.set(token, familiesApi.acceptInvitation(token));
  }
  return acceptRequests.get(token);
}

export default function AcceptInvite() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { refreshSession } = useAuth();
  const [status, setStatus] = useState("accepting"); // accepting | done | error
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    acceptInvitationOnce(token)
      .then(async () => {
        // `refreshSession`, not `checkUserAuth`: this screen sits behind
        // ProtectedRoute, which unmounts it while `isLoadingAuth` is true —
        // `checkUserAuth` sets that flag, which would unmount this effect
        // mid-flight and, on remount, fire it all over again.
        await refreshSession();
        if (!cancelled) setStatus("done");
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message || "This invitation link could not be used.");
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, refreshSession]);

  if (status === "accepting") {
    return (
      <div className="fixed inset-0 flex flex-col items-center justify-center gap-3">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
        <p className="text-sm text-muted-foreground">Linking your account…</p>
      </div>
    );
  }

  if (status === "error") {
    return (
      <AuthLayout icon={XCircle} title="Invitation not valid" subtitle={error}>
        <Button className="w-full h-12 font-medium" onClick={() => navigate("/")}>
          Continue
        </Button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout icon={CheckCircle2} title="You're linked" subtitle="Your Gamira is ready.">
      <Button className="w-full h-12 font-medium" onClick={() => navigate("/")}>
        Continue
      </Button>
    </AuthLayout>
  );
}
