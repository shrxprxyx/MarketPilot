import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";

export type Platform = "facebook" | "instagram" | "linkedin";
export const PLATFORMS: Platform[] = ["facebook", "instagram", "linkedin"];

export type SocialAccount = {
  id: string;
  client_id: string;
  platform: Platform;
  handle: string;
  created_at: string;
};

export type ImportKind = "posts" | "daily";
export type ImportResult = {
  committed: boolean;
  total: number;
  valid: number;
  errors: { row: number; message: string }[];
  sample: Record<string, unknown>[];
};

type Ranked = { key: string | number; posts: number; avg_engagements: number };
type PostBrief = {
  ref: string;
  title: string | null;
  format: string | null;
  posted_at: string;
  engagements: number;
  impressions: number;
};

export type SocialMetrics = {
  platform: Platform;
  handle: string;
  posts: number;
  followers: { start: number; end: number; growth: number; growth_pct: number | null } | null;
  engagement_rate: number | null;
  trend: { week: string; reach: number; impressions: number }[];
  cadence: { posts: number; per_week: number | null };
  best_days: Ranked[];
  best_hours_utc: Ranked[];
  best_formats: Ranked[];
  top_posts: PostBrief[];
  bottom_posts: PostBrief[];
};

export function useSocialAccounts(clientId: string) {
  return useQuery({
    queryKey: ["social-accounts", clientId],
    queryFn: () => apiFetch<SocialAccount[]>(`/clients/${clientId}/social-accounts`),
  });
}

export function useAddSocialAccount(clientId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { platform: Platform; handle: string }) =>
      apiFetch<SocialAccount>(`/clients/${clientId}/social-accounts`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["social-accounts", clientId] }),
  });
}

export function useDeleteSocialAccount(clientId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) =>
      apiFetch<void>(`/social-accounts/${accountId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["social-accounts", clientId] }),
  });
}

export function useImportExport(accountId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      kind: ImportKind;
      format: "csv" | "json";
      content: string;
      commit: boolean;
    }) =>
      apiFetch<ImportResult>(`/social-accounts/${accountId}/import`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (result) => {
      if (result.committed) qc.invalidateQueries({ queryKey: ["social-metrics", accountId] });
    },
  });
}

export function useSocialMetrics(accountId: string) {
  return useQuery({
    queryKey: ["social-metrics", accountId],
    queryFn: () => apiFetch<SocialMetrics>(`/social-accounts/${accountId}/metrics`),
  });
}
