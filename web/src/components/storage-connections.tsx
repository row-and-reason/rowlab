"use client";

import { DatabaseIcon, EllipsisIcon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useCan } from "@/components/me";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@/components/ui/item";
import { Spinner } from "@/components/ui/spinner";
import { api, type Connection } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

/** Saved connections to S3-compatible storage: list, add, change and delete them. */
export function StorageConnections() {
  const [connections, setConnections] = useState<Connection[]>();
  // The connection being edited, or "new" while adding one.
  const [editing, setEditing] = useState<Connection | "new">();
  const canAdmin = useCan("admin");

  const load = useCallback(async () => {
    const { data } = await api.GET("/v1/settings/connections");
    setConnections(data);
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    load();
  }, [load]);

  async function remove(connection: Connection) {
    const { error } = await api.DELETE("/v1/settings/connections/{connection_id}", {
      params: { path: { connection_id: connection.id } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`Deleted ${connection.name}`);
    load();
  }

  if (!connections) return <Spinner />;
  return (
    <>
      {connections.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <DatabaseIcon />
            </EmptyMedia>
            <EmptyTitle>No connections yet</EmptyTitle>
            <EmptyDescription>
              Add one to load data from a bucket and export to it. Without one, rowlab uses the AWS
              credentials in its environment, if any.
            </EmptyDescription>
          </EmptyHeader>
          {canAdmin && (
            <EmptyContent>
              <Button size="sm" onClick={() => setEditing("new")}>
                <PlusIcon data-icon="inline-start" />
                Add connection
              </Button>
            </EmptyContent>
          )}
        </Empty>
      ) : (
        <div className="flex flex-col gap-2">
          <ItemGroup className="gap-1">
            {connections.map((connection) => (
              <Item key={connection.id} variant="outline" size="sm">
                <ItemContent className="min-w-0">
                  <ItemTitle>{connection.name}</ItemTitle>
                  <ItemDescription className="truncate">
                    {connection.endpoint || "AWS S3"} · {connection.region} ·{" "}
                    {connection.access_key_id}
                  </ItemDescription>
                </ItemContent>
                {canAdmin && (
                  <ItemActions>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button variant="ghost" size="icon-sm" aria-label="Connection actions" />
                        }
                      >
                        <EllipsisIcon />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => setEditing(connection)}>
                          <PencilIcon />
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem variant="destructive" onClick={() => remove(connection)}>
                          <Trash2Icon />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </ItemActions>
                )}
              </Item>
            ))}
          </ItemGroup>
          {canAdmin && (
            <Button
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() => setEditing("new")}
            >
              <PlusIcon data-icon="inline-start" />
              Add connection
            </Button>
          )}
        </div>
      )}
      {editing && (
        <ConnectionDialog
          key={editing === "new" ? "new" : editing.id}
          connection={editing === "new" ? undefined : editing}
          onClose={() => setEditing(undefined)}
          onSaved={() => {
            setEditing(undefined);
            load();
          }}
        />
      )}
    </>
  );
}

/** Add a connection, or change one: its secret key stays as saved unless a new one is entered. */
function ConnectionDialog({
  connection,
  onClose,
  onSaved,
}: {
  connection: Connection | undefined;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    name: connection?.name ?? "",
    endpoint: connection?.endpoint ?? "",
    region: connection?.region ?? "us-east-1",
    access_key_id: connection?.access_key_id ?? "",
    secret_access_key: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const set = (field: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [field]: e.target.value });

  async function save() {
    setSaving(true);
    setError(undefined);
    const body = { ...form, secret_access_key: form.secret_access_key || null };
    const { error } = connection
      ? await api.PUT("/v1/settings/connections/{connection_id}", {
          params: { path: { connection_id: connection.id } },
          body,
        })
      : await api.POST("/v1/settings/connections", { body });
    setSaving(false);
    if (error) setError(errorMessage(error));
    else {
      toast.success(`Saved ${form.name}`);
      onSaved();
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{connection ? `Edit ${connection.name}` : "Add a connection"}</DialogTitle>
          <DialogDescription>
            To S3-compatible storage: AWS S3, Cloudflare R2, MinIO and others.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="connection-name">Name</FieldLabel>
              <Input
                id="connection-name"
                placeholder="Company data lake"
                value={form.name}
                onChange={set("name")}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="connection-endpoint">Endpoint</FieldLabel>
              <Input
                id="connection-endpoint"
                placeholder="Empty for AWS S3"
                value={form.endpoint}
                onChange={set("endpoint")}
              />
              <FieldDescription>
                For other storage, its address, e.g.
                https://&lt;account&gt;.r2.cloudflarestorage.com or http://localhost:9000 for MinIO.
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="connection-region">Region</FieldLabel>
              <Input id="connection-region" value={form.region} onChange={set("region")} />
              <FieldDescription>For Cloudflare R2, auto.</FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="connection-key">Access key ID</FieldLabel>
              <Input
                id="connection-key"
                autoComplete="off"
                value={form.access_key_id}
                onChange={set("access_key_id")}
              />
            </Field>
            <Field data-invalid={!!error}>
              <FieldLabel htmlFor="connection-secret">Secret access key</FieldLabel>
              <Input
                id="connection-secret"
                type="password"
                autoComplete="off"
                placeholder={connection ? "Saved · enter a new one to replace it" : ""}
                value={form.secret_access_key}
                onChange={set("secret_access_key")}
              />
              {error ? (
                <FieldError>{error}</FieldError>
              ) : (
                <FieldDescription>Kept by rowlab and never shown again.</FieldDescription>
              )}
            </Field>
            <Button type="submit" className="self-end" disabled={saving}>
              {saving && <Spinner data-icon="inline-start" />}
              Save
            </Button>
          </FieldGroup>
        </form>
      </DialogContent>
    </Dialog>
  );
}
