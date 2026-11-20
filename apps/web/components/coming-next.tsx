export function ComingNext({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="max-w-2xl">
      <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        Coming next
      </p>
      <h1 className="font-heading text-4xl font-semibold leading-tight tracking-tight">
        {title}
      </h1>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">{description}</p>
      <div className="mt-10 border-t pt-6 text-sm text-muted-foreground">
        This screen is being built next. The rest of your workspace works as usual.
      </div>
    </div>
  );
}
