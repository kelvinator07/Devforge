import type { ReactNode } from "react";

export type BadgeTone =
  | "neutral"
  | "indigo"
  | "emerald"
  | "amber"
  | "rose"
  | "blue"
  | "violet";

const toneStyles: Record<BadgeTone, string> = {
  neutral: "bg-zinc-800/70 text-zinc-300 border-zinc-700",
  indigo:  "bg-indigo-500/10 text-indigo-300 border-indigo-500/30",
  emerald: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  amber:   "bg-amber-500/10 text-amber-300 border-amber-500/30",
  rose:    "bg-rose-500/10 text-rose-300 border-rose-500/30",
  blue:    "bg-blue-500/10 text-blue-300 border-blue-500/30",
  violet:  "bg-violet-500/10 text-violet-300 border-violet-500/30",
};

export function Badge({
  tone = "neutral",
  icon,
  children,
  className = "",
}: {
  tone?: BadgeTone;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        toneStyles[tone],
        className,
      ].join(" ")}
    >
      {icon && <span className="flex h-3 w-3 items-center justify-center">{icon}</span>}
      {children}
    </span>
  );
}
