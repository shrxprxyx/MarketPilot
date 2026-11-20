/** Only same-origin relative paths are allowed as a post-login redirect target. */
export function safeNext(value: string | null | undefined): string {
  if (
    typeof value === "string" &&
    value.startsWith("/") &&
    !value.startsWith("//") &&
    !value.startsWith("/\\")
  ) {
    return value;
  }
  return "/";
}
