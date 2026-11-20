"use client";

import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function AuthCard({
  eyebrow,
  title,
  description,
  children,
  footer,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="w-full max-w-sm">
      <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        {eyebrow}
      </p>
      <h1 className="font-heading text-4xl font-semibold leading-tight tracking-tight">
        {title}
      </h1>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">{description}</p>
      {children && <div className="mt-9 flex flex-col gap-5">{children}</div>}
      {footer && (
        <div className="mt-9 border-t pt-6 text-sm text-muted-foreground">
          {footer}
        </div>
      )}
    </div>
  );
}

/** Label + input + inline error, wired for screen readers. Passwords get a show/hide toggle. */
export function Field({
  id,
  label,
  error,
  type,
  ...input
}: { id: string; label: string; error?: string } & React.ComponentProps<"input">) {
  const [shown, setShown] = useState(false);
  const isPassword = type === "password";
  return (
    <div className="flex flex-col gap-2">
      <Label
        htmlFor={id}
        className="font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-muted-foreground"
      >
        {label}
      </Label>
      <div className="relative">
        <Input
          id={id}
          type={isPassword && shown ? "text" : type}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          className={`h-11 rounded-md bg-white/[0.03] px-3.5 text-sm ${isPassword ? "pr-11" : ""}`}
          {...input}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShown((v) => !v)}
            aria-label={shown ? "Hide password" : "Show password"}
            className="absolute inset-y-0 right-0 grid w-11 place-items-center text-muted-foreground transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none"
          >
            {shown ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        )}
      </div>
      {error && (
        <p id={`${id}-error`} className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
    >
      {message}
    </p>
  );
}
