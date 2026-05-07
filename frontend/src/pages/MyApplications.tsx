import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FilePlus2, Inbox, ArrowRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { listApplications, type Application } from "@/lib/api";

export function MyApplications() {
  const [apps, setApps] = useState<Application[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listApplications()
      .then(setApps)
      .catch((e) => setError(e?.message ?? "Failed to load"));
  }, []);

  return (
    <div className="mx-auto w-full max-w-3xl px-8 py-8">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight text-foreground">
            My applications
          </h1>
          <p className="text-sm text-muted-foreground">
            Track customer onboarding applications across the 9-stage flow.
          </p>
        </div>
        <Button asChild size="lg">
          <Link to="/new">
            <FilePlus2 className="size-4" /> Create new application
          </Link>
        </Button>
      </div>

      <div className="mt-8 space-y-3">
        {error && (
          <Card className="border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</Card>
        )}

        {apps && apps.length === 0 && (
          <Card className="flex flex-col items-center gap-2 px-6 py-14 text-center">
            <div className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
              <Inbox className="size-5" />
            </div>
            <p className="text-base font-medium text-foreground">No applications yet</p>
            <p className="max-w-sm text-sm text-muted-foreground">
              Start the onboarding flow to capture a customer's information and run them through the 9
              automated stages.
            </p>
            <Button asChild className="mt-3">
              <Link to="/new">
                <FilePlus2 className="size-4" /> Create your first application
              </Link>
            </Button>
          </Card>
        )}

        {apps && apps.length > 0 && apps.map((a) => (
          <Card key={a.id} className="flex items-center justify-between gap-4 p-4">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-foreground">{a.full_name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {a.email} · created {new Date(a.created_at).toLocaleDateString()}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <Badge variant="default">Stage {Math.min(a.current_stage, 8)} / 8</Badge>
              <Button asChild variant="ghost" size="sm">
                <Link to={`/applications/${a.id}`}>
                  Open <ArrowRight className="size-3.5" />
                </Link>
              </Button>
            </div>
          </Card>
        ))}

        {!apps && !error && (
          <Card className="p-8 text-center text-sm text-muted-foreground">Loading…</Card>
        )}
      </div>
    </div>
  );
}
