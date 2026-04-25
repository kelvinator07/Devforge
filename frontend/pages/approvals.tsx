import { SignedIn, SignedOut, RedirectToSignIn, UserButton } from "@clerk/nextjs";
import Link from "next/link";

import { useApi, type PendingApproval } from "../lib/api";
import { PendingApprovalCard } from "../components/PendingApprovalCard";

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
    <div className="mx-auto max-w-3xl px-6 py-10">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <Link href="/dashboard" className="text-sm text-zinc-500 hover:text-zinc-300">← dashboard</Link>
          <h1 className="mt-1 text-2xl font-semibold">Pending approvals</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Migration / dependency / infra steps require an admin to mint a one-time token.
          </p>
        </div>
        <UserButton />
      </header>

      {pending.loading && <div className="text-zinc-500">loading...</div>}
      {pending.error && (
        <div className="rounded border border-rose-700/40 bg-rose-500/5 p-3 text-sm text-rose-300">
          {pending.error}
        </div>
      )}
      {pending.data && pending.data.pending.length === 0 && (
        <div className="rounded border border-zinc-800 bg-[var(--card)] p-6 text-center text-zinc-500">
          no pending approvals.
        </div>
      )}
      <div className="space-y-3">
        {pending.data?.pending.map((p) => (
          <PendingApprovalCard key={p.id} item={p} />
        ))}
      </div>
    </div>
  );
}
