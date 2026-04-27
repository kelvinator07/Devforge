import { Hammer } from "lucide-react";

export function Brand({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const dim = size === "sm" ? "h-4 w-4" : size === "lg" ? "h-6 w-6" : "h-5 w-5";
  const text = size === "sm" ? "text-sm" : size === "lg" ? "text-xl" : "text-base";
  return (
    <span className="inline-flex items-center gap-2 font-semibold tracking-tight">
      <span
        className={`${dim} flex items-center justify-center rounded-md bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-[0_0_0_1px_rgba(99,102,241,0.4)]`}
        aria-hidden="true"
      >
        <Hammer className="h-3 w-3" strokeWidth={2.5} />
      </span>
      <span className={`${text} text-zinc-100`}>DevForge</span>
    </span>
  );
}
