import { useSession, type Me } from "@/lib/auth/session-store";

const me: Me = { user_id: "u1", tenant_id: "t1", role: "admin" };

describe("session store", () => {
  beforeEach(() => {
    useSession.getState().clear();
    useSession.setState({ status: "unknown" });
  });

  it("starts unknown with no token", () => {
    const s = useSession.getState();
    expect(s.status).toBe("unknown");
    expect(s.accessToken).toBeNull();
    expect(s.me).toBeNull();
  });

  it("setSession stores the token and user and marks authenticated", () => {
    useSession.getState().setSession("tok", me);
    const s = useSession.getState();
    expect(s.status).toBe("authenticated");
    expect(s.accessToken).toBe("tok");
    expect(s.me).toEqual(me);
  });

  it("clear marks anonymous and drops token and user", () => {
    useSession.getState().setSession("tok", me);
    useSession.getState().clear();
    const s = useSession.getState();
    expect(s.status).toBe("anonymous");
    expect(s.accessToken).toBeNull();
    expect(s.me).toBeNull();
  });

  it("never writes the token to web storage", () => {
    useSession.getState().setSession("secret-token", me);
    expect(JSON.stringify({ ...localStorage })).not.toContain("secret-token");
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("secret-token");
  });
});
