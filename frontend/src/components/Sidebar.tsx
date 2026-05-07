import { NavLink } from "react-router-dom";
import {
  FilePlus2,
  ListChecks,
  ShieldCheck,
  ChevronDown,
  ClipboardCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "My applications", icon: ListChecks, enabled: true },
  { to: "/new", label: "New application", icon: FilePlus2, enabled: true },
  { to: "/manual-review", label: "Manual review", icon: ClipboardCheck, enabled: true },
];

export function Sidebar() {
  return (
    <aside className="flex h-screen w-[260px] shrink-0 flex-col border-r bg-background">
      <div className="px-5 pt-6 pb-4">
        <div className="flex items-center gap-2">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <ShieldCheck className="size-4" />
          </div>
          <div className="leading-tight">
            <p className="text-[15px] font-semibold tracking-tight text-foreground">onboard</p>
            <p className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground">agent</p>
          </div>
        </div>
      </div>

      <nav className="flex flex-col gap-0.5 px-3">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={label}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
              )
            }
          >
            <Icon className="size-4" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="mx-3 mt-auto mb-3 rounded-xl border bg-muted/40 p-4">
        <p className="text-sm font-semibold text-foreground">Make onboarding easier</p>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          The onboarding agent automates KYC, eligibility, and account setup in a single flow.
        </p>
      </div>

      <div className="border-t p-3">
        <button className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left hover:bg-accent">
          <div className="flex size-8 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground">
            DU
          </div>
          <div className="flex-1 text-sm leading-tight">
            <p className="font-medium text-foreground">Demo User</p>
            <p className="text-xs text-muted-foreground">Customer</p>
          </div>
          <ChevronDown className="size-4 text-muted-foreground" />
        </button>
      </div>
    </aside>
  );
}
