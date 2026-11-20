"use client";

import { usePathname } from "next/navigation";
import { pageLabel } from "@/lib/nav";

export function Breadcrumb() {
  const label = pageLabel(usePathname());
  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <span className="block truncate font-heading text-lg font-medium tracking-tight">
        {label}
      </span>
    </nav>
  );
}
