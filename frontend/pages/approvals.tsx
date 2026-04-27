import { SignedIn, SignedOut, RedirectToSignIn } from "@clerk/nextjs";
import Link from "next/link";
import { ArrowLeft, ShieldCheck } from "lucide-react";

import { useApi, type PendingApproval } from "../lib/api";
import { PendingApprovalCard } from "../components/PendingApprovalCard";
import { Layout } from "../components/Layout";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";

export default function Approvals() {
  return (
    <>
      <SignedOut>
        <RedirectToSignIn />
      </SignedOut>
      <SignedIn>
        <ApprovalsInner />
      </SignedIn>
    </>
  );
}

function ApprovalsInner() {
  const pending = useApi<{ pending: PendingApproval[] }>("/approvals/pending");

  return (
    <Layout width="default">
      <div className="mb-6">
        <Link
          href="/dashboard"
          className="focus-ring inline-flex items-center gap-1 rounded-md text-xs text-zinc-500 no-underline hover:text-zinc-300"
        >
          <ArrowLeft className="h-3 w-3" />
          Dashboard
        </Link>
        <h1 className="mt-2 text-[var(--text-h1)] font-semibold tracking-tight text-zinc-100">
          Pending approvals
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          Migration, dependency, and infra steps require an admin to mint a one-time token.
        </p>
      </div>

      {pending.loading && (
        <div className="space-y-2">
          {[0, 1].map((i) => (
            <div key={i} className="h-24 rounded-lg animate-shimmer" />
          ))}
        </div>
      )}

      {pending.error && (
        <Card variant="danger" padding="sm">
          <div className="text-sm text-rose-200">{pending.error}</div>
        </Card>
      )}

      {pending.data && pending.data.pending.length === 0 && (
        <EmptyState
          icon={<ShieldCheck className="h-5 w-5" />}
          title="No pending approvals"
          caption="Approvals will appear here when an agent hits a destructive step."
        />
      )}

      <div className="space-y-3">
        {pending.data?.pending.map((p) => (
          <PendingApprovalCard key={p.id} item={p} />
        ))}
      </div>
    </Layout>
  );
}
