"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { Field, FormError } from "@/components/auth/auth-card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { connectionSchema, type ConnectionValues } from "@/lib/ai/schemas";
import { ApiError } from "@/lib/api/problem";
import { useCreateConnection } from "@/lib/queries/ai";

const PROVIDER_LABELS: Record<ConnectionValues["provider"], string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  ollama: "Ollama",
  openai_compatible: "OpenAI-compatible",
};

const DEFAULTS: ConnectionValues = { provider: "openai", label: "", base_url: "", api_key: "" };

export function AddConnectionDialog({ variant = "default" }: { variant?: "default" | "outline" }) {
  const [open, setOpen] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const create = useCreateConnection();
  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ConnectionValues>({ resolver: zodResolver(connectionSchema), defaultValues: DEFAULTS });

  const provider = useWatch({ control, name: "provider" });
  const needsUrl = provider === "ollama" || provider === "openai_compatible";
  const showUrl = needsUrl || provider === "openai";
  const showKey = provider !== "ollama";

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      reset(DEFAULTS);
      setServerError(null);
    }
  }

  async function submit(values: ConnectionValues) {
    setServerError(null);
    // Send only what the provider uses: no empty strings, and no key for ollama.
    const body: ConnectionValues = { provider: values.provider, label: values.label };
    if (showUrl && values.base_url) body.base_url = values.base_url;
    if (values.provider !== "ollama" && values.api_key) body.api_key = values.api_key;
    try {
      await create.mutateAsync(body);
      toast.success("Connection added");
      onOpenChange(false);
    } catch (e) {
      setServerError(e instanceof ApiError ? e.detail : "Something went wrong. Please try again.");
    }
  }

  return (
    <>
      <Button variant={variant} className="h-10 px-4" onClick={() => setOpen(true)}>
        <Plus className="size-4" /> Add connection
      </Button>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add connection</DialogTitle>
            <DialogDescription>
              Your key is encrypted and can&apos;t be viewed again after saving.
            </DialogDescription>
          </DialogHeader>
          <form noValidate onSubmit={handleSubmit(submit)} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label
                htmlFor="provider"
                className="font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-muted-foreground"
              >
                Provider
              </Label>
              <Select id="provider" {...register("provider")}>
                {Object.entries(PROVIDER_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>
            <Field id="label" label="Name" error={errors.label?.message} {...register("label")} />
            {showUrl && (
              <Field
                id="base_url"
                label={needsUrl ? "Base URL" : "Base URL (optional)"}
                placeholder={provider === "ollama" ? "https://your-tunnel.example.com" : "https://"}
                error={errors.base_url?.message}
                {...register("base_url")}
              />
            )}
            {showKey && (
              <Field
                id="api_key"
                label="API key"
                type="password"
                autoComplete="off"
                error={errors.api_key?.message}
                {...register("api_key")}
              />
            )}
            {provider === "ollama" && (
              <p className="text-sm leading-6 text-muted-foreground">
                Our cloud API can&apos;t reach <code>localhost</code> on your machine. Expose Ollama
                through a tunnel (for example Cloudflare Tunnel or ngrok) and use that public URL,
                or run the API locally.
              </p>
            )}
            <FormError message={serverError} />
            <Button type="submit" size="lg" className="h-11 w-full" disabled={isSubmitting}>
              {isSubmitting ? "Saving…" : "Save connection"}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
