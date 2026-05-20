import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { FileDropzone } from "./FileDropzone";
import { createApplication, type Application } from "@/lib/api";

const schema = z.object({
  full_name: z.string().min(1, "Required"),
  dob: z.string().min(1, "Required"),
  mobile: z.string().regex(/^[+]?[0-9 \-]{7,20}$/, "Enter a valid mobile number"),
  email: z.string().email("Enter a valid email"),
  address: z.string().min(1, "Required"),
  pan_number: z
    .string()
    .transform((s) => s.toUpperCase())
    .pipe(z.string().regex(/^[A-Z]{5}[0-9]{4}[A-Z]$/, "Format: 5 letters · 4 digits · 1 letter")),
  aadhaar_number: z.string().regex(/^[0-9]{12}$/, "Aadhaar must be 12 digits"),
});

type FormValues = z.infer<typeof schema>;

const TOTAL_FIELDS = 9; // 7 text + 2 files

export function ApplicationForm({
  onSubmitted,
  defaults,
}: {
  onSubmitted: (app: Application) => void;
  defaults?: { full_name?: string; email?: string; mobile?: string };
}) {
  const [panFile, setPanFile] = useState<File | null>(null);
  const [aadhaarFile, setAadhaarFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [fileErrors, setFileErrors] = useState<{ pan?: string; aadhaar?: string }>({});

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    mode: "onBlur",
    defaultValues: {
      full_name: defaults?.full_name ?? "",
      email: defaults?.email ?? "",
      mobile: defaults?.mobile ?? "",
    },
  });

  const watched = watch();
  const filledCount = useMemo(() => {
    const filled = (
      ["full_name", "dob", "mobile", "email", "address", "pan_number", "aadhaar_number"] as const
    ).filter((k) => (watched[k] ?? "").toString().trim().length > 0).length;
    return filled + (panFile ? 1 : 0) + (aadhaarFile ? 1 : 0);
  }, [watched, panFile, aadhaarFile]);
  const progress = Math.round((filledCount / TOTAL_FIELDS) * 100);

  const onSubmit = async (values: FormValues) => {
    const fileErr: { pan?: string; aadhaar?: string } = {};
    if (!panFile) fileErr.pan = "Upload your PAN card";
    if (!aadhaarFile) fileErr.aadhaar = "Upload your Aadhaar card";
    setFileErrors(fileErr);
    if (fileErr.pan || fileErr.aadhaar) return;

    const fd = new FormData();
    Object.entries(values).forEach(([k, v]) => fd.append(k, String(v)));
    fd.append("pan_file", panFile!);
    fd.append("aadhaar_file", aadhaarFile!);

    setSubmitting(true);
    try {
      const app = await createApplication(fd);
      toast.success("Application submitted", {
        description: `Welcome, ${app.full_name}. Stage 1 complete.`,
      });
      onSubmitted(app);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast.error("Could not submit application", {
        description: typeof detail === "string" ? detail : "Please check your inputs and try again.",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
      <div className="flex items-center gap-3">
        <Progress value={progress} className="flex-1" />
        <span className="w-10 text-right text-xs font-medium text-muted-foreground tabular-nums">
          {progress}%
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Field label="Full name" error={errors.full_name?.message}>
          <Input placeholder="Hazel Mannion" {...register("full_name")} />
        </Field>
        <Field label="Date of birth" error={errors.dob?.message}>
          <Input type="date" {...register("dob")} />
        </Field>
        <Field label="Mobile" error={errors.mobile?.message}>
          <Input placeholder="+91 98765 43210" {...register("mobile")} />
        </Field>
        <Field label="Email" error={errors.email?.message}>
          <Input type="email" placeholder="hazel@example.com" {...register("email")} />
        </Field>
        <div className="md:col-span-2">
          <Field label="Address" error={errors.address?.message}>
            <Textarea placeholder="221B Baker Street, …" rows={2} {...register("address")} />
          </Field>
        </div>
        <Field label="PAN number" error={errors.pan_number?.message}>
          <Input
            placeholder="ABCDE1234F"
            maxLength={10}
            className="uppercase tracking-wider"
            {...register("pan_number")}
          />
        </Field>
        <Field label="Aadhaar number" error={errors.aadhaar_number?.message}>
          <Input
            inputMode="numeric"
            placeholder="1234 1234 1234"
            maxLength={12}
            {...register("aadhaar_number")}
          />
        </Field>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <FileDropzone
          label="Upload PAN card"
          file={panFile}
          onChange={(f) => {
            setPanFile(f);
            if (f) setFileErrors((e) => ({ ...e, pan: undefined }));
          }}
          error={fileErrors.pan}
        />
        <FileDropzone
          label="Upload Aadhaar card"
          file={aadhaarFile}
          onChange={(f) => {
            setAadhaarFile(f);
            if (f) setFileErrors((e) => ({ ...e, aadhaar: undefined }));
          }}
          error={fileErrors.aadhaar}
        />
      </div>

      <div className="flex items-center justify-end gap-3 pt-1">
        <Button type="submit" disabled={submitting} size="lg">
          {submitting ? (
            <>
              <Loader2 className="size-4 animate-spin" /> Submitting…
            </>
          ) : (
            <>Submit application</>
          )}
        </Button>
      </div>
    </form>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
