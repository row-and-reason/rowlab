"use client";

import {
  CheckIcon,
  EllipsisIcon,
  KeyRoundIcon,
  PencilIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useCan } from "@/components/me";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { api, type Provider, type Settings } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

type ProviderType = Provider["type"];

const TYPES: { value: ProviderType; label: string; baseUrl: string; keyHint: string }[] = [
  {
    value: "openrouter",
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api",
    keyHint: "sk-or-v1-…",
  },
  { value: "litellm", label: "LiteLLM", baseUrl: "", keyHint: "sk-…" },
];
const typeInfo = (type: ProviderType) => TYPES.find((t) => t.value === type)!;

/** The organisation's model providers: list, add, change, delete them, and pick the active one. */
export function ProviderSettings({
  settings,
  onChanged,
}: {
  settings: Settings;
  onChanged: () => void;
}) {
  const [providers, setProviders] = useState<Provider[]>();
  // The provider being edited, or "new" while adding one.
  const [editing, setEditing] = useState<Provider | "new">();
  const canAdmin = useCan("admin");

  const [loadError, setLoadError] = useState<string>();
  const load = useCallback(async () => {
    setLoadError(undefined);
    try {
      const { data, error } = await api.GET("/v1/settings/providers");
      if (data) setProviders(data);
      else setLoadError(errorMessage(error));
    } catch {
      setLoadError("Could not reach rowlab.");
    }
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    load();
  }, [load]);

  function changed() {
    load();
    onChanged();
  }

  async function activate(provider: Provider) {
    const { error } = await api.POST("/v1/settings/providers/{provider_id}/activate", {
      params: { path: { provider_id: provider.id } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`New runs use ${provider.name}`);
    changed();
  }

  async function remove(provider: Provider) {
    const { error } = await api.DELETE("/v1/settings/providers/{provider_id}", {
      params: { path: { provider_id: provider.id } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`Deleted ${provider.name}`);
    changed();
  }

  if (loadError)
    return (
      <Alert variant="destructive">
        <AlertDescription>{loadError}</AlertDescription>
        <Button size="sm" variant="outline" onClick={load}>
          Retry
        </Button>
      </Alert>
    );
  if (!providers) return <Spinner />;
  return (
    <>
      {settings.provider === "server" && (
        <Alert className="mb-4">
          <AlertDescription>
            The server&apos;s own OpenRouter key (<code>OPENROUTER_API_KEY</code>) pays for every
            run, so the providers here aren&apos;t used.
          </AlertDescription>
        </Alert>
      )}
      {providers.length === 0 ? (
        <Empty className="items-start px-0 py-5 text-left">
          <EmptyHeader className="items-start text-left">
            <EmptyMedia variant="icon">
              <KeyRoundIcon />
            </EmptyMedia>
            <EmptyTitle>No model provider yet</EmptyTitle>
            <EmptyDescription>
              {canAdmin
                ? "Add OpenRouter, or a LiteLLM gateway, with your own key. Model charges go to it."
                : "An admin adds one."}
            </EmptyDescription>
          </EmptyHeader>
          {canAdmin && (
            <EmptyContent>
              <Button size="sm" onClick={() => setEditing("new")}>
                <PlusIcon data-icon="inline-start" />
                Add provider
              </Button>
            </EmptyContent>
          )}
        </Empty>
      ) : (
        <div className="flex flex-col gap-2">
          <ItemGroup className="gap-0">
            {providers.map((provider) => (
              <Item
                key={provider.id}
                variant="default"
                size="xs"
                className="rounded-none border-x-0 border-t-0 border-b border-border"
              >
                <ItemContent className="min-w-0">
                  <ItemTitle>
                    {provider.name}
                    {provider.active && <Badge variant="secondary">Active</Badge>}
                  </ItemTitle>
                  <ItemDescription className="truncate">
                    {typeInfo(provider.type).label} · {provider.base_url}
                    {provider.model_prefix && <> · models as {provider.model_prefix}…</>}
                  </ItemDescription>
                </ItemContent>
                {canAdmin && (
                  <ItemActions>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button variant="ghost" size="icon-sm" aria-label="Provider actions" />
                        }
                      >
                        <EllipsisIcon />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {!provider.active && (
                          <DropdownMenuItem onClick={() => activate(provider)}>
                            <CheckIcon />
                            Use for new runs
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuItem onClick={() => setEditing(provider)}>
                          <PencilIcon />
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem variant="destructive" onClick={() => remove(provider)}>
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
          <p className="text-xs text-muted-foreground">
            New runs use the active provider; runs already started keep theirs.
          </p>
          {canAdmin && (
            <Button
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() => setEditing("new")}
            >
              <PlusIcon data-icon="inline-start" />
              Add provider
            </Button>
          )}
        </div>
      )}
      {editing && (
        <ProviderDialog
          key={editing === "new" ? "new" : editing.id}
          provider={editing === "new" ? undefined : editing}
          onClose={() => setEditing(undefined)}
          onSaved={() => {
            setEditing(undefined);
            changed();
          }}
        />
      )}
    </>
  );
}

/** Add a provider, or change one: its key stays as saved unless a new one is entered. */
function ProviderDialog({
  provider,
  onClose,
  onSaved,
}: {
  provider: Provider | undefined;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    type: provider?.type ?? ("openrouter" as ProviderType),
    name: provider?.name ?? "",
    base_url: provider?.base_url ?? typeInfo("openrouter").baseUrl,
    model_prefix: provider?.model_prefix ?? "",
    api_key: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const set = (field: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [field]: e.target.value });
  const info = typeInfo(form.type);

  async function save() {
    setSaving(true);
    setError(undefined);
    const body = { ...form, api_key: form.api_key || null };
    try {
      const { error } = provider
        ? await api.PUT("/v1/settings/providers/{provider_id}", {
            params: { path: { provider_id: provider.id } },
            body,
          })
        : await api.POST("/v1/settings/providers", { body });
      if (error) setError(errorMessage(error));
      else {
        toast.success(`Saved ${form.name || info.label}`);
        onSaved();
      }
    } catch {
      setError("Could not reach rowlab. The provider was not saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{provider ? `Edit ${provider.name}` : "Add a model provider"}</DialogTitle>
          <DialogDescription>
            Model calls go to it, on your own key. The key is checked before saving.
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
              <FieldLabel htmlFor="provider-type">Type</FieldLabel>
              <Select
                items={TYPES}
                value={form.type}
                disabled={!!provider}
                onValueChange={(type) =>
                  type &&
                  setForm({
                    ...form,
                    type,
                    // The default address follows the type, unless one was typed in.
                    base_url: TYPES.some((t) => t.baseUrl === form.base_url)
                      ? typeInfo(type).baseUrl
                      : form.base_url,
                  })
                }
              >
                <SelectTrigger id="provider-type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldDescription>
                {form.type === "litellm"
                  ? "A LiteLLM gateway in front of other providers. Language models only; decision models need OpenRouter."
                  : "Decision models and language models, billed to your OpenRouter account."}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="provider-name">Name</FieldLabel>
              <Input
                id="provider-name"
                placeholder={info.label}
                value={form.name}
                onChange={set("name")}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="provider-url">Base URL</FieldLabel>
              <Input
                id="provider-url"
                placeholder={form.type === "litellm" ? "https://litellm.example.com" : ""}
                value={form.base_url}
                onChange={set("base_url")}
              />
              {provider && (
                <FieldDescription>To change it, enter the API key again.</FieldDescription>
              )}
            </Field>
            {form.type === "litellm" && (
              <Field>
                <FieldLabel htmlFor="provider-prefix">Model prefix</FieldLabel>
                <Input
                  id="provider-prefix"
                  placeholder="openrouter/"
                  value={form.model_prefix}
                  onChange={set("model_prefix")}
                />
                <FieldDescription>
                  Put before each model&apos;s id, if the gateway routes them under one.
                </FieldDescription>
              </Field>
            )}
            <Field data-invalid={!!error}>
              <FieldLabel htmlFor="provider-key">API key</FieldLabel>
              <Input
                id="provider-key"
                type="password"
                autoComplete="off"
                placeholder={provider ? "Saved · enter a new one to replace it" : info.keyHint}
                value={form.api_key}
                onChange={set("api_key")}
              />
              {error ? (
                <FieldError>{error}</FieldError>
              ) : (
                <FieldDescription>Kept by rowlab and never shown again.</FieldDescription>
              )}
            </Field>
            <Button type="submit" size="sm" className="self-end" disabled={saving}>
              {saving && <Spinner data-icon="inline-start" />}
              Save
            </Button>
          </FieldGroup>
        </form>
      </DialogContent>
    </Dialog>
  );
}
