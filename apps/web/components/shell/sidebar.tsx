"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Wordmark } from "@/components/brand";
import { useSession } from "@/lib/auth/session-store";
import { isActive, navFor } from "@/lib/nav";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const role = useSession((s) => s.me?.role);
  const pathname = usePathname();
  const sections = role ? navFor(role) : [];

  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-9 px-4 py-6">
      <Wordmark className="px-2" />
      {sections.map((section) => (
        <div key={section.label}>
          <p className="mb-3 px-3 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            {section.label}
          </p>
          <ul className="flex flex-col gap-0.5">
            {section.items.map((item) => {
              const active = isActive(item.href, pathname);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={`flex items-center gap-4 rounded-md px-3 py-2.5 text-[15px] transition-colors ${
                      active
                        ? "bg-white/[0.07] text-foreground"
                        : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground"
                    }`}
                  >
                    <span className="font-mono text-xs">{item.number}</span>
                    <span>{item.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
