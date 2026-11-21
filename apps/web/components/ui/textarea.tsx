import * as React from "react";
import { cn } from "cn";
import { Label } from "@/components/ui/label";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "min-h-24 w-full min-w-0 rounded-md border border-input bg-white/[0.03] px-3.5 py-2.5 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive",
        className,
      )}
      {...props}
    />
  );
}

/** Label + textarea + optional hint and inline error, wired for screen readers. */
function TextareaField({
  id,
  label,
  hint,
  error,
  ...props
}: { id: string; label: string; hint?: string; error?: string } & React.ComponentProps<"textarea">) {
  return (
    <div className="flex flex-col gap-2">
      <Label
        htmlFor={id}
        className="font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-muted-foreground"
      >
        {label}
      </Label>
      <Textarea
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        {...props}
      />
      {hint && !error && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error && (
        <p id={`${id}-error`} className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

export { Textarea, TextareaField };
