"use client";

import { Copy, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { FormError } from "@/components/auth/auth-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/problem";
import { useSession, type Role } from "@/lib/auth/session-store";
import {
  useInviteMember,
  useMembers,
  usePendingInvites,
  useRevokeInvite,
  useUpdateMember,
  type Member,
} from "@/lib/queries/members";

const ROLES: Role[] = ["admin", "manager", "member"];
const detailOf = (e: unknown) =>
  e instanceof ApiError ? e.detail : "Something went wrong. Please try again.";

function InviteDialog() {
  const invite = useInviteMember();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setEmail("");
      setRole("member");
      setError(null);
      setLink(null);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const created = await invite.mutateAsync({ email: email.trim(), role });
      // The raw token is only returned once, so the link is built here and shown for copying.
      setLink(`${window.location.origin}/accept-invite?token=${created.invite_token}`);
    } catch (err) {
      setError(detailOf(err));
    }
  }

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      toast.success("Invite link copied");
    } catch {
      toast.error("Could not copy. Select the link and copy it manually.");
    }
  }

  return (
    <>
      <Button className="h-10 px-4" onClick={() => setOpen(true)}>
        <Plus className="size-4" /> Invite member
      </Button>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{link ? "Invite created" : "Invite a teammate"}</DialogTitle>
            <DialogDescription>
              {link
                ? "Share this link with them. It is shown only once."
                : "They join with the role you choose. You get a link to share."}
            </DialogDescription>
          </DialogHeader>
          {link ? (
            <div className="flex flex-col gap-3">
              <Input readOnly value={link} aria-label="Invite link" className="font-mono text-xs" />
              <Button onClick={copy} className="h-11">
                <Copy className="size-4" /> Copy link
              </Button>
            </div>
          ) : (
            <form noValidate onSubmit={submit} className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="invite-email">Email</Label>
                <Input
                  id="invite-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-11"
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="invite-role">Role</Label>
                <Select
                  id="invite-role"
                  value={role}
                  onChange={(e) => setRole(e.target.value as Role)}
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </Select>
              </div>
              <FormError message={error} />
              <Button type="submit" size="lg" className="h-11 w-full" disabled={invite.isPending}>
                {invite.isPending ? "Creating…" : "Create invite"}
              </Button>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function MemberRow({ member, isSelf }: { member: Member; isSelf: boolean }) {
  const update = useUpdateMember();
  const [error, setError] = useState<string | null>(null);
  const deactivated = member.status !== "active";

  async function patch(p: { role?: Role; status?: "active" | "deactivated" }) {
    setError(null);
    try {
      await update.mutateAsync({ id: member.id, patch: p });
    } catch (e) {
      setError(detailOf(e));
    }
  }

  return (
    <li className="flex flex-col gap-2 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">
            {member.email}
            {isSelf && <span className="ml-2 text-xs text-muted-foreground">(you)</span>}
          </p>
          {deactivated && (
            <Badge variant="outline" className="mt-1">
              deactivated
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Select
            aria-label={`Role for ${member.email}`}
            value={member.role}
            disabled={update.isPending}
            onChange={(e) => patch({ role: e.target.value as Role })}
            className="h-9 w-32"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
          <Button
            variant="outline"
            disabled={update.isPending}
            onClick={() => patch({ status: deactivated ? "active" : "deactivated" })}
          >
            {deactivated ? "Reactivate" : "Deactivate"}
          </Button>
        </div>
      </div>
      <FormError message={error} />
    </li>
  );
}

function InviteRow({ id, email, role }: { id: string; email: string; role: Role }) {
  const revoke = useRevokeInvite();
  return (
    <li className="flex items-center justify-between gap-3 py-4">
      <p className="min-w-0 truncate">
        {email} <span className="text-xs text-muted-foreground">· {role}</span>
      </p>
      <Button
        variant="outline"
        disabled={revoke.isPending}
        onClick={() =>
          revoke
            .mutateAsync(id)
            .then(() => toast.success("Invite revoked"))
            .catch((e) => toast.error(detailOf(e)))
        }
      >
        Revoke
      </Button>
    </li>
  );
}

export function TeamPage() {
  const me = useSession((s) => s.me);
  const isAdmin = me?.role === "admin";
  // Admin-only on the API; `enabled` keeps other roles from sending the requests.
  const members = useMembers(isAdmin);
  const invites = usePendingInvites(isAdmin);

  if (!me) return null;

  return (
    <div className="flex max-w-3xl flex-col gap-12">
      <header className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            Workspace
          </p>
          <h1 className="font-heading text-4xl font-semibold leading-tight tracking-tight">
            Team
          </h1>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            Invite teammates, change roles and manage access.
          </p>
        </div>
        {isAdmin && <InviteDialog />}
      </header>

      {!isAdmin ? (
        <p className="border-y py-10 text-sm text-muted-foreground">
          Only admins can manage the team. Ask an admin if you need a change.
        </p>
      ) : (
        <>
          <section aria-labelledby="members-heading">
            <h2 id="members-heading" className="mb-2 text-lg font-medium">
              Members
            </h2>
            {members.isLoading ? (
              <Skeleton data-testid="member-skeleton" className="h-16 w-full" />
            ) : members.isError ? (
              <p role="alert" className="text-sm text-destructive">
                Could not load members.
              </p>
            ) : (
              <ul className="divide-y border-y">
                {(members.data ?? []).map((m) => (
                  <MemberRow key={m.id} member={m} isSelf={m.user_id === me.user_id} />
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="invites-heading">
            <h2 id="invites-heading" className="mb-2 text-lg font-medium">
              Pending invites
            </h2>
            {invites.isError ? (
              <p role="alert" className="text-sm text-destructive">
                Could not load invites.
              </p>
            ) : (invites.data ?? []).length === 0 ? (
              <p className="border-y py-6 text-sm text-muted-foreground">No pending invites.</p>
            ) : (
              <ul className="divide-y border-y">
                {(invites.data ?? []).map((i) => (
                  <InviteRow key={i.id} id={i.id} email={i.email} role={i.role} />
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
