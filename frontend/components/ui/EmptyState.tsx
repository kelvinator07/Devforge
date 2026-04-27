import type { ReactNode } from "react";

export function EmptyState({
  icon,
  title,
  caption,
  action,
  className = "",
}: {
  icon?: ReactNode;
  title: ReactNode;
  caption?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={[
        "flex flex-col items-center justify-center gap-3 rounded-lg",
        "border border-dashed border-[var(--border)] bg-[var(--card)]/50",
        "px-6 py-12 text-center",
        className,
      ].join(" ")}
    >
      {icon && (
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-zinc-800/60 text-zinc-400">
          {icon}
        </div>
      )}
      <div>
        <div className="text-sm font-medium text-zinc-200">{title}</div>
        {caption && <div className="mt-1 text-xs text-zinc-500">{caption}</div>}
      </div>
      {action}
    </div>
  );
}
