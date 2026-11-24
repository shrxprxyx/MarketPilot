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

export function useGenerateStrategy(clientId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { month: string }) =>
      apiFetch<Strategy>(`/clients/${clientId}/strategies`, {
        method: "POST",
        body: JSON.stringify(v),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategies", clientId] });
      qc.invalidateQueries({ queryKey: ["budget"] }); // a new call changes this month's spend
    },
  });
}
