import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ChevronLeft,
  HelpCircle,
  FileText,
  ScanLine,
  ShieldCheck,
  ClipboardList,
  CircleDollarSign,
  FileSignature,
  CreditCard,
  Sparkles,
  AlertTriangle,
  ArrowRight,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { StepCard } from "@/components/StepCard";
import { ApplicationForm } from "@/components/ApplicationForm";
import { Badge } from "@/components/ui/badge";
import type { Application } from "@/lib/api";

type Status = "active" | "complete" | "locked";

const STAGES = [
  {
    title: "Customer Application Initiation",
    description: "Capture full name, contact details, and identity documents (PAN, Aadhaar).",
    icon: FileText,
  },
  {
    title: "Document Verification",
    description: "ID validation, liveness check, and document authenticity scoring.",
    icon: ScanLine,
  },
  {
    title: "KYC Agent",
    description: "Reused subagent: sanctions, PEP, and adverse media screening.",
    icon: ShieldCheck,
  },
  {
    title: "Eligibility",
    description: "Product rules, income checks, and credit bureau queries.",
    icon: ClipboardList,
  },
  {
    title: "Pricing",
    description: "Applies the rate card, computes fees, generates the offer letter.",
    icon: CircleDollarSign,
  },
  {
    title: "Regulatory Disclosure",
    description: "Generates disclosures and captures explicit acknowledgement.",
    icon: FileSignature,
  },
  {
    title: "Account Creation",
    description: "Core banking API call; provisions ledger and downstream systems.",
    icon: CreditCard,
  },
  {
    title: "Welcome",
    description: "Account details, card dispatch trigger, and app activation.",
    icon: Sparkles,
  },
  {
    title: "Exception Router",
    description: "Diverts complex cases to humans with a full context package.",
    icon: AlertTriangle,
  },
] as const;

export function NewApplication() {
  const navigate = useNavigate();
  const [submitted, setSubmitted] = useState<Application | null>(null);

  const handleSubmitted = (app: Application) => {
    setSubmitted(app);
    navigate(`/applications/${app.id}`);
  };

  const currentStage = submitted ? submitted.current_stage : 1;
  const customerName = submitted?.full_name ?? "New customer";

  const statusFor = (idx1: number): Status => {
    if (idx1 < currentStage) return "complete";
    if (idx1 === currentStage) return "active";
    return "locked";
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-8 py-8">
      <Link
        to="/"
        className="inline-flex items-center gap-1 text-sm font-medium text-foreground/70 hover:text-foreground"
      >
        <ChevronLeft className="size-4" /> Go back
      </Link>

      <div className="mt-4 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight text-foreground">
            {customerName}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span>
              Application:{" "}
              <span className="font-medium text-foreground">Customer Onboarding</span>
            </span>
            {submitted && (
              <Badge variant="default">
                Stage {submitted.current_stage} · {submitted.status.replaceAll("_", " ")}
              </Badge>
            )}
          </div>
        </div>
        <Button variant="outline" size="sm" className="rounded-full">
          <HelpCircle className="size-4" />
          Need help? Schedule call
        </Button>
      </div>

      <div className="mt-8">
        {STAGES.map((stage, i) => {
          const idx1 = i + 1;
          const status = statusFor(idx1);
          const isStep1 = idx1 === 1;
          const isLast = idx1 === STAGES.length;

          return (
            <StepCard
              key={idx1}
              index={idx1}
              title={stage.title}
              description={status === "locked" ? "Complete the section above to continue with this step" : stage.description}
              status={status}
              icon={<stage.icon className="size-4" />}
              isLastConnector={isLast}
              trailing={
                status === "active" && !isStep1 ? (
                  <Button size="sm" disabled>
                    Awaiting agent
                  </Button>
                ) : status === "active" && isStep1 && !submitted ? (
                  <Badge variant="default" className="hidden md:inline-flex">
                    In progress
                  </Badge>
                ) : status === "complete" ? (
                  <Badge variant="default" className="bg-primary text-primary-foreground">
                    <ArrowRight className="mr-0.5 size-3" /> Complete
                  </Badge>
                ) : null
              }
            >
              {isStep1 && status === "active" && (
                <ApplicationForm onSubmitted={handleSubmitted} />
              )}
              {isStep1 && status === "complete" && submitted && (
                <SubmittedSummary app={submitted} />
              )}
            </StepCard>
          );
        })}
      </div>
    </div>
  );
}

function SubmittedSummary({ app }: { app: Application }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 rounded-lg bg-muted/40 p-4 text-sm md:grid-cols-2">
      <SummaryRow label="Full name" value={app.full_name} />
      <SummaryRow label="DOB" value={app.dob} />
      <SummaryRow label="Mobile" value={app.mobile} />
      <SummaryRow label="Email" value={app.email} />
      <SummaryRow label="PAN" value={app.pan_number} />
      <SummaryRow
        label="Aadhaar"
        value={`xxxx xxxx ${app.aadhaar_number.slice(-4)}`}
      />
      <SummaryRow
        label="Documents"
        value={`${app.documents.length} uploaded`}
      />
    </dl>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-0.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="truncate font-medium text-foreground">{value}</dd>
    </div>
  );
}
