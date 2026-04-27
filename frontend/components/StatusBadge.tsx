import {
  Activity,
  CheckCircle2,
  Clock,
  GitMerge,
  Loader2,
  XCircle,
} from "lucide-react";
import { Badge, type BadgeTone } from "./ui/Badge";

type Mapping = { tone: BadgeTone; icon: React.ReactNode; label?: string };

const MAP: Record<string, Mapping> = {
  pr_opened: { tone: "emerald", icon: <CheckCircle2 className="h-3 w-3" />, label: "PR opened" },
  running:   { tone: "blue",    icon: <Loader2 className="h-3 w-3 animate-spin-fast" />, label: "Running" },
  queued:    { tone: "neutral", icon: <Clock className="h-3 w-3" />, label: "Queued" },
  failed:    { tone: "rose",    icon: <XCircle className="h-3 w-3" />, label: "Failed" },
  refused:   { tone: "rose",    icon: <XCircle className="h-3 w-3" />, label: "Refused" },
  awaiting_approval: { tone: "amber", icon: <Clock className="h-3 w-3" />, label: "Awaiting approval" },
  approval_superseded: { tone: "neutral", icon: <GitMerge className="h-3 w-3" />, label: "Superseded" },
};

const FALLBACK: Mapping = {
  tone: "neutral",
  icon: <Activity className="h-3 w-3" />,
};

export function StatusBadge({ status }: { status: string }) {
  const m = MAP[status] || FALLBACK;
  return (
    <Badge tone={m.tone} icon={m.icon}>
      {m.label ?? status}
    </Badge>
  );
}
