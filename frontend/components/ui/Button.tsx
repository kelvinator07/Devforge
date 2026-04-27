import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost" | "destructive" | "warning";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

const variantStyles: Record<Variant, string> = {
  primary:
    "bg-indigo-600 text-white hover:bg-indigo-500 active:bg-indigo-700 " +
    "border border-indigo-500/40 shadow-[0_1px_0_rgba(255,255,255,0.08)_inset]",
  secondary:
    "bg-zinc-900 text-zinc-200 hover:bg-zinc-800 active:bg-zinc-900 " +
    "border border-zinc-700 hover:border-zinc-600",
  ghost:
    "bg-transparent text-zinc-300 hover:bg-zinc-800/60 hover:text-zinc-100 " +
    "border border-transparent",
  destructive:
    "bg-rose-600 text-white hover:bg-rose-500 border border-rose-500/40",
  warning:
    "bg-amber-600 text-white hover:bg-amber-500 border border-amber-500/40 " +
    "shadow-[0_1px_0_rgba(255,255,255,0.08)_inset]",
};

const sizeStyles: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = "primary",
      size = "md",
      loading = false,
      leftIcon,
      rightIcon,
      disabled,
      className = "",
      children,
      ...rest
    },
    ref,
  ) => {
    const isDisabled = disabled || loading;
    return (
      <button
        ref={ref}
        disabled={isDisabled}
        className={[
          "focus-ring inline-flex items-center justify-center rounded-md font-medium",
          "transition-[background-color,border-color,opacity] duration-[var(--dur-fast)] ease-[var(--ease)]",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "select-none",
          variantStyles[variant],
          sizeStyles[size],
          className,
        ].join(" ")}
        {...rest}
      >
        {loading ? <Spinner size={size === "sm" ? "sm" : "md"} /> : leftIcon}
        {children && <span>{children}</span>}
        {!loading && rightIcon}
      </button>
    );
  },
);

Button.displayName = "Button";
