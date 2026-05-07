import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { LogEntry } from "@/lib/api";

function formatTime(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export function LiveLogs({ logs }: { logs: LogEntry[] }) {
  const scrollerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  return (
    <section className="rounded-2xl border bg-card shadow-sm">
      <header className="flex items-center justify-between px-5 py-3.5 border-b">
        <h2 className="text-sm font-semibold text-foreground">Live Logs</h2>
        <span className="text-xs text-muted-foreground tabular-nums">
          {logs.length} {logs.length === 1 ? "entry" : "entries"}
        </span>
      </header>
      <div
        ref={scrollerRef}
        className="max-h-[360px] overflow-y-auto rounded-b-2xl bg-[#0b0b0b] px-2 py-2 font-mono text-[12.5px] leading-relaxed"
      >
        {logs.length === 0 ? (
          <p className="px-3 py-6 text-center text-zinc-500">
            Waiting for the agent to emit events…
          </p>
        ) : (
          <ul className="flex flex-col">
            {logs.map((entry) => (
              <li
                key={entry.id}
                className={cn(
                  "flex gap-3 rounded px-3 py-1.5",
                  entry.level === "success" && "bg-emerald-950/60",
                  entry.level === "error" && "bg-red-950/60",
                )}
              >
                <span className="shrink-0 text-zinc-500 select-none">
                  [{formatTime(entry.ts)}]
                </span>
                <span
                  className={cn(
                    "min-w-0 break-words",
                    entry.level === "success" && "text-emerald-300",
                    entry.level === "error" && "text-red-300",
                    entry.level === "info" && "text-zinc-100",
                  )}
                >
                  {entry.message}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
