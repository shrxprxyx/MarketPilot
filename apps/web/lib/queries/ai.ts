import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { ConnectionValues, RouteValues } from "@/lib/ai/schemas";

export type AiConnection = {
  id: string;
  provider: string;
  label: string;
  base_url: string | null;
  key_last4: string | null;
  is_active: boolean;
};

export type AiRoute = {
  task_type: string;
  connection_id: string;
  model: string;
  temperature: number;
  max_tokens: number;
  fallback_connection_id: string | null;
  fallback_model: string | null;
};

export type UsageGroup = "day" | "client" | "task" | "model";

export type ConnectionTest = { ok: boolean; models: string[] };

export type UsageRow = {
  key: string | null;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: string; // decimal string from the API
  unpriced_calls: number;
};

// `enabled` lets a role that cannot read this data (the API answers 403) skip the request entirely.
export function useAiConnections(enabled: boolean) {
  return useQuery({
    queryKey: ["ai-connections"],
    queryFn: () => apiFetch<AiConnection[]>("/ai/connections"),
    enabled,
  });
}

export function useAiUsage(enabled: boolean) {
  return useQuery({
    queryKey: ["ai-usage", "day", 30],
    queryFn: () => apiFetch<UsageRow[]>("/ai/usage?group_by=day&days=30"),
    enabled,
  });
}

// Not keepPreviousData: a range switch must not show the old range's numbers as current.
export function useAiUsageBy(groupBy: UsageGroup, days: number, enabled: boolean) {
  return useQuery({
    queryKey: ["ai-usage", groupBy, days],
    queryFn: () => apiFetch<UsageRow[]>(`/ai/usage?group_by=${groupBy}&days=${days}`),
    enabled,
  });
}

export function useAiRoutes(enabled: boolean) {
  return useQuery({
    queryKey: ["ai-routes"],
    queryFn: () => apiFetch<AiRoute[]>("/ai/routes"),
    enabled,
  });
}

export function useCreateConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ConnectionValues) =>
      apiFetch<AiConnection>("/ai/connections", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ai-connections"] }),
  });
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<ConnectionTest>(`/ai/connections/${id}/test`, { method: "POST" }),
  });
}

export function useDeleteConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/ai/connections/${id}`, { method: "DELETE" }),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: ["ai-connections"] }),
        qc.invalidateQueries({ queryKey: ["ai-routes"] }),
      ]),
  });
}

export function useSaveRoutes() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (routes: RouteValues[]) =>
      apiFetch<AiRoute[]>("/ai/routes", { method: "PUT", body: JSON.stringify(routes) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ai-routes"] }),
  });
}
