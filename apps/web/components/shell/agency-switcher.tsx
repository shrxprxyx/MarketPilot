"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ChevronsUpDown } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { switchTenant } from "@/lib/api/client";
import { ApiError, GENERIC_DETAIL } from "@/lib/api/problem";
import { useSession } from "@/lib/auth/session-store";
import { useTenants } from "@/lib/queries/tenants";

const box =
  "flex h-10 max-w-56 items-center gap-2 rounded-md border bg-white/[0.02] px-3 text-sm";

export function AgencySwitcher() {
  const me = useSession((s) => s.me);
  const { data: tenants } = useTenants();
  const queryClient = useQueryClient();
  const router = useRouter();

  if (!me) return null;

  // One agency (or still loading): show the name, with nothing to click.
  if (!tenants || tenants.length < 2) {
    return (
      <div className={box}>
        <span className="truncate">{me.tenant_name}</span>
      </div>
    );
  }

  async function onSwitch(id: string) {
    if (id === me?.tenant_id) return;
    try {
      await switchTenant(id);
      // Drop everything cached for the previous agency before showing the new one.
      queryClient.clear();
      router.replace("/");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : GENERIC_DETAIL);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={`${box} cursor-pointer outline-none transition-colors hover:bg-white/[0.05] focus-visible:ring-2 focus-visible:ring-ring`}
      >
        <span className="truncate">{me.tenant_name}</span>
        <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-60">
        <DropdownMenuRadioGroup value={me.tenant_id} onValueChange={onSwitch}>
          {tenants.map((t) => (
            <DropdownMenuRadioItem key={t.id} value={t.id}>
              <span className="truncate">{t.name}</span>
              <span className="ml-auto pl-3 font-mono text-[11px] uppercase text-muted-foreground">
                {t.role}
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
