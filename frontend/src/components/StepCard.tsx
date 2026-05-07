import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { StepBadge } from "./StepBadge";

type Status = "active" | "complete" | "locked";

export function StepCard({
  index,
  title,
  description,
  status,
  icon,
  children,
  trailing,
  isLastConnector,
}: {
  index: number;
  title: string;
  description?: string;
  status: Status;
  icon?: ReactNode;
  children?: ReactNode;
  trailing?: ReactNode;
  isLastConnector?: boolean;
}) {
  return (
    <div className="relative flex gap-4">
      <div className="relative flex flex-col items-center">
        <StepBadge index={index} status={status} />
        {!isLastConnector && (
          <div
            className={cn(
              "mt-1 w-px flex-1",
              status === "complete" ? "bg-primary/40" : "bg-border",
            )}
          />
        )}
      </div>

      <div className="flex-1 pb-6">
        <div
          className={cn(
            "rounded-2xl border bg-card px-5 py-4 shadow-[0_1px_0_rgba(15,23,42,0.04)] transition-colors",
            status === "locked" && "bg-muted/40",
          )}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-3 min-w-0">
              {icon && (
                <div
                  className={cn(
                    "mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg",
                    status === "locked"
                      ? "bg-muted text-muted-foreground"
                      : "bg-accent text-accent-foreground",
                  )}
                >
                  {icon}
                </div>
              )}
              <div className="min-w-0">
                <p
                  className={cn(
                    "text-[11px] font-semibold uppercase tracking-wider",
                    status === "locked" ? "text-muted-foreground" : "text-foreground/70",
                  )}
                >
                  Step {index}
                </p>
                <h3
                  className={cn(
                    "text-[15px] font-semibold leading-tight",
                    status === "locked" ? "text-muted-foreground" : "text-foreground",
                  )}
                >
                  {title}
                </h3>
                {description && (
                  <p className="mt-1 text-sm text-muted-foreground">{description}</p>
                )}
              </div>
            </div>
            {trailing && <div className="shrink-0">{trailing}</div>}
          </div>
          {children && <div className="mt-4">{children}</div>}
        </div>
      </div>
    </div>
  );
}
