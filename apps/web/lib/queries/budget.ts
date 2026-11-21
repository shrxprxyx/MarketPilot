import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";

export type Budget = {
  monthly_budget_usd: string | null; // null = no budget set
  hard_stop: boolean;
  spent_usd: string;
  percent_used: number | null;
  unpriced_calls: number; // calls with no known price; never counted in spend
  month: string;
};

export type BudgetInput = { monthly_budget_usd: number | null; hard_stop: boolean };

export type Estimate = {
  tokens_in_est: number;
  tokens_out_max: number;
  cost_max_usd: string | null; // null = no price known for the model
  model: string;
};

export function useBudget(enabled = true) {
  return useQuery({
    queryKey: ["budget"],
    queryFn: () => apiFetch<Budget>("/ai/budget"),
    enabled,
  });
}

export function useSaveBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: BudgetInput) =>
      apiFetch<Budget>("/ai/budget", { method: "PUT", body: JSON.stringify(v) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["budget"] }),
  });
}

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

/** Pre-flight estimate for a strategy; builds the prompt on the server, never calls the model. */
export function useEstimate(clientId: string, month: string, enabled: boolean) {
  return useQuery({
    queryKey: ["estimate", clientId, month],
    queryFn: () =>
      apiFetch<Estimate>(
        `/ai/usage/estimate?task=strategy&client_id=${clientId}&month=${month}`,
      ),
    enabled: enabled && MONTH.test(month),
    retry: false, // a 409 (no model set up) is an answer, not a blip
  });
}
