import { SignedIn, SignedOut, SignInButton, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect } from "react";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-6 px-4 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">DevForge</h1>
      <p className="text-center text-zinc-400">
        Multi-agent engineering platform — watch the crew turn tickets into PRs in real time.
      </p>

      <SignedOut>
        <div className="flex gap-3">
          <SignInButton mode="modal">
            <button className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500">
              Sign in
            </button>
          </SignInButton>
        </div>
      </SignedOut>

      <SignedIn>
        <RedirectToDashboard />
        <div className="flex items-center gap-4">
          <Link
            href="/dashboard"
            className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
          >
            Open dashboard
          </Link>
          <UserButton />
        </div>
      </SignedIn>
    </main>
  );
}

function RedirectToDashboard() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);
  return null;
}
