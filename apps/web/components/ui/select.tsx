import * as React from "react";
import { cn } from "cn";

// A styled native <select>: accessible and keyboard friendly for short fixed lists.
function Select({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      data-slot="select"
      className={cn(
        "h-11 w-full min-w-0 cursor-pointer rounded-md border border-input bg-white/[0.03] px-3 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive [&>option]:bg-popover",
        className,
      )}
      {...props}
    />
  );
}

export { Select };
