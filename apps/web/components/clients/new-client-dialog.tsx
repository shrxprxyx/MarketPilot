"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Field, FormError } from "@/components/auth/auth-card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ApiError } from "@/lib/api/problem";
import { useCreateClient, type NewClient } from "@/lib/queries/clients";

// Mirrors ClientIn in apps/api/app/api/v1/clients.py; "" means "left blank".
const schema = z.object({
  name: z.string().trim().min(1, "Name is required").max(200, "Name is too long"),
  website_url: z
    .string()
    .trim()
    .max(500)
    .refine((v) => v === "" || /^https?:\/\//.test(v), "Website must start with http:// or https://"),
  industry: z.string().trim().max(120, "Industry is too long"),
});
type Values = z.infer<typeof schema>;
const DEFAULTS: Values = { name: "", website_url: "", industry: "" };

export function NewClientDialog({ variant = "default" }: { variant?: "default" | "outline" }) {
  const router = useRouter();
  const create = useCreateClient();
  const [open, setOpen] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: DEFAULTS });

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      reset(DEFAULTS);
      setServerError(null);
    }
  }

  async function submit(values: Values) {
    setServerError(null);
    const body: NewClient = { name: values.name };
    if (values.website_url) body.website_url = values.website_url;
    if (values.industry) body.industry = values.industry;
    try {
      const created = await create.mutateAsync(body);
      toast.success("Client created");
      onOpenChange(false);
      router.push(`/clients/${created.id}`);
    } catch (e) {
      setServerError(e instanceof ApiError ? e.detail : "Something went wrong. Please try again.");
    }
  }

  return (
    <>
      <Button variant={variant} className="h-10 px-4" onClick={() => setOpen(true)}>
        <Plus className="size-4" /> New client
      </Button>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>New client</DialogTitle>
            <DialogDescription>
              Add the business you&apos;re doing marketing for. You can add knowledge documents next.
            </DialogDescription>
          </DialogHeader>
          <form noValidate onSubmit={handleSubmit(submit)} className="flex flex-col gap-4">
            <Field id="name" label="Name" error={errors.name?.message} {...register("name")} />
            <Field
              id="website_url"
              label="Website (optional)"
              placeholder="https://"
              error={errors.website_url?.message}
              {...register("website_url")}
            />
            <Field
              id="industry"
              label="Industry (optional)"
              error={errors.industry?.message}
              {...register("industry")}
            />
            <FormError message={serverError} />
            <Button type="submit" size="lg" className="h-11 w-full" disabled={isSubmitting}>
              {isSubmitting ? "Creating…" : "Create client"}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
