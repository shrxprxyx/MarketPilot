"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Upload } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Field, FormError } from "@/components/auth/auth-card";
import { Button } from "@/components/ui/button";
import { TextareaField } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/problem";
import { usePasteDocument, useUploadDocument, type AddedDocument } from "@/lib/queries/documents";

const ALLOWED = [".pdf", ".docx", ".txt", ".md"];
const MAX_BYTES = 10 * 1024 * 1024;

const schema = z.object({
  title: z.string().trim().min(1, "Title is required").max(300, "Title is too long"),
  text: z.string().trim().min(1, "Text is required"),
});
type Values = z.infer<typeof schema>;

const detailOf = (e: unknown) =>
  e instanceof ApiError ? e.detail : "Something went wrong. Please try again.";

// The API reports a content-hash duplicate with 202 and duplicate: true.
const announce = (r: AddedDocument) =>
  toast.success(r.duplicate ? "Already added" : "Uploaded - indexing started");

export function AddDocumentPanel({ clientId }: { clientId: string }) {
  const upload = useUploadDocument(clientId);
  const paste = usePasteDocument(clientId);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [pasteError, setPasteError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { title: "", text: "" } });

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow choosing the same file again
    if (!file) return;
    setUploadError(null);
    if (!ALLOWED.some((ext) => file.name.toLowerCase().endsWith(ext))) {
      setUploadError("Use a PDF, DOCX, TXT or MD file");
      return;
    }
    if (file.size > MAX_BYTES) {
      setUploadError("Files must be 10 MB or smaller");
      return;
    }
    setUploading(true);
    try {
      announce(await upload.mutateAsync(file));
    } catch (err) {
      setUploadError(detailOf(err));
    } finally {
      setUploading(false);
    }
  }

  async function submitPaste(values: Values) {
    setPasteError(null);
    try {
      announce(await paste.mutateAsync(values));
      reset({ title: "", text: "" });
    } catch (err) {
      setPasteError(detailOf(err));
    }
  }

  return (
    <div className="grid gap-10 border-y py-8 lg:grid-cols-2">
      <div className="flex flex-col gap-3">
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          Upload a file
        </p>
        <label className="inline-flex h-10 w-fit cursor-pointer items-center gap-2 rounded-md border px-4 text-sm font-medium transition-colors hover:bg-white/[0.06] has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50">
          <Upload className="size-4" />
          {uploading ? "Uploading…" : "Upload file"}
          <input
            type="file"
            accept=".pdf,.docx,.txt,.md"
            className="sr-only"
            disabled={uploading}
            onChange={onFile}
            aria-label="Upload file"
          />
        </label>
        <p className="text-xs text-muted-foreground">PDF, DOCX, TXT or MD, up to 10 MB.</p>
        <FormError message={uploadError} />
      </div>

      <form noValidate onSubmit={handleSubmit(submitPaste)} className="flex flex-col gap-4">
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          Or paste text
        </p>
        <Field id="paste-title" label="Title" error={errors.title?.message} {...register("title")} />
        <TextareaField
          id="paste-text"
          label="Text"
          className="min-h-32"
          error={errors.text?.message}
          {...register("text")}
        />
        <FormError message={pasteError} />
        <div>
          <Button type="submit" className="h-10 px-4" disabled={isSubmitting}>
            {isSubmitting ? "Adding…" : "Add text"}
          </Button>
        </div>
      </form>
    </div>
  );
}
