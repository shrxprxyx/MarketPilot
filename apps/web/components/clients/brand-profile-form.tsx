"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Field, FormError } from "@/components/auth/auth-card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TextareaField } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/problem";
import { useSession } from "@/lib/auth/session-store";
import { fromList, textOrNull, toList } from "@/lib/lines";
import {
  useBrandProfile,
  useSaveBrandProfile,
  type BrandProfile,
  type BrandProfileInput,
} from "@/lib/queries/brand-profile";

// Mirrors BrandProfileIn in apps/api/app/api/v1/clients.py (voice and tone are max 120).
const schema = z.object({
  voice: z.string().max(120, "Voice must be 120 characters or fewer"),
  tone: z.string().max(120, "Tone must be 120 characters or fewer"),
  audience: z.string(),
  keywords: z.string(),
  do_rules: z.string(),
  dont_rules: z.string(),
  sample_text: z.string(),
});
type Values = z.infer<typeof schema>;

const valuesOf = (p: BrandProfile | null): Values => ({
  voice: p?.voice ?? "",
  tone: p?.tone ?? "",
  audience: p?.audience ?? "",
  keywords: fromList(p?.keywords),
  do_rules: fromList(p?.do_rules),
  dont_rules: fromList(p?.dont_rules),
  sample_text: p?.sample_text ?? "",
});

const detailOf = (e: unknown) =>
  e instanceof ApiError ? e.detail : "Something went wrong. Please try again.";

function ProfileFields({
  clientId,
  profile,
  canWrite,
}: {
  clientId: string;
  profile: BrandProfile | null;
  canWrite: boolean;
}) {
  const save = useSaveBrandProfile(clientId);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    getValues,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: valuesOf(profile) });
  const ro = { readOnly: !canWrite };

  async function submit(v: Values) {
    setServerError(null);
    // The API replaces the whole profile, so every field is always sent.
    const input: BrandProfileInput = {
      voice: textOrNull(v.voice),
      tone: textOrNull(v.tone),
      audience: textOrNull(v.audience),
      keywords: toList(v.keywords),
      do_rules: toList(v.do_rules),
      dont_rules: toList(v.dont_rules),
      sample_text: textOrNull(v.sample_text),
    };
    try {
      await save.mutateAsync(input);
      toast.success("Brand profile saved");
      reset(getValues());
    } catch (e) {
      setServerError(detailOf(e));
    }
  }

  return (
    <form noValidate onSubmit={handleSubmit(submit)} className="flex max-w-2xl flex-col gap-5">
      <div className="grid gap-5 sm:grid-cols-2">
        <Field id="bp-voice" label="Voice" error={errors.voice?.message} {...ro} {...register("voice")} />
        <Field id="bp-tone" label="Tone" error={errors.tone?.message} {...ro} {...register("tone")} />
      </div>
      <TextareaField id="bp-audience" label="Audience" {...ro} {...register("audience")} />
      <TextareaField
        id="bp-keywords"
        label="Keywords (one per line)"
        {...ro}
        {...register("keywords")}
      />
      <div className="grid gap-5 sm:grid-cols-2">
        <TextareaField
          id="bp-do"
          label="Do rules (one per line)"
          {...ro}
          {...register("do_rules")}
        />
        <TextareaField
          id="bp-dont"
          label="Don't rules (one per line)"
          {...ro}
          {...register("dont_rules")}
        />
      </div>
      <TextareaField
        id="bp-sample"
        label="Sample text"
        hint="A short example of writing that sounds like this brand."
        className="min-h-32"
        {...ro}
        {...register("sample_text")}
      />
      <FormError message={serverError} />
      {canWrite && (
        <div>
          <Button type="submit" size="lg" className="h-11 px-6" disabled={!isDirty || isSubmitting}>
            {isSubmitting ? "Saving…" : "Save profile"}
          </Button>
        </div>
      )}
    </form>
  );
}

export function BrandProfileForm({ clientId }: { clientId: string }) {
  const role = useSession((s) => s.me?.role);
  const canWrite = role === "admin" || role === "manager";
  const { data, isLoading, error } = useBrandProfile(clientId);

  if (isLoading) return <Skeleton data-testid="profile-skeleton" className="h-72 w-full max-w-2xl" />;
  // No profile saved yet resolves to null (empty form); anything else is a real failure.
  if (error) {
    return <p className="text-sm text-muted-foreground">{detailOf(error)}</p>;
  }
  return (
    // Remount when the saved profile changes so the form baseline matches the server.
    <ProfileFields
      key={JSON.stringify(data ?? null)}
      clientId={clientId}
      profile={data ?? null}
      canWrite={canWrite}
    />
  );
}
