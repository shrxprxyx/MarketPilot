"use client";

import { useState } from "react";
import { FormError } from "@/components/auth/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/problem";
import { useSession } from "@/lib/auth/session-store";
import {
  PLATFORMS,
  useAddSocialAccount,
  useDeleteSocialAccount,
  useImportExport,
  useSocialAccounts,
  useSocialMetrics,
  type ImportKind,
  type ImportResult,
  type Platform,
  type SocialAccount,
} from "@/lib/queries/social";

const PLATFORM_LABELS: Record<Platform, string> = {
  facebook: "Facebook",
  instagram: "Instagram",
  linkedin: "LinkedIn",
};

const message = (e: unknown) =>
  e instanceof ApiError ? e.detail : "Something went wrong. Please try again.";

const num = (n: number | null | undefined) => (n == null ? "–" : n.toLocaleString());

// ─── Import with preview ─────────────────────────────────────────────────────

function ImportPanel({ account }: { account: SocialAccount }) {
  const importer = useImportExport(account.id);
  const [kind, setKind] = useState<ImportKind>("posts");
  const [file, setFile] = useState<{ format: "csv" | "json"; content: string } | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function pick(f: File | undefined) {
    setPreview(null);
    setSaved(false);
    setError(null);
    if (!f) return setFile(null);
    const format = f.name.toLowerCase().endsWith(".json") ? "json" : "csv";
    setFile({ format, content: await f.text() });
  }

  async function send(commit: boolean) {
    if (!file) return;
    setError(null);
    try {
      const result = await importer.mutateAsync({ kind, ...file, commit });
      setPreview(result);
      setSaved(result.committed);
    } catch (e) {
      setError(message(e));
    }
  }

  return (
    <div className="flex flex-col gap-3 border-t pt-4">
      <h4 className="text-sm font-medium">Import a performance export</h4>
      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label="Export type"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value as ImportKind);
            setPreview(null);
          }}
          className="h-10 w-auto"
        >
          <option value="posts">Posts</option>
          <option value="daily">Daily totals (followers, reach)</option>
        </Select>
        <Input
          aria-label="Export file"
          type="file"
          accept=".csv,.json"
          className="h-10 w-auto"
          onChange={(e) => pick(e.target.files?.[0])}
        />
        <Button
          variant="outline"
          className="h-10 cursor-pointer"
          disabled={!file || importer.isPending}
          onClick={() => send(false)}
        >
          Preview
        </Button>
      </div>
      <FormError message={error} />
      {preview && (
        <div className="flex flex-col gap-2 text-sm">
          <p>
            {preview.valid} of {preview.total} rows are valid
            {preview.errors.length > 0 && `, ${preview.errors.length} have errors`}.
          </p>
          {preview.errors.length > 0 && (
            <ul className="list-disc pl-5 text-destructive">
              {preview.errors.slice(0, 5).map((e) => (
                <li key={e.row}>
                  Row {e.row}: {e.message}
                </li>
              ))}
            </ul>
          )}
          {saved ? (
            <p className="text-muted-foreground">Imported {preview.valid} rows.</p>
          ) : (
            <div>
              <Button
                className="h-10 cursor-pointer"
                disabled={preview.errors.length > 0 || preview.valid === 0 || importer.isPending}
                onClick={() => send(true)}
              >
                Import {preview.valid} rows
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Metrics ─────────────────────────────────────────────────────────────────

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
    </div>
  );
}

function Metrics({ accountId }: { accountId: string }) {
  const { data, isLoading, isError } = useSocialMetrics(accountId);
  if (isLoading) return <Skeleton className="h-20 w-full" />;
  if (isError || !data)
    return <p className="text-sm text-muted-foreground">Couldn&apos;t load metrics.</p>;
  if (data.posts === 0 && !data.followers)
    return <p className="text-sm text-muted-foreground">Import an export to see metrics.</p>;

  const f = data.followers;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Posts" value={num(data.posts)} />
        <Stat
          label="Engagement rate"
          value={data.engagement_rate == null ? "–" : `${data.engagement_rate}%`}
        />
        <Stat
          label="Posts per week"
          value={data.cadence.per_week == null ? "–" : String(data.cadence.per_week)}
        />
        <Stat
          label="Follower growth"
          value={
            f ? `${f.growth >= 0 ? "+" : ""}${num(f.growth)}${f.growth_pct == null ? "" : ` (${f.growth_pct}%)`}` : "–"
          }
        />
      </div>
      <p className="text-sm text-muted-foreground">
        Best day: {data.best_days[0]?.key ?? "–"} · Best format:{" "}
        {data.best_formats[0]?.key ?? "–"} · Best hour (UTC):{" "}
        {data.best_hours_utc[0]?.key ?? "–"}
      </p>
      {data.top_posts.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-medium">Top posts</h4>
          <ul className="flex flex-col gap-1 text-sm">
            {data.top_posts.map((p) => (
              <li key={p.ref} className="flex justify-between gap-4">
                <span className="truncate">{p.title ?? p.ref}</span>
                <span className="shrink-0 text-muted-foreground">
                  {num(p.engagements)} engagements
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.bottom_posts.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-medium">Bottom posts</h4>
          <ul className="flex flex-col gap-1 text-sm">
            {data.bottom_posts.map((p) => (
              <li key={p.ref} className="flex justify-between gap-4">
                <span className="truncate">{p.title ?? p.ref}</span>
                <span className="shrink-0 text-muted-foreground">
                  {num(p.engagements)} engagements
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ─── Root section ────────────────────────────────────────────────────────────

export function SocialSection({ clientId }: { clientId: string }) {
  const role = useSession((s) => s.me?.role);
  const canWrite = role === "admin" || role === "manager";
  const { data, isLoading, isError } = useSocialAccounts(clientId);
  const add = useAddSocialAccount(clientId);
  const remove = useDeleteSocialAccount(clientId);
  const [platform, setPlatform] = useState<Platform>("facebook");
  const [handle, setHandle] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await add.mutateAsync({ platform, handle: handle.trim() });
      setHandle("");
    } catch (err) {
      setError(message(err));
    }
  }

  return (
    <section className="flex max-w-4xl flex-col gap-8">
      <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
        Register this client&apos;s social accounts and import their performance exports to see
        follower growth, engagement and the best times and formats to post.
      </p>

      {canWrite && (
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            <Select
              aria-label="Platform"
              value={platform}
              onChange={(e) => setPlatform(e.target.value as Platform)}
              className="h-11 w-auto"
            >
              {PLATFORMS.map((p) => (
                <option key={p} value={p}>
                  {PLATFORM_LABELS[p]}
                </option>
              ))}
            </Select>
            <Input
              aria-label="Handle"
              placeholder="@handle"
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              className="h-11 w-56"
            />
            <Button
              type="submit"
              className="h-11 cursor-pointer px-4"
              disabled={!handle.trim() || add.isPending}
            >
              Add account
            </Button>
          </div>
          <FormError message={error} />
        </form>
      )}

      {isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">Couldn&apos;t load accounts. Try again later.</p>
      ) : !data?.length ? (
        <p className="border-y py-10 text-sm text-muted-foreground">No social accounts yet</p>
      ) : (
        data.map((account) => (
          <article key={account.id} className="flex flex-col gap-4 rounded-lg border p-4">
            <header className="flex items-center justify-between">
              <h3 className="font-medium">
                {PLATFORM_LABELS[account.platform]} · @{account.handle}
              </h3>
              {canWrite && (
                <Button
                  variant="ghost"
                  className="cursor-pointer text-destructive"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(account.id)}
                >
                  Remove
                </Button>
              )}
            </header>
            <Metrics accountId={account.id} />
            {canWrite && <ImportPanel account={account} />}
          </article>
        ))
      )}
    </section>
  );
}
