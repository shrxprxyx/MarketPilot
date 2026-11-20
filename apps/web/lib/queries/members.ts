import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { Role } from "@/lib/auth/session-store";

export type Member = {
  id: string;
  user_id: string;
  email: string;
  role: Role;
  status: string;
  created_at: string;
};

// Admin-only on the API; pass enabled=false for any other role.
export function useMembers(enabled: boolean) {
  return useQuery({
    queryKey: ["members"],
    queryFn: () => apiFetch<Member[]>("/members"),
    enabled,
  });
}
