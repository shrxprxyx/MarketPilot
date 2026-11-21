import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";

export type BrandProfile = {
  id: string;
  client_id: string;
  voice: string | null;
  tone: string | null;
  audience: string | null;
  keywords: string[] | null;
  do_rules: string[] | null;
  dont_rules: string[] | null;
  sample_text: string | null;
};

export type BrandProfileInput = Omit<BrandProfile, "id" | "client_id">;

// The API answers 404 until a profile has been saved; the form treats that as "empty".
// No retry, so the empty form appears immediately instead of after three failed attempts.
export function useBrandProfile(clientId: string) {
  return useQuery({
    queryKey: ["brand-profile", clientId],
    queryFn: () => apiFetch<BrandProfile>(`/clients/${clientId}/brand-profile`),
    retry: false,
  });
}

// PUT replaces the whole profile, so callers must always send every field.
export function useSaveBrandProfile(clientId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: BrandProfileInput) =>
      apiFetch<BrandProfile>(`/clients/${clientId}/brand-profile`, {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["brand-profile", clientId] }),
  });
}
