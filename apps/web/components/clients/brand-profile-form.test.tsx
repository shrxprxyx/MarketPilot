import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrandProfileForm } from "@/components/clients/brand-profile-form";
import { ApiError } from "@/lib/api/problem";
import { useSession, type Role } from "@/lib/auth/session-store";

const profile = {
  id: "p1",
  client_id: "c1",
  voice: "Warm",
  tone: "Playful",
  audience: "Millennials",
  keywords: ["dogs", "treats"],
  do_rules: ["Use emojis"],
  dont_rules: null,
  sample_text: "Hi there",
};

let query: { data?: unknown; isLoading: boolean; error: unknown } = {
  data: profile,
  isLoading: false,
  error: null,
};
const save = vi.fn();
const success = vi.fn();
vi.mock("sonner", () => ({ toast: { success: (...a: unknown[]) => success(...a), error: vi.fn() } }));
vi.mock("@/lib/queries/brand-profile", () => ({
  useBrandProfile: () => query,
  useSaveBrandProfile: () => ({ mutateAsync: (...a: unknown[]) => save(...a) }),
}));

function as(role: Role) {
  useSession.getState().setSession("t", {
    user_id: "u",
    tenant_id: "t",
    role,
    email: "a@b.co",
    tenant_name: "Acme Agency",
  });
}
const saveBtn = () => screen.getByRole("button", { name: "Save profile" });

beforeEach(() => {
  query = { data: profile, isLoading: false, error: null };
  save.mockReset();
  success.mockReset();
  useSession.getState().clear();
});

describe("BrandProfileForm", () => {
  it("shows a skeleton while loading", () => {
    as("manager");
    query = { isLoading: true, error: null };
    render(<BrandProfileForm clientId="c1" />);
    expect(screen.getByTestId("profile-skeleton")).toBeInTheDocument();
  });

  it("renders an empty editable form when no profile exists yet", () => {
    as("manager");
    query = { data: null, isLoading: false, error: null };
    render(<BrandProfileForm clientId="c1" />);
    expect(screen.getByLabelText("Voice")).toHaveValue("");
  });

  it("shows the detail, not an empty form, for any other load error", () => {
    as("manager");
    query = { isLoading: false, error: new ApiError(500, "Error", "Server exploded.") };
    render(<BrandProfileForm clientId="c1" />);
    expect(screen.getByText("Server exploded.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Voice")).not.toBeInTheDocument();
  });

  it("prefills from the saved profile, one list item per line", () => {
    as("manager");
    render(<BrandProfileForm clientId="c1" />);
    expect(screen.getByLabelText("Voice")).toHaveValue("Warm");
    expect(screen.getByLabelText("Tone")).toHaveValue("Playful");
    expect(screen.getByLabelText("Audience")).toHaveValue("Millennials");
    expect(screen.getByLabelText("Keywords (one per line)")).toHaveValue("dogs\ntreats");
    expect(screen.getByLabelText("Do rules (one per line)")).toHaveValue("Use emojis");
    expect(screen.getByLabelText("Don't rules (one per line)")).toHaveValue("");
    expect(screen.getByLabelText("Sample text")).toHaveValue("Hi there");
  });

  it("makes every field read-only for members and offers no Save", () => {
    as("member");
    render(<BrandProfileForm clientId="c1" />);
    for (const label of ["Voice", "Tone", "Audience", "Keywords (one per line)", "Sample text"]) {
      expect(screen.getByLabelText(label)).toHaveAttribute("readonly");
    }
    expect(screen.queryByRole("button", { name: "Save profile" })).not.toBeInTheDocument();
  });

  it("keeps Save disabled until something changes", async () => {
    as("manager");
    render(<BrandProfileForm clientId="c1" />);
    expect(saveBtn()).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Tone"), "!");
    expect(saveBtn()).toBeEnabled();
  });

  it("sends ALL fields when only one was edited, so nothing else is wiped", async () => {
    as("manager");
    save.mockResolvedValue({});
    render(<BrandProfileForm clientId="c1" />);
    const tone = screen.getByLabelText("Tone");
    await userEvent.clear(tone);
    await userEvent.type(tone, "Bold");
    await userEvent.click(saveBtn());
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith({
      voice: "Warm",
      tone: "Bold",
      audience: "Millennials",
      keywords: ["dogs", "treats"],
      do_rules: ["Use emojis"],
      dont_rules: null,
      sample_text: "Hi there",
    });
  });

  it("sends blank text as null and trims lists, dropping blank lines", async () => {
    as("manager");
    save.mockResolvedValue({});
    query = { data: null, isLoading: false, error: null };
    render(<BrandProfileForm clientId="c1" />);
    await userEvent.type(screen.getByLabelText("Voice"), "Warm");
    await userEvent.type(screen.getByLabelText("Keywords (one per line)"), "a{Enter}{Enter}  b  ");
    await userEvent.click(saveBtn());
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith({
      voice: "Warm",
      tone: null,
      audience: null,
      keywords: ["a", "b"],
      do_rules: null,
      dont_rules: null,
      sample_text: null,
    });
  });

  it("blocks a voice longer than 120 characters without sending", async () => {
    as("manager");
    render(<BrandProfileForm clientId="c1" />);
    const voice = screen.getByLabelText("Voice");
    await userEvent.clear(voice);
    await userEvent.click(voice);
    await userEvent.paste("x".repeat(121));
    await userEvent.click(saveBtn());
    expect(await screen.findByText("Voice must be 120 characters or fewer")).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("toasts on success and disables Save again", async () => {
    as("manager");
    save.mockResolvedValue({});
    render(<BrandProfileForm clientId="c1" />);
    await userEvent.type(screen.getByLabelText("Tone"), "!");
    await userEvent.click(saveBtn());
    await waitFor(() => expect(success).toHaveBeenCalled());
    await waitFor(() => expect(saveBtn()).toBeDisabled());
  });

  it("shows the API detail and keeps the input when saving fails", async () => {
    as("manager");
    save.mockRejectedValue(new ApiError(403, "Forbidden", "Not allowed."));
    render(<BrandProfileForm clientId="c1" />);
    await userEvent.type(screen.getByLabelText("Tone"), "!");
    await userEvent.click(saveBtn());
    expect(await screen.findByText("Not allowed.")).toBeInTheDocument();
    expect(screen.getByLabelText("Tone")).toHaveValue("Playful!");
  });
});
