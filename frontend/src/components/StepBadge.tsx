import { Check, Lock } from "lucide-react";
import { cn } from "@/lib/utils";

type Status = "active" | "complete" | "locked";

export function StepBadge({ index, status }: { index: number; status: Status }) {
  return (
    <div
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-full border text-xs font-semibold transition-colors",
        status === "complete" && "border-primary bg-primary text-primary-foreground",
        status === "active" && "border-primary bg-background text-primary ring-4 ring-accent",
        status === "locked" && "border-border bg-background text-muted-foreground",
      )}
      aria-label={`Step ${index} ${status}`}
    >
      {status === "complete" ? (
        <Check className="size-4" strokeWidth={3} />
      ) : status === "locked" ? (
        <Lock className="size-3.5" />
      ) : (
        <span>{index}</span>
      )}
    </div>
  );
}
