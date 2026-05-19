import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, ShieldCheck, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/lib/auth";

const schema = z.object({
  email: z.string().email("Enter a valid email"),
  name: z.string().min(1, "Required").max(255),
  phone_number: z
    .string()
    .regex(/^\+[1-9][0-9]{7,14}$/, "E.164 format, e.g. +919876543210"),
});

type FormValues = z.infer<typeof schema>;

export function Signup() {
  const navigate = useNavigate();
  const { signup } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [appNumber, setAppNumber] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema), mode: "onBlur" });

  const onSubmit = async (values: FormValues) => {
    setSubmitting(true);
    try {
      const { application_number } = await signup(values);
      setAppNumber(application_number);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast.error("Signup failed", {
        description: typeof detail === "string" ? detail : "Please try again.",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-muted/40 px-4">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <ShieldCheck className="size-5" />
          </div>
          <div className="leading-tight">
            <p className="text-base font-semibold tracking-tight">onboard</p>
            <p className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
              agent
            </p>
          </div>
        </div>

        {appNumber ? (
          <Card className="p-6">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-emerald-600" />
              <div className="flex-1">
                <h1 className="text-xl font-semibold tracking-tight">Account created</h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  Check your email for your email and password to continue your application.
                </p>
              </div>
            </div>

            <Button
              onClick={() => navigate("/login")}
              className="mt-5 w-full"
              size="lg"
            >
              Go to login
            </Button>
          </Card>
        ) : (
          <Card className="p-6">
            <h1 className="text-xl font-semibold tracking-tight">Create an account</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              We'll email you an application number and password.
            </p>

            <form onSubmit={handleSubmit(onSubmit)} className="mt-5 space-y-4">
              <Field label="Email" error={errors.email?.message}>
                <Input type="email" placeholder="you@example.com" {...register("email")} />
              </Field>
              <Field label="Full name" error={errors.name?.message}>
                <Input placeholder="Your full name" {...register("name")} />
              </Field>
              <Field label="Phone number" error={errors.phone_number?.message}>
                <Input placeholder="+919876543210" {...register("phone_number")} />
              </Field>

              <Button type="submit" className="w-full" size="lg" disabled={submitting}>
                {submitting ? (
                  <>
                    <Loader2 className="size-4 animate-spin" /> Creating account…
                  </>
                ) : (
                  "Sign up"
                )}
              </Button>
            </form>

            <p className="mt-5 text-center text-sm text-muted-foreground">
              Already have an account?{" "}
              <Link to="/login" className="font-medium text-foreground underline-offset-4 hover:underline">
                Log in
              </Link>
            </p>
          </Card>
        )}
      </div>
    </div>
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
