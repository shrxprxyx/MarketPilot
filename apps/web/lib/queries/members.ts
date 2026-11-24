import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export type PendingInvite = {
  id: string;
  email: string;
  role: Role;
  expires_at: string;
  created_at: string;
};

export type CreatedInvite = {
  id: string;
  email: string;
  role: Role;
  invite_token: string;
  expires_at: string;
};

export function usePendingInvites(enabled: boolean) {
  return useQuery({
    queryKey: ["members", "invites"],
    queryFn: () => apiFetch<PendingInvite[]>("/members/invites"),
    enabled,
  });
}

// ["members"] is a prefix of both the member list and the invites list.
export function useInviteMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; role: Role }) =>
      apiFetch<CreatedInvite>("/members/invite", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members"] }),
  });
}

export function useRevokeInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/members/invites/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members"] }),
  });
}

export function useUpdateMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: string;
      patch: { role?: Role; status?: "active" | "deactivated" };
    }) => apiFetch<Member>(`/members/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members"] }),
  });
}
