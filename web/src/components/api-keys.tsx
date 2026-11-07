"use client";

import { CheckIcon, CopyIcon, KeyRoundIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { TooltipButton } from "@/components/tooltip-button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Field, FieldDescription, FieldError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@/components/ui/input-group";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@/components/ui/item";
import {
  Alert as LoadAlert,
  AlertDescription as LoadAlertDescription,
} from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { api, type ApiKey } from "@/lib/api/client";
import { errorMessage, formatDate } from "@/lib/format";

/** Your own API keys: make one (shown once), see when each was last used, delete them. */
export function ApiKeys() {
  const [keys, setKeys] = useState<ApiKey[]>();
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string>();
  // The key just made, shown until the page is left.
  const [made, setMade] = useState<{ name: string; key: string }>();
  const [copied, setCopied] = useState(false);

  const [loadError, setLoadError] = useState<string>();
  const load = useCallback(async () => {
    setLoadError(undefined);
    try {
      const { data, error } = await api.GET("/v1/settings/api-keys");
      if (data) setKeys(data);
      else setLoadError(errorMessage(error));
    } catch {
      setLoadError("Could not reach rowlab.");
    }
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    load();
  }, [load]);

  async function create() {
    setCreating(true);
    setError(undefined);
    const { data, error } = await api.POST("/v1/settings/api-keys", { body: { name } });
    setCreating(false);
    if (error) {
      setError(errorMessage(error));
      return;
    }
    setMade({ name: data.api_key.name, key: data.key });
    setCopied(false);
    setName("");
    load();
  }

  async function remove(key: ApiKey) {
    const { error } = await api.DELETE("/v1/settings/api-keys/{api_key_id}", {
      params: { path: { api_key_id: key.id } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`Deleted ${key.name}`);
    load();
  }

  async function copy(key: string) {
    await navigator.clipboard.writeText(key);
    setCopied(true);
  }

  if (loadError)
    return (
      <LoadAlert variant="destructive">
        <LoadAlertDescription>{loadError}</LoadAlertDescription>
        <Button size="sm" variant="outline" onClick={load}>
          Retry
        </Button>
      </LoadAlert>
    );
  if (!keys) return <Spinner />;
  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-muted-foreground">
        Personal keys for scripts and notebooks. Each key uses your current role.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) create();
        }}
      >
        <Field data-invalid={!!error}>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="min-w-48 flex-1"
              placeholder="Where it's used, e.g. notebook"
              aria-label="Key name"
              aria-invalid={!!error}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Button type="submit" size="sm" disabled={creating || !name.trim()}>
              {creating && <Spinner data-icon="inline-start" />}
              Create key
            </Button>
          </div>
          {error ? (
            <FieldError>{error}</FieldError>
          ) : (
            <FieldDescription>
              Send it as <code>Authorization: Bearer rl_…</code>. It acts as you, with your role.
            </FieldDescription>
          )}
        </Field>
      </form>

      {made && (
        <Alert>
          <KeyRoundIcon />
          <AlertTitle>{made.name}: copy it now, it isn&apos;t shown again</AlertTitle>
          <AlertDescription>
            <InputGroup className="mt-1">
              <InputGroupInput readOnly value={made.key} className="font-mono" />
              <InputGroupAddon align="inline-end">
                <InputGroupButton aria-label="Copy" size="icon-xs" onClick={() => copy(made.key)}>
                  {copied ? <CheckIcon /> : <CopyIcon />}
                </InputGroupButton>
              </InputGroupAddon>
            </InputGroup>
          </AlertDescription>
        </Alert>
      )}

      {keys.length === 0 ? (
        <Empty className="items-start px-0 py-5 text-left">
          <EmptyHeader className="items-start text-left">
            <EmptyMedia variant="icon">
              <KeyRoundIcon />
            </EmptyMedia>
            <EmptyTitle>No API keys yet</EmptyTitle>
            <EmptyDescription>
              For scripts and notebooks that use rowlab&apos;s API.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <ItemGroup className="gap-0">
          {keys.map((key) => (
            <Item
              key={key.id}
              variant="default"
              size="xs"
              className="rounded-none border-x-0 border-t-0 border-b border-border"
            >
              <ItemContent className="min-w-0">
                <ItemTitle>{key.name}</ItemTitle>
                <ItemDescription>
                  Made {formatDate(key.created_at)} ·{" "}
                  {key.last_used_at ? `last used ${formatDate(key.last_used_at)}` : "never used"}
                </ItemDescription>
              </ItemContent>
              <ItemActions>
                <TooltipButton
                  label="Delete"
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => remove(key)}
                >
                  <Trash2Icon />
                </TooltipButton>
              </ItemActions>
            </Item>
          ))}
        </ItemGroup>
      )}
    </div>
  );
}
