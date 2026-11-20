import { SessionGate } from "@/components/session-gate";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <SessionGate>{children}</SessionGate>;
}
