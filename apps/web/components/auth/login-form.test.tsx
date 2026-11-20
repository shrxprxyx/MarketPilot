import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginForm } from "@/components/auth/login-form";
import { ApiError } from "@/lib/api/problem";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(search),
}));

const signIn = vi.fn();
vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client");
  return { ...actual, signIn: (...a: unknown[]) => signIn(...a) };
});

beforeEach(() => {
  replace.mockReset();
  signIn.mockReset();
  search = "";
});

async function fill(email: string, password: string) {
  const user = userEvent.setup();
  if (email) await user.type(screen.getByLabelText("Email"), email);
  if (password) await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: /sign in/i }));
}

describe("LoginForm", () => {
  it("shows field errors and sends nothing when submitted empty", async () => {
    render(<LoginForm />);
    await fill("", "");
    expect(await screen.findByText("Enter a valid email")).toBeInTheDocument();
    expect(screen.getByText("Password is required")).toBeInTheDocument();
    expect(signIn).not.toHaveBeenCalled();
  });

  it("shows the API problem detail inline and does not navigate on a 401", async () => {
    signIn.mockRejectedValue(new ApiError(401, "Unauthorized", "Invalid credentials."));
    render(<LoginForm />);
    await fill("a@b.co", "wrong-password");
    expect(await screen.findByText("Invalid credentials.")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows a friendly message when the server can't be reached", async () => {
    signIn.mockRejectedValue(new ApiError(0, "Network error", "Can't reach the server. Please try again."));
    render(<LoginForm />);
    await fill("a@b.co", "whatever-password");
    expect(await screen.findByText("Can't reach the server. Please try again.")).toBeInTheDocument();
  });

  it("disables the button while the request is pending", async () => {
    signIn.mockReturnValue(new Promise(() => {}));
    render(<LoginForm />);
    await fill("a@b.co", "whatever-password");
    await waitFor(() => expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled());
  });

  it("sends the credentials and goes to the next path on success", async () => {
    signIn.mockResolvedValue(undefined);
    search = "next=%2Fclients";
    render(<LoginForm />);
    await fill("a@b.co", "correct-horse-1");
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/clients"));
    expect(signIn).toHaveBeenCalledWith("login", { email: "a@b.co", password: "correct-horse-1" });
  });

  it("ignores an unsafe next parameter", async () => {
    signIn.mockResolvedValue(undefined);
    search = "next=%2F%2Fevil.com";
    render(<LoginForm />);
    await fill("a@b.co", "correct-horse-1");
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });
});
