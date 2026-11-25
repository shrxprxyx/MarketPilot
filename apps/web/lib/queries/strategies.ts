import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";

export type StrategyPlan = {
  summary: string;
  objectives: { title: string; kpis: { name: string; target: string }[] }[];
  channels: { name: string; rationale: string }[];
  risks: { risk: string; mitigation: string }[];
};

export type StrategySource = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  source_type: string;
  excerpt: string;
};

export type Strategy = {
  id: string;
  client_id: string;
  month: string;
  version: number;
  status: string;
  plan: StrategyPlan;
  provider: string;
  model_used: string;
  sources: StrategySource[];
  // Figures in the plan that appear nowhere in the client details or knowledge sources.
  warnings: string[];
  tokens_in: number;
  tokens_out: number;
  cost_usd: string | null; // null = no price known for the model
  created_at: string;
};

export function useStrategies(clientId: string) {
  return useQuery({
    queryKey: ["strategies", clientId],
    queryFn: () => apiFetch<Strategy[]>(`/clients/${clientId}/strategies`),
  });
}

// Idempotency keys of generations that have not succeeded yet, by client and month. Kept outside
// the component so that leaving the tab and trying again still counts as the same request.
const pendingKeys = new Map<string, string>();

// randomUUID exists only on https and localhost; the fallback covers plain http on a LAN.
const newKey = () =>
  globalThis.crypto?.randomUUID?.() ??
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;

export function useGenerateStrategy(clientId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { month: string }) => {
      const request = `${clientId}:${v.month}`;
      const key = pendingKeys.get(request) ?? newKey();
      pendingKeys.set(request, key);
      // Retrying after a lost response reuses the key, so the API returns the strategy it
      // already made instead of calling the model again. (It frees the key if it failed.)
      const strategy = await apiFetch<Strategy>(`/clients/${clientId}/strategies`, {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify(v),
      });
      pendingKeys.delete(request);
      return strategy;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategies", clientId] });
      qc.invalidateQueries({ queryKey: ["budget"] }); // a new call changes this month's spend
    },
  });
}
