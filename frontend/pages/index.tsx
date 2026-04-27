import { SignedIn, SignedOut, SignInButton } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect } from "react";
import { ArrowRight, Sparkles } from "lucide-react";

import { Brand } from "../components/Brand";
import { Button } from "../components/ui/Button";

export default function Home() {
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center gap-8 px-6 py-16">
      <div className="absolute top-6 left-6">
        <Brand size="md" />
      </div>

      <div className="flex flex-col items-center gap-4 text-center animate-fade-in">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-300">
          <Sparkles className="h-3 w-3" />
          Multi-agent engineering platform
        </span>
        <h1 className="text-[clamp(2rem,4vw,3rem)] font-semibold tracking-tight text-zinc-100">
          From ticket to pull request,
          <br />
          <span className="bg-gradient-to-r from-indigo-300 to-violet-300 bg-clip-text text-transparent">
            in real time.
          </span>
        </h1>
        <p className="max-w-md text-sm text-zinc-400">
          Watch a 5-agent crew plan, implement, test, and ship — inside a sandboxed worktree
          with strict guardrails.
        </p>
      </div>

      <SignedOut>
        <SignInButton mode="modal">
          <Button size="md" rightIcon={<ArrowRight className="h-4 w-4" />}>
            Sign in to continue
          </Button>
        </SignInButton>
      </SignedOut>

      <SignedIn>
        <RedirectToDashboard />
        <Link href="/dashboard" className="no-underline">
          <Button size="md" rightIcon={<ArrowRight className="h-4 w-4" />}>
            Open dashboard
          </Button>
        </Link>
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
