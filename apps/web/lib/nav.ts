import type { Role } from "@/lib/auth/session-store";

export type NavItem = { label: string; href: string; number: string };
export type NavSection = { label: string; items: NavItem[] };

const ALL: Role[] = ["admin", "manager", "member"];
const MANAGERS: Role[] = ["admin", "manager"];

// One declarative table: which roles see which sidebar item (mirrors the API's role checks).
const SECTIONS: {
  label: string;
  items: { label: string; href: string; roles: Role[] }[];
}[] = [
  {
    label: "A · WORKSPACE",
    items: [
      { label: "Dashboard", href: "/", roles: ALL },
      { label: "Clients", href: "/clients", roles: ALL },
      { label: "Team", href: "/team", roles: ["admin"] },
    ],
  },
  {
    label: "B · AI",
    items: [
      { label: "AI models", href: "/settings/ai", roles: MANAGERS },
      { label: "Usage", href: "/usage", roles: MANAGERS },
    ],
  },
  {
    label: "C · SETTINGS",
    items: [{ label: "Agency", href: "/settings/agency", roles: ["admin"] }],
  },
];

/** Sections and items a role may see, numbered continuously (01, 02, ...). */
export function navFor(role: Role): NavSection[] {
  let n = 0;
  return SECTIONS.map((section) => ({
    label: section.label,
    items: section.items
      .filter((item) => item.roles.includes(role))
      .map((item) => ({
        label: item.label,
        href: item.href,
        number: String(++n).padStart(2, "0"),
      })),
  })).filter((section) => section.items.length > 0);
}

export function isActive(href: string, pathname: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The page name for a path (nested routes use their parent item), or null if unknown. */
export function pageLabel(pathname: string): string | null {
  const match = SECTIONS.flatMap((s) => s.items)
    .filter((item) => isActive(item.href, pathname))
    .sort((a, b) => b.href.length - a.href.length)[0];
  return match?.label ?? null;
}
