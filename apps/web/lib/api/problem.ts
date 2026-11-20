export class ApiError extends Error {
  constructor(
    public status: number,
    public title: string,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

export const GENERIC_DETAIL = "Something went wrong. Please try again.";

export function networkError(): ApiError {
  return new ApiError(0, "Network error", "Can't reach the server. Please try again.");
}

/** Turns an error response (RFC 7807 or anything else) into an ApiError. */
export async function parseProblem(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    if (body && typeof body === "object") {
      const detail =
        typeof body.detail === "string" ? body.detail : GENERIC_DETAIL;
      const title = typeof body.title === "string" ? body.title : "Error";
      return new ApiError(res.status, title, detail);
    }
  } catch {
    // body was not JSON
  }
  return new ApiError(res.status, "Error", GENERIC_DETAIL);
}
