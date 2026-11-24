import { AiSettingsPage } from "@/components/ai/ai-settings-page";

export const metadata = { title: "AI models · MarketPilot" };

// The session gate renders only a skeleton until the client restores the session, so the
// page is never rendered during the dev-time instant-navigation check. Opt out explicitly.
export const instant = false;

export default function Page() {
  return <AiSettingsPage />;
}
