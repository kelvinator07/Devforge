import { Loader2 } from "lucide-react";

type Size = "sm" | "md" | "lg";

const sizeMap: Record<Size, string> = {
  sm: "h-3.5 w-3.5",
  md: "h-4 w-4",
  lg: "h-5 w-5",
};

export function Spinner({ size = "md", className = "" }: { size?: Size; className?: string }) {
  return (
    <Loader2
      className={`${sizeMap[size]} animate-spin-fast ${className}`}
      aria-hidden="true"
    />
  );
}
