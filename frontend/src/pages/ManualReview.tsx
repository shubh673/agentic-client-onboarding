import { ClipboardCheck } from "lucide-react";

import { Card } from "@/components/ui/card";

export function ManualReview() {
  return (
    <div className="mx-auto w-full max-w-3xl px-8 py-8">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight text-foreground">
          Manual review
        </h1>
        <p className="text-sm text-muted-foreground">
          Applications routed to a human for review will appear here.
        </p>
      </div>

      <Card className="mt-8 flex flex-col items-center gap-2 px-6 py-14 text-center">
        <div className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <ClipboardCheck className="size-5" />
        </div>
        <p className="text-base font-medium text-foreground">Nothing in the queue</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          The exception router only sends applications here when an automated
          stage flags a case for human review.
        </p>
      </Card>
    </div>
  );
}
