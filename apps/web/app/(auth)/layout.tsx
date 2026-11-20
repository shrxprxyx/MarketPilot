import { Suspense } from "react";
import { RedirectIfAuthed } from "@/components/auth/redirect-if-authed";
import { Wordmark } from "@/components/brand";

const points = [
  ["01", "Audit", "Technical SEO, social and competitor audits in minutes."],
  ["02", "Plan", "Monthly strategy and a 30-day content calendar from your own data."],
  ["03", "Deliver", "On-brand content, task boards and white-label reports."],
] as const;

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-svh flex-1 lg:grid-cols-[1.05fr_1fr]">
      <aside className="hidden flex-col justify-between border-r p-12 lg:flex">
        <Wordmark />
        <div>
          <p className="mb-5 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            AI marketing operations
          </p>
          <h2 className="font-heading text-5xl font-semibold leading-[1.08] tracking-tight">
            Run every client&apos;s marketing from one place.
          </h2>
          <ul className="mt-14 border-t">
            {points.map(([n, title, text]) => (
              <li key={n} className="flex gap-6 border-b py-5">
                <span className="pt-0.5 font-mono text-xs text-muted-foreground">{n}</span>
                <div>
                  <p className="font-medium">{title}</p>
                  <p className="mt-1 text-sm text-muted-foreground">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          Built for agencies
        </p>
      </aside>

      <main className="flex flex-col items-center justify-center gap-10 p-6 sm:p-12">
        <Wordmark className="lg:hidden" />
        {/* useSearchParams in the forms needs a Suspense boundary (cacheComponents). */}
        <Suspense>
          <RedirectIfAuthed />
          {children}
        </Suspense>
      </main>
    </div>
  );
}
