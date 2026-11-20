import { create } from "zustand";

export type Role = "admin" | "manager" | "member";

export type Me = {
  user_id: string;
  tenant_id: string;
  role: Role;
  email: string;
  tenant_name: string;
};

type SessionState = {
  accessToken: string | null;
  me: Me | null;
  status: "unknown" | "authenticated" | "anonymous";
  setSession: (accessToken: string, me: Me) => void;
  clear: () => void;
};

// In memory only: the access token is never persisted (SRS section 11).
export const useSession = create<SessionState>((set) => ({
  accessToken: null,
  me: null,
  status: "unknown",
  setSession: (accessToken, me) =>
    set({ accessToken, me, status: "authenticated" }),
  clear: () => set({ accessToken: null, me: null, status: "anonymous" }),
}));
