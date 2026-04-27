import Link from "next/link";
import { useRouter } from "next/router";
import type { ReactNode } from "react";
import { UserButton } from "@clerk/nextjs";
import { LayoutDashboard, ShieldCheck, Github } from "lucide-react";
import { Brand } from "./Brand";

type Width = "narrow" | "default" | "wide";

const widthClass: Record<Width, string> = {
  narrow: "max-w-3xl",
  default: "max-w-4xl",
  wide: "max-w-6xl",
};

export function Layout({
  children,
  width = "wide",
}: {
  children: ReactNode;
  width?: Width;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <TopNav />
      <main className={`mx-auto w-full ${widthClass[width]} flex-1 px-6 py-8 animate-fade-in`}>
        {children}
      </main>
      <Footer />
    </div>
  );
}

function TopNav() {
  const router = useRouter();
  const isActive = (href: string) =>
    href === "/" ? router.pathname === "/" : router.pathname.startsWith(href);

  return (
    <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-[var(--background)]/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <div className="flex items-center gap-8">
          <Link href="/dashboard" className="focus-ring rounded-md no-underline">
            <Brand />
          </Link>
          <nav className="hidden items-center gap-1 md:flex">
            <NavLink
              href="/dashboard"
              icon={<LayoutDashboard className="h-3.5 w-3.5" />}
              active={isActive("/dashboard")}
            >
              Dashboard
            </NavLink>
            <NavLink
              href="/approvals"
              icon={<ShieldCheck className="h-3.5 w-3.5" />}
              active={isActive("/approvals")}
            >
              Approvals
            </NavLink>
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <a
            href="https://github.com/kelvinator07/Devforge"
            target="_blank"
            rel="noreferrer"
            className="focus-ring rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-800/60 hover:text-zinc-200 no-underline"
            aria-label="GitHub"
          >
            <Github className="h-4 w-4" />
          </a>
          <div className="flex h-7 w-7 items-center justify-center">
            <UserButton
              appearance={{
                elements: {
                  avatarBox: "h-7 w-7",
                },
              }}
            />
          </div>
        </div>
      </div>
    </header>
  );
}

function NavLink({
  href,
  icon,
  active,
  children,
}: {
  href: string;
  icon?: ReactNode;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={[
        "focus-ring inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm",
        "transition-colors duration-[var(--dur-fast)] ease-[var(--ease)] no-underline",
        active
          ? "bg-zinc-800/60 text-zinc-100"
          : "text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-200",
      ].join(" ")}
    >
      {icon}
      {children}
    </Link>
  );
}

function Footer() {
  return (
    <footer className="border-t border-[var(--border)] py-4">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 text-xs text-zinc-600">
        <span>DevForge — multi-agent engineering platform</span>
        <span className="font-mono">v0.1</span>
      </div>
    </footer>
  );
}
