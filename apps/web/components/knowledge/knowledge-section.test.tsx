import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KnowledgeSection } from "@/components/knowledge/knowledge-section";
import { ApiError } from "@/lib/api/problem";
import { useSession, type Role } from "@/lib/auth/session-store";

const doc = (over = {}) => ({
  id: "d1",
  client_id: "c1",
  source_type: "upload",
  title: "Brand guide",
  status: "ready",
  error: null,
  ...over,
});

let list: {
  data?: { items: unknown[]; next_cursor: string | null };
  isLoading: boolean;
  isError: boolean;
} = { data: { items: [doc()], next_cursor: null }, isLoading: false, isError: false };
const upload = vi.fn();
const paste = vi.fn();
const reindex = vi.fn();
const del = vi.fn();
const success = vi.fn();
vi.mock("sonner", () => ({ toast: { success: (...a: unknown[]) => success(...a), error: vi.fn() } }));
vi.mock("@/lib/queries/documents", () => ({
  useDocuments: () => list,
  useUploadDocument: () => ({ mutateAsync: (...a: unknown[]) => upload(...a) }),
  usePasteDocument: () => ({ mutateAsync: (...a: unknown[]) => paste(...a) }),
  useReindexDocument: () => ({ mutateAsync: (...a: unknown[]) => reindex(...a) }),
  useDeleteDocument: () => ({ mutateAsync: (...a: unknown[]) => del(...a) }),
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
const setList = (items: unknown[], next_cursor: string | null = null) => {
  list = { data: { items, next_cursor }, isLoading: false, isError: false };
};

beforeEach(() => {
  setList([doc()]);
  [upload, paste, reindex, del, success].forEach((m) => m.mockReset());
  useSession.getState().clear();
});

describe("document list", () => {
  it("shows title, source type and a status badge for each document", () => {
    as("manager");
    setList([
      doc(),
      doc({ id: "d2", title: "Pending doc", status: "pending", source_type: "brand_doc" }),
    ]);
    render(<KnowledgeSection clientId="c1" />);
    expect(screen.getByText("Brand guide")).toBeInTheDocument();
    expect(screen.getByText("Upload")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Indexing…")).toBeInTheDocument();
    expect(screen.getByText("Brand doc")).toBeInTheDocument();
  });

  it("labels the auto-managed brand profile and offers re-index but not delete", () => {
    as("manager");
    setList([doc({ title: "Brand profile", source_type: "brand_profile" })]);
    render(<KnowledgeSection clientId="c1" />);
    expect(screen.getByText("Auto")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-index Brand profile" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete Brand profile" })).not.toBeInTheDocument();
  });

  it("does not mark ordinary documents as auto", () => {
    as("manager");
    render(<KnowledgeSection clientId="c1" />);
    expect(screen.queryByText("Auto")).not.toBeInTheDocument();
  });

  it("shows the error text for a failed document", () => {
    as("manager");
    setList([doc({ status: "failed", error: "Could not read this PDF." })]);
    render(<KnowledgeSection clientId="c1" />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Could not read this PDF.")).toBeInTheDocument();
  });

  it("shows skeletons while loading, an empty state, and an error state", () => {
    as("manager");
    list = { isLoading: true, isError: false };
    const { rerender } = render(<KnowledgeSection clientId="c1" />);
    expect(screen.getAllByTestId("doc-skeleton").length).toBeGreaterThan(0);
    setList([]);
    rerender(<KnowledgeSection clientId="c1" />);
    expect(screen.getByText("No documents yet")).toBeInTheDocument();
    list = { isLoading: false, isError: true };
    rerender(<KnowledgeSection clientId="c1" />);
    expect(screen.getByText(/couldn.t load documents/i)).toBeInTheDocument();
  });

  it("notes when only the first 100 documents are shown", () => {
    as("manager");
    setList([doc()], "abc");
    render(<KnowledgeSection clientId="c1" />);
    expect(screen.getByText("Showing the first 100 documents")).toBeInTheDocument();
  });
});

describe("roles", () => {
  it("gives members the list only: no add panel, no re-index, no delete", () => {
    as("member");
    render(<KnowledgeSection clientId="c1" />);
    expect(screen.getByText("Brand guide")).toBeInTheDocument();
    expect(screen.queryByLabelText("Upload file")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add text" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /re-index/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^delete/i })).not.toBeInTheDocument();
  });
});

describe("re-index and delete", () => {
  it("re-indexes with the document id", async () => {
    as("manager");
    reindex.mockResolvedValue({});
    render(<KnowledgeSection clientId="c1" />);
    await userEvent.click(screen.getByRole("button", { name: "Re-index Brand guide" }));
    expect(reindex).toHaveBeenCalledWith("d1");
  });

  it("deletes only after the user confirms", async () => {
    as("manager");
    del.mockResolvedValue(undefined);
    render(<KnowledgeSection clientId="c1" />);
    await userEvent.click(screen.getByRole("button", { name: "Delete Brand guide" }));
    expect(del).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: "Delete document" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("d1"));
  });

  it("shows the API detail and keeps the row when a delete is rejected", async () => {
    as("manager");
    del.mockRejectedValue(new ApiError(403, "Forbidden", "Not allowed."));
    render(<KnowledgeSection clientId="c1" />);
    await userEvent.click(screen.getByRole("button", { name: "Delete Brand guide" }));
    await userEvent.click(await screen.findByRole("button", { name: "Delete document" }));
    expect(await screen.findByText("Not allowed.")).toBeInTheDocument();
    expect(screen.getByText("Brand guide")).toBeInTheDocument();
  });
});

describe("upload", () => {
  const file = (name: string, size = 100) => {
    const f = new File(["x"], name);
    Object.defineProperty(f, "size", { value: size });
    return f;
  };

  it("blocks a wrong file type without sending anything", async () => {
    as("manager");
    render(<KnowledgeSection clientId="c1" />);
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(screen.getByLabelText("Upload file"), file("photo.png"));
    expect(await screen.findByText("Use a PDF, DOCX, TXT or MD file")).toBeInTheDocument();
    expect(upload).not.toHaveBeenCalled();
  });

  it("blocks a file over 10 MB without sending anything", async () => {
    as("manager");
    render(<KnowledgeSection clientId="c1" />);
    await userEvent.upload(
      screen.getByLabelText("Upload file"),
      file("big.pdf", 10 * 1024 * 1024 + 1),
    );
    expect(await screen.findByText("Files must be 10 MB or smaller")).toBeInTheDocument();
    expect(upload).not.toHaveBeenCalled();
  });

  it("uploads a valid file and says indexing started", async () => {
    as("manager");
    upload.mockResolvedValue({ ...doc(), duplicate: false });
    render(<KnowledgeSection clientId="c1" />);
    const f = file("brief.pdf");
    await userEvent.upload(screen.getByLabelText("Upload file"), f);
    await waitFor(() => expect(upload).toHaveBeenCalledWith(f));
    expect(success).toHaveBeenCalledWith("Uploaded - indexing started");
  });

  it("says Already added when the API reports a duplicate", async () => {
    as("manager");
    upload.mockResolvedValue({ ...doc(), duplicate: true });
    render(<KnowledgeSection clientId="c1" />);
    await userEvent.upload(screen.getByLabelText("Upload file"), file("brief.pdf"));
    await waitFor(() => expect(success).toHaveBeenCalledWith("Already added"));
  });

  it("shows the API detail when an upload is rejected", async () => {
    as("manager");
    upload.mockRejectedValue(new ApiError(422, "Unprocessable", "Could not read this file."));
    render(<KnowledgeSection clientId="c1" />);
    await userEvent.upload(screen.getByLabelText("Upload file"), file("brief.pdf"));
    expect(await screen.findByText("Could not read this file.")).toBeInTheDocument();
  });
});

describe("paste text", () => {
  async function fill(title: string, text: string) {
    if (title) await userEvent.type(screen.getByLabelText("Title"), title);
    if (text) await userEvent.type(screen.getByLabelText("Text"), text);
    await userEvent.click(screen.getByRole("button", { name: "Add text" }));
  }

  it("requires a title and text and sends nothing without them", async () => {
    as("manager");
    render(<KnowledgeSection clientId="c1" />);
    await fill("", "");
    expect(await screen.findByText("Title is required")).toBeInTheDocument();
    expect(screen.getByText("Text is required")).toBeInTheDocument();
    expect(paste).not.toHaveBeenCalled();
  });

  it("sends the title and text, then clears the form", async () => {
    as("manager");
    paste.mockResolvedValue({ ...doc(), duplicate: false });
    render(<KnowledgeSection clientId="c1" />);
    await fill("Voice notes", "We are playful.");
    await waitFor(() =>
      expect(paste).toHaveBeenCalledWith({ title: "Voice notes", text: "We are playful." }),
    );
    await waitFor(() => expect(screen.getByLabelText("Title")).toHaveValue(""));
  });

  it("keeps the typed title and text and shows the detail when it fails", async () => {
    as("manager");
    paste.mockRejectedValue(new ApiError(422, "Unprocessable", "Text is too long."));
    render(<KnowledgeSection clientId="c1" />);
    await fill("Voice notes", "We are playful.");
    expect(await screen.findByText("Text is too long.")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Voice notes");
    expect(screen.getByLabelText("Text")).toHaveValue("We are playful.");
  });
});
