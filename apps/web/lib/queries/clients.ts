import { useQuery } from "@tanstack/react-query";
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
