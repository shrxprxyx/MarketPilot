import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import { useSession } from "@/lib/auth/session-store";

export type Branding = {
  logo_url: string | null;
  primary_color: string | null;
  report_footer: string | null;
};

export type TenantDetail = {
  id: string;
  name: string;
  slug: string;
  plan: string;
  branding: Branding;
};

/** The current agency's settings and white-label branding (every role may read). */
export function useTenantDetail(enabled = true) {
  return useQuery({
    queryKey: ["tenant"],
    queryFn: () => apiFetch<TenantDetail>("/tenant"),
    enabled,
  });
}

function useAfterSave() {
  const qc = useQueryClient();
  return (detail: TenantDetail) => {
    qc.setQueryData(["tenant"], detail);
    qc.invalidateQueries({ queryKey: ["tenants"] }); // the agency switcher lists names
    // The shell shows the agency name from the session; keep it in step with the rename.
    const { accessToken, me, setSession } = useSession.getState();
    if (accessToken && me && me.tenant_name !== detail.name) {
      setSession(accessToken, { ...me, tenant_name: detail.name });
    }
  };
}

export function useRenameTenant() {
  const afterSave = useAfterSave();
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<TenantDetail>("/tenant", { method: "PATCH", body: JSON.stringify({ name }) }),
    onSuccess: afterSave,
  });
}

/** PUT replaces the whole branding block: a null clears that field. */
export function useSaveBranding() {
  const afterSave = useAfterSave();
  return useMutation({
    mutationFn: (branding: Branding) =>
      apiFetch<TenantDetail>("/tenant/branding", {
        method: "PUT",
        body: JSON.stringify(branding),
      }),
    onSuccess: afterSave,
  });
}
