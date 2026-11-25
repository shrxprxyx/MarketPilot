import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/problem";

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

// The API answers 404 until a profile has been saved. That is a normal "empty" result, so it
// resolves to null rather than an error: a refetch of an errored query with no data goes back
// to "loading", which would unmount the form and discard what the user typed.
// No retry, so real errors show immediately instead of after three failed attempts.
export function useBrandProfile(clientId: string) {
  return useQuery({
    queryKey: ["brand-profile", clientId],
    queryFn: async () => {
      try {
        return await apiFetch<BrandProfile>(`/clients/${clientId}/brand-profile`);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
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
