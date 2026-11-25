import { apiFetch } from "@/lib/api/client";

type Page<T> = { items: T[]; next_cursor: string | null };

// Follows next_cursor until the list ends. For lists that stay small per agency or client
// (team, invites, one client's strategies), where the screen needs every row at once.
export async function fetchAllPages<T>(path: string): Promise<T[]> {
  const all: T[] = [];
  let cursor: string | null = null;
  do {
    const query: string = cursor ? `?limit=100&cursor=${encodeURIComponent(cursor)}` : "?limit=100";
    const page: Page<T> = await apiFetch<Page<T>>(`${path}${query}`);
    all.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return all;
}
