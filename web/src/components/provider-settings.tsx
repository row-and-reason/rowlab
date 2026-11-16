"use client";

import {
  BoxIcon,
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
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldSeparator,
} from "@/components/ui/field";
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
import { api, type Model, type Provider, type Settings } from "@/lib/api/client";
import { forgetModels } from "@/lib/catalog";
import { errorMessage, formatNumber } from "@/lib/format";

type ProviderType = Provider["type"];

const TYPES: {
  value: ProviderType;
  label: string;
  baseUrl: string;
  keyHint: string;
  about: string;
}[] = [
  {
    value: "openrouter",
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api",
    keyHint: "sk-or-v1-…",
    about: "Billed to your OpenRouter account.",
  },
  {
    value: "openai",
    label: "OpenAI-compatible",
    baseUrl: "",
    keyHint: "sk-…",
    about:
      "A LiteLLM gateway, or vLLM serving a generic model or LoRA checkpoints (/v1/decisions).",
  },
  {
    value: "systemone",
    label: "System One",
    baseUrl: "",
    keyHint: "The key the server was started with",
    about: "A server of decision models, e.g. vLLM or a model's own (/v1/systemone).",
  },
];
const typeInfo = (type: ProviderType) => TYPES.find((t) => t.value === type)!;

/** The organisation's model providers, each with its own models: list, add, change and delete them,
 * and pick the one rowlab's catalog models go to. Admins manage providers; members add models. */
export function ProviderSettings({
  settings,
  onChanged,
}: {
  settings: Settings;
  onChanged: () => void;
}) {
  const [providers, setProviders] = useState<Provider[]>();
  const [models, setModels] = useState<Model[]>([]);
  // The provider being edited, or "new" while adding one.
  const [editing, setEditing] = useState<Provider | "new">();
  // The provider a model is being added to, or the model being edited.
  const [modelEditing, setModelEditing] = useState<{ provider: Provider; model?: Model }>();
  const canAdmin = useCan("admin");
  const canEdit = useCan("member");

  const [loadError, setLoadError] = useState<string>();
  const load = useCallback(async () => {
    setLoadError(undefined);
    try {
      const [found, listed] = await Promise.all([
        api.GET("/v1/settings/providers"),
        api.GET("/v1/models"),
      ]);
      if (found.data) setProviders(found.data);
      else setLoadError(errorMessage(found.error));
      setModels((listed.data ?? []).filter((m) => m.provider_id));
    } catch {
      setLoadError("Could not reach rowlab.");
    }
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    load();
  }, [load]);

  function changed() {
    forgetModels();
    load();
    onChanged();
  }

  async function activate(provider: Provider) {
    const { error } = await api.POST("/v1/settings/providers/{provider_id}/activate", {
      params: { path: { provider_id: provider.id } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`rowlab's models go to ${provider.name}`);
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

  async function removeModel(model: Model) {
    const { error } = await api.DELETE("/v1/models/{model_id}", {
      params: { path: { model_id: model.id } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`Deleted ${model.id}; its answers stay`);
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
            The server&apos;s own OpenRouter key (<code>OPENROUTER_API_KEY</code>) pays for
            rowlab&apos;s models. Your own models go to their providers here.
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
                ? "Add OpenRouter, a LiteLLM gateway, or a server of your own, with its key."
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
            {providers.map((provider) => [
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
                {canEdit && (
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
                        <DropdownMenuItem onClick={() => setModelEditing({ provider })}>
                          <PlusIcon />
                          Add model
                        </DropdownMenuItem>
                        {canAdmin && !provider.active && provider.type !== "systemone" && (
                          <DropdownMenuItem onClick={() => activate(provider)}>
                            <CheckIcon />
                            Use for rowlab&apos;s models
                          </DropdownMenuItem>
                        )}
                        {canAdmin && (
                          <DropdownMenuItem onClick={() => setEditing(provider)}>
                            <PencilIcon />
                            Edit
                          </DropdownMenuItem>
                        )}
                        {canAdmin && (
                          <DropdownMenuItem variant="destructive" onClick={() => remove(provider)}>
                            <Trash2Icon />
                            Delete
                          </DropdownMenuItem>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </ItemActions>
                )}
              </Item>,
              ...models
                .filter((m) => m.provider_id === provider.id)
                .map((model) => (
                  <Item
                    key={`${provider.id}/${model.id}`}
                    variant="default"
                    size="xs"
                    className="rounded-none border-x-0 border-t-0 border-b border-border pl-8"
                  >
                    <ItemContent className="min-w-0">
                      <ItemTitle>
                        <BoxIcon className="size-3.5 text-muted-foreground" />
                        {model.id}
                      </ItemTitle>
                      <ItemDescription className="truncate">
                        {model.kind === "decision" ? "Decision model" : "LLM"} · served as{" "}
                        {model.upstream} · {modelPrice(model)}
                        {model.note && <> · {model.note}</>}
                      </ItemDescription>
                    </ItemContent>
                    {canEdit && (
                      <ItemActions>
                        <DropdownMenu>
                          <DropdownMenuTrigger
                            render={
                              <Button variant="ghost" size="icon-sm" aria-label="Model actions" />
                            }
                          >
                            <EllipsisIcon />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => setModelEditing({ provider, model })}>
                              <PencilIcon />
                              Edit
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              variant="destructive"
                              onClick={() => removeModel(model)}
                            >
                              <Trash2Icon />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </ItemActions>
                    )}
                  </Item>
                )),
            ])}
          </ItemGroup>
          <p className="text-xs text-muted-foreground">
            rowlab&apos;s models go to the active provider, and runs already started keep theirs.
            Your own models, added from a provider&apos;s menu, each go to their own.
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
      {modelEditing && (
        <ModelDialog
          key={modelEditing.model?.id ?? modelEditing.provider.id}
          provider={modelEditing.provider}
          model={modelEditing.model}
          onClose={() => setModelEditing(undefined)}
          onSaved={() => {
            setModelEditing(undefined);
            changed();
          }}
        />
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
              <FieldDescription>{info.about}</FieldDescription>
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
                placeholder={form.type === "openrouter" ? "" : "https://gpu.example.com:8000"}
                value={form.base_url}
                onChange={set("base_url")}
              />
              {provider && (
                <FieldDescription>To change it, enter the API key again.</FieldDescription>
              )}
            </Field>
            {form.type === "openai" && (
              <Field>
                <FieldLabel htmlFor="provider-prefix">Model prefix</FieldLabel>
                <Input
                  id="provider-prefix"
                  placeholder="openrouter/"
                  value={form.model_prefix}
                  onChange={set("model_prefix")}
                />
                <FieldDescription>
                  Put before the ids of rowlab&apos;s models, if a gateway routes them under one.
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

/** A model's prices per 1M tokens, or that it has none. */
function modelPrice(model: Model): string {
  if (model.prompt_price == null) return "no price";
  const input = `$${formatNumber(model.prompt_price * 1e6)}`;
  return model.completion_price == null
    ? `${input}/M in`
    : `${input} in · $${formatNumber(model.completion_price * 1e6)} out per M`;
}

/** USD per token, from a price per 1M tokens as typed: null for none, undefined if it isn't one. */
function perToken(typed: string): number | null | undefined {
  if (!typed.trim()) return null;
  const value = Number(typed.trim());
  return Number.isFinite(value) && value >= 0 ? value / 1e6 : undefined;
}

/** Add a model of the organisation's own to a provider, or change one's note and prices. What
 * answers (its id, served name and kind) is fixed once added. */
function ModelDialog({
  provider,
  model,
  onClose,
  onSaved,
}: {
  provider: Provider;
  model: Model | undefined;
  onClose: () => void;
  onSaved: () => void;
}) {
  const perMillion = (price: number | null | undefined) =>
    price == null ? "" : String(price * 1e6);
  const [form, setForm] = useState({
    id: model?.id ?? "",
    upstream: model?.upstream ?? "",
    kind: model?.kind ?? ("decision" as Model["kind"]),
    note: model?.note ?? "",
    prompt_price: perMillion(model?.prompt_price),
    completion_price: perMillion(model?.completion_price),
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const set =
    (field: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm({ ...form, [field]: e.target.value });

  async function save() {
    setSaving(true);
    setError(undefined);
    const prices = {
      prompt_price: perToken(form.prompt_price),
      completion_price: perToken(form.completion_price),
    };
    if (prices.prompt_price === undefined || prices.completion_price === undefined) {
      setError("Enter prices as numbers of dollars, e.g. 0.05, or leave them empty.");
      setSaving(false);
      return;
    }
    try {
      const { error } = model
        ? await api.PATCH("/v1/models/{model_id}", {
            params: { path: { model_id: model.id } },
            body: { note: form.note, ...prices },
          })
        : await api.POST("/v1/models", {
            body: {
              id: form.id.trim(),
              provider: provider.id,
              upstream: form.upstream.trim(),
              kind: form.kind,
              note: form.note,
              ...prices,
            },
          });
      if (error) setError(errorMessage(error));
      else {
        toast.success(model ? `Saved ${model.id}` : `${form.id} answered, and was added`);
        onSaved();
      }
    } catch {
      setError("Could not reach rowlab. The model was not saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{model ? `Edit ${model.id}` : `Add a model to ${provider.name}`}</DialogTitle>
          <DialogDescription>
            {model
              ? "What answers can't change; for other weights, add a new model."
              : "It is asked a short question first, and added once it answers."}
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <FieldGroup>
            {!model && (
              <>
                <Field>
                  <FieldLabel htmlFor="model-id">Id</FieldLabel>
                  <Input
                    id="model-id"
                    placeholder="fallacy-ft-step-2000"
                    value={form.id}
                    onChange={set("id")}
                  />
                  <FieldDescription>
                    As answer columns show it, for good: one per checkpoint, never reused.
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="model-upstream">Served as</FieldLabel>
                  <Input
                    id="model-upstream"
                    placeholder={form.id || "step-2000"}
                    value={form.upstream}
                    onChange={set("upstream")}
                  />
                  <FieldDescription>
                    The name the server gives it, e.g. vLLM&apos;s --served-model-name or a
                    --lora-modules name. Defaults to the id.
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="model-kind">Kind</FieldLabel>
                  <Select
                    items={KINDS}
                    value={form.kind}
                    onValueChange={(kind) => kind && setForm({ ...form, kind })}
                  >
                    <SelectTrigger id="model-kind" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {KINDS.map((k) => (
                        <SelectItem key={k.value} value={k.value}>
                          {k.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              </>
            )}
            <Field>
              <FieldLabel htmlFor="model-note">Note</FieldLabel>
              <Input
                id="model-note"
                placeholder="Qwen/Qwen3.5-4B-Base + LoRA, run 7, step 2000"
                value={form.note}
                onChange={set("note")}
              />
              <FieldDescription>What answers, to read in results months later.</FieldDescription>
            </Field>
            <FieldSeparator />
            <div className="grid grid-cols-2 gap-3">
              <Field>
                <FieldLabel htmlFor="model-price-in">$ per 1M in</FieldLabel>
                <Input
                  id="model-price-in"
                  inputMode="decimal"
                  placeholder="None"
                  value={form.prompt_price}
                  onChange={set("prompt_price")}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="model-price-out">$ per 1M out</FieldLabel>
                <Input
                  id="model-price-out"
                  inputMode="decimal"
                  placeholder="None"
                  value={form.completion_price}
                  onChange={set("completion_price")}
                />
              </Field>
            </div>
            <Field data-invalid={!!error}>
              {error ? (
                <FieldError>{error}</FieldError>
              ) : (
                <FieldDescription>
                  Optional. Leave them empty for a GPU paid by the hour: its answers are counted,
                  not priced.
                </FieldDescription>
              )}
            </Field>
            <Button type="submit" size="sm" className="self-end" disabled={saving}>
              {saving && <Spinner data-icon="inline-start" />}
              {model ? "Save" : "Add"}
            </Button>
          </FieldGroup>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const KINDS: { value: Model["kind"]; label: string }[] = [
  { value: "decision", label: "Decision model" },
  { value: "llm", label: "LLM, with structured outputs" },
];
