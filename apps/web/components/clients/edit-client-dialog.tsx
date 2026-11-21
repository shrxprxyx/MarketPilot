"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Pencil } from "lucide-react";
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
import { TextareaField } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/problem";
import { fromList, toList } from "@/lib/lines";
import { useUpdateClient, type Client } from "@/lib/queries/clients";

// Mirrors ClientPatch in apps/api/app/api/v1/clients.py; "" means "cleared".
const schema = z.object({
  name: z.string().trim().min(1, "Name is required").max(200, "Name is too long"),
  website_url: z
    .string()
    .trim()
    .max(500)
    .refine((v) => v === "" || /^https?:\/\//.test(v), "Website must start with http:// or https://"),
  industry: z.string().trim().max(120, "Industry is too long"),
  goals: z.string(),
});
type Values = z.infer<typeof schema>;

const defaultsOf = (c: Client): Values => ({
  name: c.name,
  website_url: c.website_url ?? "",
  industry: c.industry ?? "",
  goals: fromList(c.goals),
});

export function EditClientDialog({ client }: { client: Client }) {
  const update = useUpdateClient(client.id);
  const [open, setOpen] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: defaultsOf(client) });

  function onOpenChange(next: boolean) {
    setOpen(next);
    setServerError(null);
    // Always start from the latest saved values, never from a previous abandoned edit.
    reset(defaultsOf(client));
  }

  async function submit(values: Values) {
    setServerError(null);
    try {
      await update.mutateAsync({
        name: values.name,
        website_url: values.website_url || null,
        industry: values.industry || null,
        goals: toList(values.goals),
      });
      toast.success("Client updated");
      setOpen(false);
    } catch (e) {
      setServerError(e instanceof ApiError ? e.detail : "Something went wrong. Please try again.");
    }
  }

  return (
    <>
      <Button variant="outline" className="h-10 px-4" onClick={() => onOpenChange(true)}>
        <Pencil className="size-4" /> Edit client
      </Button>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit client</DialogTitle>
            <DialogDescription>Update the details of this client.</DialogDescription>
          </DialogHeader>
          <form noValidate onSubmit={handleSubmit(submit)} className="flex flex-col gap-4">
            <Field id="edit-name" label="Name" error={errors.name?.message} {...register("name")} />
            <Field
              id="edit-website"
              label="Website (optional)"
              placeholder="https://"
              error={errors.website_url?.message}
              {...register("website_url")}
            />
            <Field
              id="edit-industry"
              label="Industry (optional)"
              error={errors.industry?.message}
              {...register("industry")}
            />
            <TextareaField
              id="edit-goals"
              label="Goals (one per line)"
              error={errors.goals?.message}
              {...register("goals")}
            />
            <FormError message={serverError} />
            <Button type="submit" size="lg" className="h-11 w-full" disabled={isSubmitting}>
              {isSubmitting ? "Saving…" : "Save changes"}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
