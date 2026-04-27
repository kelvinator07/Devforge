import type { HTMLAttributes, ReactNode } from "react";

type Variant = "default" | "elevated" | "accent" | "danger";

const variantStyles: Record<Variant, string> = {
  default:
    "bg-[var(--card)] border border-[var(--border)] " +
    "shadow-[var(--shadow-card)]",
  elevated:
    "bg-gradient-to-b from-[var(--card-hover)] to-[var(--card)] " +
    "border border-[var(--border-strong)] " +
    "shadow-[var(--shadow-card-hover)]",
  accent:
    "bg-gradient-to-br from-amber-500/[0.06] to-[var(--card)] " +
    "border border-amber-500/30 shadow-[var(--shadow-card)]",
  danger:
    "bg-gradient-to-br from-rose-500/[0.06] to-[var(--card)] " +
    "border border-rose-500/30 shadow-[var(--shadow-card)]",
};

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: Variant;
  padding?: "none" | "sm" | "md" | "lg";
  hover?: boolean;
}

const paddingStyles = {
  none: "",
  sm: "p-3",
  md: "p-4",
  lg: "p-6",
};

export function Card({
  variant = "default",
  padding = "md",
  hover = false,
  className = "",
  children,
  ...rest
}: CardProps) {
  return (
    <div
      className={[
        "rounded-lg",
        variantStyles[variant],
        paddingStyles[padding],
        hover &&
          "transition-[background-color,border-color,box-shadow] duration-[var(--dur)] ease-[var(--ease)] hover:bg-[var(--card-hover)] hover:border-[var(--border-strong)] hover:shadow-[var(--shadow-card-hover)]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  right,
  className = "",
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex items-start justify-between gap-3 ${className}`}>
      <div>
        <div className="text-[var(--text-h2)] font-semibold text-zinc-100">{title}</div>
        {subtitle && <div className="mt-0.5 text-xs text-zinc-500">{subtitle}</div>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}
