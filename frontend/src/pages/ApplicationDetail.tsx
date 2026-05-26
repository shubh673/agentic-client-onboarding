import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AlertTriangle,
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
  ArrowRight,
  Loader2,
  Wifi,
  WifiOff,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { StepCard } from "@/components/StepCard";
import { LiveLogs } from "@/components/LiveLogs";
import { FileDropzone } from "@/components/FileDropzone";
import {
  getApplication,
  getApplicationLogs,
  openApplicationSocket,
  reuploadDocuments,
  type Application,
  type LogEntry,
} from "@/lib/api";

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
    runningCopy: "Running document verification — checking authenticity and liveness…",
    pendingCopy: "Pending — about to start document verification.",
    failedCopy: "Document verification failed — please re-upload the corrected documents.",
    icon: ScanLine,
  },
  {
    title: "KYC Agent",
    description: "Reused subagent: dedup, sanctions, PEP, and adverse media screening.",
    runningCopy: "Running KYC checks — dedup, sanctions, PEP, and adverse media…",
    pendingCopy: "Pending KYC — agent will start screening shortly.",
    failedCopy: "KYC rejected — application blocked.",
    manualReviewCopy: "KYC flagged for manual review by compliance.",
    icon: ShieldCheck,
  },
  {
    title: "Eligibility",
    description: "Product rules, income checks, and credit bureau queries.",
    runningCopy: "Evaluating eligibility — product rules and credit bureau lookup in progress…",
    pendingCopy: "Pending eligibility evaluation.",
    icon: ClipboardList,
  },
  {
    title: "Pricing",
    description: "Applies the rate card, computes fees, generates the offer letter.",
    runningCopy: "Applying rate card and computing fees…",
    pendingCopy: "Pending pricing — offer letter will be generated next.",
    icon: CircleDollarSign,
  },
  {
    title: "Regulatory Disclosure",
    description: "Generates disclosures and captures explicit acknowledgement.",
    runningCopy: "Generating disclosures and capturing acknowledgement…",
    pendingCopy: "Pending disclosures.",
    icon: FileSignature,
  },
  {
    title: "Account Creation",
    description: "Core banking API call; provisions ledger and downstream systems.",
    runningCopy: "Provisioning account — calling core banking and downstream systems…",
    pendingCopy: "Pending account creation.",
    icon: CreditCard,
  },
  {
    title: "Welcome",
    description: "Account details, card dispatch trigger, and app activation.",
    runningCopy: "Sending welcome pack and triggering card dispatch…",
    pendingCopy: "Pending welcome.",
    icon: Sparkles,
  },
] as const;

type StageMeta = (typeof STAGES)[number];

function isFailedAt(idx1: number, app: Application): boolean {
  return app.status === `stage_${idx1}_failed`;
}

function isManualReviewAt(idx1: number, app: Application): boolean {
  return idx1 === app.current_stage && app.status === "manual_review";
}

function statusFor(idx1: number, app: Application): Status {
  if (app.status === "completed") return "complete";
  // A Stage failure halts the runner at current_stage=idx1; treat it as the
  // active card (so the failure/reason panel renders inside it).
  if (isFailedAt(idx1, app)) return "active";
  if (isManualReviewAt(idx1, app)) return "active";
  if (idx1 < app.current_stage) return "complete";
  if (idx1 === app.current_stage) return "active";
  return "locked";
}

function isRunning(idx1: number, app: Application): boolean {
  return app.status === `stage_${idx1}_running`;
}

function describe(idx1: number, stage: StageMeta, app: Application, status: Status): string {
  if (status === "complete") return stage.description;
  if (status === "locked") {
    return "Complete the section above to continue with this step.";
  }
  // active
  if (idx1 === 1) return stage.description;
  if (isFailedAt(idx1, app)) {
    return ("failedCopy" in stage && stage.failedCopy) || stage.description;
  }
  if (isManualReviewAt(idx1, app)) {
    return ("manualReviewCopy" in stage && stage.manualReviewCopy) || stage.description;
  }
  if (isRunning(idx1, app)) {
    return ("runningCopy" in stage && stage.runningCopy) || stage.description;
  }
  return ("pendingCopy" in stage && stage.pendingCopy) || stage.description;
}

const KYC_REASON_LABELS: Record<string, string> = {
  duplicate_identifier:
    "Duplicate identifier — PAN, Aadhaar, email, or mobile already on file with another application.",
  possible_duplicate_fuzzy:
    "Possible duplicate — name and date of birth closely match an existing application.",
  cross_field_anomaly:
    "Cross-field anomaly — one of the supplied identifiers has been previously paired with a different PAN/Aadhaar.",
  risk_screening_manual_review:
    "Risk screening (sanctions / PEP / adverse media) returned a signal that requires human review.",
  sanctions_hit:
    "Sanctions match — the applicant's name and date of birth match a sanctioned entity. Compliance must confirm before proceeding.",
  pep_hit:
    "Politically Exposed Person — the applicant matches a PEP record and requires enhanced due diligence.",
  compliance_manual_review:
    "Compliance screening could not be completed automatically and needs a manual review.",
  manual_review_required: "Flagged for manual review by compliance.",
  kyc_rejected: "KYC screening rejected the application.",
  kyc_agent_error:
    "The KYC agent failed mid-run. A compliance officer will retry shortly.",
};

function friendlyReason(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return KYC_REASON_LABELS[reason] ?? reason.replaceAll("_", " ");
}

export function ApplicationDetail() {
  const { id } = useParams<{ id: string }>();
  const [app, setApp] = useState<Application | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    Promise.all([getApplication(id), getApplicationLogs(id)])
      .then(([appData, logEntries]) => {
        if (cancelled) return;
        setApp(appData);
        setLogs(logEntries);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.response?.data?.detail ?? e?.message ?? "Failed to load");
      });

    const ws = openApplicationSocket(id, (event) => {
      if (event.type === "application_update") {
        setApp(event.application);
      } else if (event.type === "log_appended") {
        setLogs((prev) =>
          prev.some((entry) => entry.id === event.log.id) ? prev : [...prev, event.log],
        );
      }
    });
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    return () => {
      cancelled = true;
      ws.close();
    };
  }, [id]);

  if (error) {
    return (
      <div className="mx-auto w-full max-w-3xl px-8 py-8">
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-sm font-medium text-foreground/70 hover:text-foreground"
        >
          <ChevronLeft className="size-4" /> Go back
        </Link>
        <div className="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      </div>
    );
  }

  if (!app) {
    return (
      <div className="mx-auto w-full max-w-3xl px-8 py-8 text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

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
            {app.full_name}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span>
              Application:{" "}
              <span className="font-medium text-foreground">Customer Onboarding</span>
            </span>
            <Badge variant="default">
              Stage {Math.min(app.current_stage, 8)} · {app.status.replaceAll("_", " ")}
            </Badge>
            <span
              className={
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium " +
                (connected
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : "border-border bg-muted text-muted-foreground")
              }
              title={connected ? "Live updates connected" : "Disconnected"}
            >
              {connected ? <Wifi className="size-3" /> : <WifiOff className="size-3" />}
              {connected ? "live" : "offline"}
            </span>
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
          const status = statusFor(idx1, app);
          const running = status === "active" && isRunning(idx1, app);
          const isLast = idx1 === STAGES.length;

          return (
            <StepCard
              key={idx1}
              index={idx1}
              title={stage.title}
              description={describe(idx1, stage, app, status)}
              status={status}
              icon={<stage.icon className="size-4" />}
              isLastConnector={isLast}
              trailing={
                status === "complete" ? (
                  <Badge variant="default" className="bg-primary text-primary-foreground">
                    <ArrowRight className="mr-0.5 size-3" /> Complete
                  </Badge>
                ) : status === "active" && isFailedAt(idx1, app) ? (
                  <Badge
                    variant="default"
                    className="gap-1 border-destructive/30 bg-destructive/10 text-destructive"
                  >
                    <AlertTriangle className="size-3" /> {idx1 === 2 ? "Failed" : "Rejected"}
                  </Badge>
                ) : status === "active" && isManualReviewAt(idx1, app) ? (
                  <Badge
                    variant="default"
                    className="gap-1 border-amber-200 bg-amber-50 text-amber-700"
                  >
                    <AlertTriangle className="size-3" /> Manual review
                  </Badge>
                ) : status === "active" && running ? (
                  <Badge variant="default" className="gap-1">
                    <Loader2 className="size-3 animate-spin" /> Running
                  </Badge>
                ) : status === "active" ? (
                  <Badge variant="muted">Pending</Badge>
                ) : null
              }
            >
              {idx1 === 1 && <SubmittedSummary app={app} />}
              {idx1 === 2 && app.status === "stage_2_failed" && (
                <ReuploadPanel app={app} />
              )}
              {idx1 === 3 && (isFailedAt(3, app) || isManualReviewAt(3, app)) && (
                <KYCReasonPanel app={app} />
              )}
            </StepCard>
          );
        })}
      </div>

      <div className="mt-4">
        <LiveLogs logs={logs} />
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
      <SummaryRow label="Documents" value={`${app.documents.length} uploaded`} />
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

function KYCReasonPanel({ app }: { app: Application }) {
  const isManualReview = app.status === "manual_review";
  const reason = friendlyReason(app.verification_reason) ?? (
    isManualReview ? "Flagged for manual review." : "KYC screening rejected the application."
  );
  const palette = isManualReview
    ? "border-amber-200 bg-amber-50 text-amber-800"
    : "border-destructive/30 bg-destructive/5 text-destructive";
  const heading = isManualReview ? "Manual review required" : "KYC rejected";
  const followUp = isManualReview
    ? "A compliance officer will review your application and reach out with next steps."
    : "This application has been blocked. If you believe this is a mistake, contact support.";

  return (
    <div className={`rounded-lg border p-4 ${palette}`}>
      <div className="flex items-start gap-2 text-sm">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <div>
          <p className="font-medium">{heading}</p>
          <p className="mt-0.5">{reason}</p>
          <p className="mt-1 opacity-90">{followUp}</p>
        </div>
      </div>
    </div>
  );
}

function ReuploadPanel({ app }: { app: Application }) {
  const [panFile, setPanFile] = useState<File | null>(null);
  const [aadhaarFile, setAadhaarFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async () => {
    if (!panFile && !aadhaarFile) {
      toast.error("Pick at least one document to re-upload");
      return;
    }
    setSubmitting(true);
    try {
      await reuploadDocuments(app.id, { pan: panFile, aadhaar: aadhaarFile });
      toast.success("Documents resubmitted", {
        description: "Stage 2 is re-running.",
      });
      setPanFile(null);
      setAadhaarFile(null);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast.error("Re-upload failed", {
        description: typeof detail === "string" ? detail : "Please try again.",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4">
      <div className="flex items-start gap-2 text-sm text-destructive">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <div>
          <p className="font-medium">Verification failed</p>
          {app.verification_reason && (
            <p className="mt-0.5 text-destructive/90">{app.verification_reason}</p>
          )}
          <p className="mt-1 text-destructive/80">
            Replace the PAN or Aadhaar image (or both) with a clearer copy and resubmit.
          </p>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <FileDropzone label="Re-upload PAN card" file={panFile} onChange={setPanFile} />
        <FileDropzone
          label="Re-upload Aadhaar card"
          file={aadhaarFile}
          onChange={setAadhaarFile}
        />
      </div>

      <div className="mt-3 flex justify-end">
        <Button onClick={onSubmit} disabled={submitting} size="sm">
          {submitting ? (
            <>
              <Loader2 className="size-4 animate-spin" /> Resubmitting…
            </>
          ) : (
            <>Resubmit documents</>
          )}
        </Button>
      </div>
    </div>
  );
}
