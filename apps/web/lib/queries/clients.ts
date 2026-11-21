import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";

export type Client = {
  id: string;
  name: string;
  website_url: string | null;
  industry: string | null;
  goals: string[] | null;
  status: string;
};
export type ClientList = { items: Client[]; next_cursor: string | null };

export function useClients(limit: number) {
  return useQuery({
    queryKey: ["clients", "list", limit],
    queryFn: () => apiFetch<ClientList>(`/clients?limit=${limit}`),
  });
}

export function useClient(id: string) {
  return useQuery({
    queryKey: ["clients", "detail", id],
    queryFn: () => apiFetch<Client>(`/clients/${id}`),
  });
}

export type NewClient = { name: string; website_url?: string; industry?: string };

export function useCreateClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NewClient) =>
      apiFetch<Client>("/clients", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });
}

export type ClientPatch = {
  name?: string;
  website_url?: string | null;
  industry?: string | null;
  goals?: string[] | null;
  status?: "active" | "archived";
};

// ["clients"] is a prefix of both the list and the detail keys, so one invalidation refreshes both.
export function useUpdateClient(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: ClientPatch) =>
      apiFetch<Client>(`/clients/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });
}

/** The API archives (soft delete); restoring is useUpdateClient with { status: "active" }. */
export function useArchiveClient(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>(`/clients/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });
}
