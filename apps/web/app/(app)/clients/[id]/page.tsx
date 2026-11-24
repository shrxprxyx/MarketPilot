import { Suspense } from "react";
import { ClientPage } from "@/components/clients/client-page";

export const metadata = { title: "Client · MarketPilot" };

// The session gate renders only a skeleton until the client restores the session, so the
// page is never rendered during the dev-time instant-navigation check. Opt out explicitly.
export const instant = false;

// `params` is a Promise in Next 16; with cacheComponents it must be awaited inside Suspense.
async function ClientRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ClientPage id={id} />;
}

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={null}>
      <ClientRoute params={params} />
    </Suspense>
  );
}
