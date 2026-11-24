import { formatCost } from "@/lib/usage";
import type { Strategy } from "@/lib/queries/strategies";

const LABEL = "font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground";

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className={LABEL}>{title}</h3>
      {children}
    </section>
  );
}

export function StrategyView({ strategy }: { strategy: Strategy }) {
  const { plan } = strategy;
  return (
    <div className="flex flex-col gap-8">
      {strategy.warnings.length > 0 && (
        <section
          role="note"
          aria-label="Check these figures"
          className="rounded-md border border-amber-500/40 bg-amber-500/5 p-4 text-sm"
        >
          <h3 className="font-medium">Check these figures</h3>
          <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-muted-foreground">
            {strategy.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </section>
      )}
      <dl className="grid gap-4 border-y py-4 text-sm sm:grid-cols-3">
        <div>
          <dt className={LABEL}>Model</dt>
          <dd className="mt-1.5">{strategy.model_used}</dd>
        </div>
        <div>
          <dt className={LABEL}>Tokens</dt>
          <dd className="mt-1.5">
            {strategy.tokens_in.toLocaleString("en-US")} in ·{" "}
            {strategy.tokens_out.toLocaleString("en-US")} out
          </dd>
        </div>
        <div>
          <dt className={LABEL}>Cost</dt>
          <dd className="mt-1.5">
            {strategy.cost_usd === null ? "Cost unknown" : formatCost(strategy.cost_usd)}
          </dd>
        </div>
      </dl>

      <Block title="Summary">
        <p className="max-w-3xl text-sm leading-6">{plan.summary}</p>
      </Block>

      <Block title="Objectives">
        <ul className="flex flex-col gap-4">
          {plan.objectives.map((o, i) => (
            <li key={i}>
              <p className="font-medium">{o.title}</p>
              <ul className="mt-1.5 flex flex-col gap-1 text-sm text-muted-foreground">
                {o.kpis.map((k, j) => (
                  <li key={j}>
                    {k.name}: <span className="text-foreground">{k.target}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </Block>

      <Block title="Channels">
        <ul className="flex flex-col gap-3">
          {plan.channels.map((c, i) => (
            <li key={i}>
              <p className="font-medium">{c.name}</p>
              <p className="text-sm text-muted-foreground">{c.rationale}</p>
            </li>
          ))}
        </ul>
      </Block>

      <Block title="Risks">
        <ul className="flex flex-col gap-3">
          {plan.risks.map((r, i) => (
            <li key={i}>
              <p className="font-medium">{r.risk}</p>
              <p className="text-sm text-muted-foreground">{r.mitigation}</p>
            </li>
          ))}
        </ul>
      </Block>

      <section aria-label="Sources used" className="flex flex-col gap-3 border-t pt-6">
        <h3 className={LABEL}>Sources used</h3>
        {strategy.sources.length === 0 ? (
          <p className="text-sm text-muted-foreground">No knowledge documents were used</p>
        ) : (
          <ul className="flex flex-col gap-4">
            {strategy.sources.map((s) => (
              <li key={s.chunk_id}>
                <p className="font-medium">{s.document_title}</p>
                <p className="mt-1 text-sm text-muted-foreground">{s.excerpt}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
