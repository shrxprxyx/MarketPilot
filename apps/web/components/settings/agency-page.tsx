"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Field, FormError } from "@/components/auth/auth-card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/problem";
import { useSession } from "@/lib/auth/session-store";
import {
  useRenameTenant,
  useSaveBranding,
  useTenantDetail,
  type TenantDetail,
} from "@/lib/queries/tenant";

const LABEL = "font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground";
const FAILED = "Something went wrong. Please try again.";

// Mirrors TenantPatch in apps/api/app/api/v1/tenant.py.
const nameSchema = z.object({
  name: z.string().trim().min(1, "Agency name is required").max(120, "Name is too long"),
});
type NameValues = z.infer<typeof nameSchema>;

// Mirrors BrandingIn. "" means "left blank", which clears the stored value.
const brandingSchema = z.object({
  logo_url: z
    .string()
    .trim()
    .max(500, "Logo URL is too long")
    .refine((v) => v === "" || /^https?:\/\/\S+$/i.test(v), "Logo URL must start with http:// or https://"),
  primary_color: z
    .string()
    .trim()
    .refine((v) => v === "" || /^#[0-9a-fA-F]{6}$/.test(v), "Use a hex color like #1f6f43"),
  report_footer: z.string().trim().max(300, "Keep the footer under 300 characters"),
});
type BrandingValues = z.infer<typeof brandingSchema>;

function NameForm({ tenant }: { tenant: TenantDetail }) {
  const rename = useRenameTenant();
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<NameValues>({ resolver: zodResolver(nameSchema), defaultValues: { name: tenant.name } });

  async function submit(values: NameValues) {
    setServerError(null);
    try {
      const saved = await rename.mutateAsync(values.name);
      toast.success("Agency name saved");
      reset({ name: saved.name });
    } catch (e) {
      setServerError(e instanceof ApiError ? e.detail : FAILED);
    }
  }

  return (
    <form noValidate onSubmit={handleSubmit(submit)} className="flex max-w-md flex-col gap-4">
      <Field id="agency-name" label="Agency name" error={errors.name?.message} {...register("name")} />
      <FormError message={serverError} />
      <div>
        <Button type="submit" size="lg" className="h-11 cursor-pointer px-6" disabled={!isDirty || isSubmitting}>
          {isSubmitting ? "Saving…" : "Save name"}
        </Button>
      </div>
    </form>
  );
}

function BrandingForm({ tenant }: { tenant: TenantDetail }) {
  const save = useSaveBranding();
  const [serverError, setServerError] = useState<string | null>(null);
  const toValues = (t: TenantDetail): BrandingValues => ({
    logo_url: t.branding.logo_url ?? "",
    primary_color: t.branding.primary_color ?? "",
    report_footer: t.branding.report_footer ?? "",
  });
  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<BrandingValues>({ resolver: zodResolver(brandingSchema), defaultValues: toValues(tenant) });
  const color = useWatch({ control, name: "primary_color" });
  const validColor = /^#[0-9a-fA-F]{6}$/.test(color ?? "") ? color : null;

  async function submit(values: BrandingValues) {
    setServerError(null);
    try {
      const saved = await save.mutateAsync({
        logo_url: values.logo_url || null,
        primary_color: values.primary_color || null,
        report_footer: values.report_footer || null,
      });
      toast.success("Branding saved");
      reset(toValues(saved));
    } catch (e) {
      setServerError(e instanceof ApiError ? e.detail : FAILED);
    }
  }

  return (
    <form noValidate onSubmit={handleSubmit(submit)} className="flex max-w-md flex-col gap-4">
      <Field
        id="logo-url"
        label="Logo URL (optional)"
        placeholder="https://"
        error={errors.logo_url?.message}
        {...register("logo_url")}
      />
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <Field
            id="primary-color"
            label="Primary color (optional)"
            placeholder="#1f6f43"
            error={errors.primary_color?.message}
            {...register("primary_color")}
          />
        </div>
        <span
          data-testid="color-swatch"
          aria-hidden="true"
          className="mb-1 size-10 shrink-0 rounded-md border"
          style={validColor ? { backgroundColor: validColor } : undefined}
        />
      </div>
      <Field
        id="report-footer"
        label="Report footer (optional)"
        placeholder="Prepared by your agency"
        error={errors.report_footer?.message}
        {...register("report_footer")}
      />
      <FormError message={serverError} />
      <div>
        <Button type="submit" size="lg" className="h-11 cursor-pointer px-6" disabled={!isDirty || isSubmitting}>
          {isSubmitting ? "Saving…" : "Save branding"}
        </Button>
      </div>
    </form>
  );
}

export function AgencyPage() {
  const role = useSession((s) => s.me?.role);
  const { data, isLoading, isError } = useTenantDetail(role === "admin");

  if (!role) return null;

  return (
    <div className="flex max-w-5xl flex-col gap-12">
      <header>
        <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          Settings
        </p>
        <h1 className="font-heading text-4xl font-semibold leading-tight tracking-tight">Agency</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
          Your agency&apos;s name and the branding used on client-facing reports.
        </p>
      </header>

      {role !== "admin" ? (
        <p className="border-y py-10 text-sm text-muted-foreground">
          Only admins can change agency settings.
        </p>
      ) : isLoading ? (
        <Skeleton data-testid="agency-skeleton" className="h-40 w-full max-w-md" />
      ) : isError || !data ? (
        <p className="text-sm text-muted-foreground">
          Couldn&apos;t load the agency settings. Try again later.
        </p>
      ) : (
        <>
          <section className="flex flex-col gap-6">
            <p className={LABEL}>Name</p>
            <NameForm key={data.name} tenant={data} />
          </section>
          <section className="flex flex-col gap-6">
            <div>
              <p className={LABEL}>White-label branding</p>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                Reports carry your logo, color and footer, and no MarketPilot branding.
              </p>
            </div>
            <BrandingForm key={JSON.stringify(data.branding)} tenant={data} />
          </section>
        </>
      )}
    </div>
  );
}
