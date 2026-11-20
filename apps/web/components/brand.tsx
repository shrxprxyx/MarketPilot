export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <span className="grid size-8 place-items-center rounded-[6px] bg-foreground">
        <span className="size-2.5 rounded-[2px] bg-background" />
      </span>
      <span className="font-heading text-lg font-semibold tracking-tight">
        MarketPilot
      </span>
    </div>
  );
}
