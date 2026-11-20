"use client";

import { ChevronDown, LogOut } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { signOut } from "@/lib/api/client";
import { useSession } from "@/lib/auth/session-store";

export function UserMenu() {
  const me = useSession((s) => s.me);
  if (!me) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex h-10 max-w-64 cursor-pointer items-center gap-3 rounded-md border bg-white/[0.02] pl-1.5 pr-3 text-left outline-none transition-colors hover:bg-white/[0.05] focus-visible:ring-2 focus-visible:ring-ring">
        <span
          aria-hidden
          className="grid size-7 shrink-0 place-items-center rounded-[5px] bg-foreground text-xs font-semibold text-background"
        >
          {me.email.charAt(0).toUpperCase()}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm leading-4">{me.email}</span>
          <span className="block font-mono text-[10px] uppercase leading-4 tracking-[0.14em] text-muted-foreground">
            {me.role}
          </span>
        </span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-56">
        <DropdownMenuItem onClick={() => void signOut()}>
          <LogOut aria-hidden />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
