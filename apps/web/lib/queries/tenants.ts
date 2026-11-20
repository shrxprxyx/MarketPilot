import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { Role } from "@/lib/auth/session-store";

export type Tenant = { id: string; name: string; role: Role };

/** The agencies the signed-in user belongs to (for the agency switcher). */
export function useTenants() {
  return useQuery({
    queryKey: ["tenants"],
    queryFn: () => apiFetch<Tenant[]>("/me/tenants"),
  });
}
