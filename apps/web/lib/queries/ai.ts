import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";

export type AiConnection = {
  id: string;
  provider: string;
  label: string;
  base_url: string | null;
  key_last4: string | null;
  is_active: boolean;
};

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
