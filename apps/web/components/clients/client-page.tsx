"use client";

import Link from "next/link";
import { AuditsSection } from "@/components/audits/audits-section";
import { BrandProfileForm } from "@/components/clients/brand-profile-form";
import { ClientOverview } from "@/components/clients/client-overview";
import { KnowledgeSection } from "@/components/knowledge/knowledge-section";
import { StrategySection } from "@/components/strategy/strategy-section";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api/problem";
import { useClient } from "@/lib/queries/clients";

const BackLink = () => (
  <Link
    href="/clients"
    className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
  >
    Back to clients
  </Link>
);

export function ClientPage({ id }: { id: string }) {
  const { data: client, isLoading, error } = useClient(id);

  if (isLoading) {
    return <Skeleton data-testid="client-skeleton" className="h-40 w-full max-w-4xl" />;
  }

  if (error || !client) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <div className="flex max-w-2xl flex-col gap-4">
        <h1 className="font-heading text-3xl font-semibold tracking-tight">
          {notFound ? "Client not found" : "Couldn't load this client"}
        </h1>
        {!notFound && (
          <p className="text-sm text-muted-foreground">
            {error instanceof ApiError ? error.detail : "Something went wrong. Please try again."}
          </p>
        )}
        <BackLink />
      </div>
    );
  }

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <header>
        <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          <Link href="/clients" className="hover:text-foreground">
            Clients
          </Link>
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="break-words font-heading text-4xl font-semibold leading-tight tracking-tight">
            {client.name}
          </h1>
          {client.status === "archived" && <Badge variant="outline">Archived</Badge>}
        </div>
      </header>

      <Tabs defaultValue="overview">
        <TabsList variant="line">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="brand">Brand profile</TabsTrigger>
          <TabsTrigger value="knowledge">Knowledge</TabsTrigger>
          <TabsTrigger value="strategy">Strategy</TabsTrigger>
          <TabsTrigger value="audits">Audits</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="pt-6">
          <ClientOverview client={client} />
        </TabsContent>
        {/* keepMounted: switching tabs must not discard unsaved edits in the form. */}
        <TabsContent value="brand" keepMounted className="pt-6">
          <BrandProfileForm clientId={client.id} />
        </TabsContent>
        <TabsContent value="knowledge" className="pt-6">
          <KnowledgeSection clientId={client.id} />
        </TabsContent>
        <TabsContent value="strategy" className="pt-6">
          <StrategySection clientId={client.id} />
        </TabsContent>
        <TabsContent value="audits" className="pt-6">
          <AuditsSection clientId={client.id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
