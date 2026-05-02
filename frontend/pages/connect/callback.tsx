import { SignedIn, SignedOut, RedirectToSignIn, useAuth } from "@clerk/nextjs";
import { useRouter } from "next/router";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2, AlertCircle, ArrowRight } from "lucide-react";

import { connectInstallation } from "../../lib/api";
import { consumeInstallState, setActive } from "../../lib/active";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { Spinner } from "../../components/ui/Spinner";

type Status =
  | { kind: "validating" }
  | { kind: "connecting" }
  | { kind: "success"; tenantId: number; repoCount: number }
  | { kind: "error"; message: string };

export default function ConnectCallback() {
  return (
    <>
      <SignedOut>
        <RedirectToSignIn />
      </SignedOut>
      <SignedIn>
        <ConnectCallbackInner />
      </SignedIn>
    </>
  );
}

function ConnectCallbackInner() {
  const router = useRouter();
  const { getToken } = useAuth();
  const [status, setStatus] = useState<Status>({ kind: "validating" });
  // Guard against React strict-mode double-invoke + router.query re-creation
  // re-running the effect and consuming the state token twice.
  const ranRef = useRef(false);

  useEffect(() => {
    if (!router.isReady || ranRef.current) return;
    ranRef.current = true;

    const installationId = Number(router.query.installation_id);
    const setupAction = String(router.query.setup_action || "");
    const state = String(router.query.state || "");

    if (!Number.isFinite(installationId) || installationId <= 0) {
      setStatus({
        kind: "error",
        message: "Missing installation_id in callback URL — GitHub didn't return one. Try connecting again.",
      });
      return;
    }
    if (setupAction === "request") {
      setStatus({
        kind: "error",
        message: "GitHub App install was requested but needs approval from an org admin. Once approved, click Connect again.",
      });
      return;
    }

    const expectedState = consumeInstallState();
    if (!expectedState || expectedState !== state) {
      setStatus({
        kind: "error",
        message: "Session state mismatch. This usually means the tab was closed mid-install. Please connect again from the dashboard.",
      });
      return;
    }

    setStatus({ kind: "connecting" });
    connectInstallation(getToken, { installation_id: installationId, state })
      .then((tenant) => {
        if (!tenant.repos.length) {
          setStatus({
            kind: "error",
            message: "GitHub install completed, but the App has no repository access. Re-install and grant at least one repo.",
          });
          return;
        }
        setActive({ tenantId: tenant.id, repoId: tenant.repos[0].id });
        setStatus({
          kind: "success",
          tenantId: tenant.id,
          repoCount: tenant.repos.length,
        });
        // Navigate to dashboard after a brief beat so the success card is visible.
        setTimeout(() => router.replace("/dashboard"), 900);
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e);
        setStatus({ kind: "error", message: msg });
      });
  }, [router.isReady, router.query, getToken, router]);

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center px-6">
      <Card variant="elevated" className="w-full">
        {status.kind === "validating" && (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <Spinner size="lg" />
            <div className="text-sm font-medium text-zinc-100">Validating install…</div>
          </div>
        )}
        {status.kind === "connecting" && (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <Spinner size="lg" />
            <div className="text-sm font-medium text-zinc-100">Connecting your repos…</div>
            <div className="text-xs text-zinc-500">
              Discovering which repos you granted access to.
            </div>
          </div>
        )}
        {status.kind === "success" && (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-400">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <div className="text-sm font-medium text-zinc-100">
              Connected · {status.repoCount} {status.repoCount === 1 ? "repo" : "repos"}
            </div>
            <div className="text-xs text-zinc-500">Taking you to the dashboard…</div>
          </div>
        )}
        {status.kind === "error" && (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-rose-500/10 text-rose-400">
              <AlertCircle className="h-5 w-5" />
            </div>
            <div className="text-sm font-medium text-zinc-100">Install couldn&apos;t be completed</div>
            <div className="text-xs text-zinc-400">{status.message}</div>
            <Button
              size="sm"
              rightIcon={<ArrowRight className="h-3.5 w-3.5" />}
              onClick={() => router.replace("/dashboard")}
            >
              Back to dashboard
            </Button>
          </div>
        )}
      </Card>
    </main>
  );
}
