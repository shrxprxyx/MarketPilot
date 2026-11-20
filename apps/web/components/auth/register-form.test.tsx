import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RegisterForm } from "@/components/auth/register-form";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const signIn = vi.fn();
vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client");
  return { ...actual, signIn: (...a: unknown[]) => signIn(...a) };
});

beforeEach(() => signIn.mockReset());

describe("RegisterForm", () => {
  it("blocks a password under 10 characters before any request", async () => {
    const user = userEvent.setup();
    render(<RegisterForm />);
    await user.type(screen.getByLabelText("Agency name"), "Acme");
    await user.type(screen.getByLabelText("Email"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByText("Use at least 10 characters")).toBeInTheDocument();
    expect(signIn).not.toHaveBeenCalled();
  });

  it("registers with the agency name as tenant_name", async () => {
    signIn.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<RegisterForm />);
    await user.type(screen.getByLabelText("Agency name"), "Acme");
    await user.type(screen.getByLabelText("Email"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "correct-horse-1");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    await vi.waitFor(() =>
      expect(signIn).toHaveBeenCalledWith("register", {
        email: "a@b.co",
        password: "correct-horse-1",
        tenant_name: "Acme",
      }),
    );
  });
});
