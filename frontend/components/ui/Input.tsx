import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

const baseInput =
  "focus-ring w-full rounded-md border bg-[#0e1116] px-3 text-sm text-zinc-100 " +
  "placeholder:text-zinc-600 transition-colors duration-[var(--dur-fast)] ease-[var(--ease)] " +
  "outline-none";

const stateStyles = {
  ok: "border-[var(--border-strong)] hover:border-zinc-600 focus:border-indigo-500",
  error: "border-rose-500/60 focus:border-rose-500",
};

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ invalid, className = "", ...rest }, ref) => (
    <input
      ref={ref}
      className={`${baseInput} ${invalid ? stateStyles.error : stateStyles.ok} h-9 ${className}`}
      {...rest}
    />
  ),
);
Input.displayName = "Input";

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ invalid, className = "", ...rest }, ref) => (
    <textarea
      ref={ref}
      className={`${baseInput} ${invalid ? stateStyles.error : stateStyles.ok} py-2 leading-relaxed ${className}`}
      {...rest}
    />
  ),
);
Textarea.displayName = "Textarea";

export function Label({
  htmlFor,
  children,
  hint,
}: {
  htmlFor?: string;
  children: React.ReactNode;
  hint?: React.ReactNode;
}) {
  return (
    <div className="mb-1.5 flex items-center justify-between">
      <label htmlFor={htmlFor} className="text-xs font-medium uppercase tracking-wide text-zinc-400">
        {children}
      </label>
      {hint && <span className="text-xs text-zinc-600">{hint}</span>}
    </div>
  );
}
