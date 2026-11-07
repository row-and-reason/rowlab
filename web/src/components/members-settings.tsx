"use client";

import { EllipsisIcon, MailIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useCan, useMe } from "@/components/me";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Field, FieldDescription, FieldError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@/components/ui/item";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { api, type Members, type Role } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

const ROLES: { value: Role; label: string; description: string }[] = [
  { value: "admin", label: "Admin", description: "Everything, and settings and members" },
  { value: "member", label: "Member", description: "Add data, run tasks and export" },
  { value: "verifier", label: "Verifier", description: "Look at the data; no exports" },
];
const roleLabel = (role: Role) => ROLES.find((r) => r.value === role)!.label;

/** The organisation's members and invites. Admins invite people, change roles and remove them. */
export function MembersSettings() {
  const me = useMe();
  const canAdmin = useCan("admin");
  const [members, setMembers] = useState<Members>();

  const load = useCallback(async () => {
    const { data } = await api.GET("/v1/settings/members");
    setMembers(data);
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    load();
  }, [load]);

  async function changeRole(userId: string, role: Role) {
    const { error } = await api.PUT("/v1/settings/members/{user_id}", {
      params: { path: { user_id: userId } },
      body: { role },
    });
    if (error) toast.error(errorMessage(error));
    load();
  }

  async function remove(userId: string, name: string) {
    const { error } = await api.DELETE("/v1/settings/members/{user_id}", {
      params: { path: { user_id: userId } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`Removed ${name}`);
    load();
  }

  async function cancelInvite(inviteId: string, email: string) {
    const { error } = await api.DELETE("/v1/settings/invites/{invite_id}", {
      params: { path: { invite_id: inviteId } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`Cancelled the invite for ${email}`);
    load();
  }

  if (!members) return <Spinner />;
  return (
    <div className="flex flex-col gap-4">
      {canAdmin && <InviteForm onInvited={load} />}
      <ItemGroup className="gap-1">
        {members.members.map((member) => (
          <Item key={member.user.id} variant="outline" size="sm">
            <ItemContent className="min-w-0">
              <ItemTitle>
                {member.user.name}
                {member.user.id === me.user?.id && <Badge variant="secondary">You</Badge>}
              </ItemTitle>
              <ItemDescription className="truncate">{member.user.email}</ItemDescription>
            </ItemContent>
            <ItemActions>
              <span className="text-sm text-muted-foreground">{roleLabel(member.role)}</span>
              {canAdmin && (
                <DropdownMenu>
                  <DropdownMenuTrigger
                    render={<Button variant="ghost" size="icon-sm" aria-label="Member actions" />}
                  >
                    <EllipsisIcon />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-64">
                    <DropdownMenuRadioGroup
                      value={member.role}
                      onValueChange={(role) => changeRole(member.user.id, role as Role)}
                    >
                      {ROLES.map((role) => (
                        <DropdownMenuRadioItem key={role.value} value={role.value}>
                          <div className="flex flex-col">
                            <span>{role.label}</span>
                            <span className="text-xs text-muted-foreground">
                              {role.description}
                            </span>
                          </div>
                        </DropdownMenuRadioItem>
                      ))}
                    </DropdownMenuRadioGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => remove(member.user.id, member.user.name)}
                    >
                      <Trash2Icon />
                      Remove
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </ItemActions>
          </Item>
        ))}
        {members.invites.map((invite) => (
          <Item key={invite.id} variant="outline" size="sm">
            <ItemContent className="min-w-0">
              <ItemTitle className="truncate">{invite.email}</ItemTitle>
              <ItemDescription>Invited · joins when they first sign in</ItemDescription>
            </ItemContent>
            <ItemActions>
              <span className="text-sm text-muted-foreground">{roleLabel(invite.role)}</span>
              {canAdmin && (
                <DropdownMenu>
                  <DropdownMenuTrigger
                    render={<Button variant="ghost" size="icon-sm" aria-label="Invite actions" />}
                  >
                    <EllipsisIcon />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => cancelInvite(invite.id, invite.email)}
                    >
                      <Trash2Icon />
                      Cancel invite
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </ItemActions>
          </Item>
        ))}
      </ItemGroup>
    </div>
  );
}

/** Invite an email address with a role. Nobody is emailed: tell them to sign in. */
function InviteForm({ onInvited }: { onInvited: () => void }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();

  async function invite() {
    setSaving(true);
    setError(undefined);
    const { error } = await api.POST("/v1/settings/invites", { body: { email, role } });
    setSaving(false);
    if (error) {
      setError(errorMessage(error));
      return;
    }
    toast.success(`Invited ${email}`);
    setEmail("");
    onInvited();
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (email.trim()) invite();
      }}
    >
      <Field data-invalid={!!error}>
        <div className="flex gap-2">
          <Input
            type="email"
            placeholder="name@example.com"
            aria-label="Email address"
            aria-invalid={!!error}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Select
            items={ROLES.map((r) => ({ value: r.value, label: r.label }))}
            value={role}
            onValueChange={(value) => setRole(value as Role)}
          >
            <SelectTrigger aria-label="Role" className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROLES.map((r) => (
                <SelectItem key={r.value} value={r.value}>
                  {r.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button type="submit" disabled={saving || !email.trim()}>
            {saving ? <Spinner data-icon="inline-start" /> : <MailIcon data-icon="inline-start" />}
            Invite
          </Button>
        </div>
        {error ? (
          <FieldError>{error}</FieldError>
        ) : (
          <FieldDescription>
            Nobody is emailed: they join with this role when they first sign in with this address.
          </FieldDescription>
        )}
      </Field>
    </form>
  );
}
