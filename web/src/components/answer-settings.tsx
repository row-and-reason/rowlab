"use client";

import { InfoIcon, PlusIcon, XIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { type PickGroup, PickList } from "@/components/pick-list";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  ExtractField,
  FieldType,
  Model,
  Option,
  Task,
  TaskTypes,
} from "@/lib/api/client";
import { useModels } from "@/lib/catalog";
import { formatNumber } from "@/lib/format";
import { EMPTY_FIELD, modelSlug } from "@/lib/tasks";

/** A task's options, fields, reason and result column, as its answer type needs. */
export function AnswerSettings({
  labels = false,
  task,
  types,
  models,
  onChange,
}: {
  labels?: boolean;
  task: Task;
  types: TaskTypes;
  models: Model[];
  onChange: (task: Task) => void;
}) {
  const family = types.types.find((t) => t.id === task.type)?.family;
  const scalarTypes = types.field_types
    .filter((t) => t.id !== "items" && t.id !== "list")
    .map((t) => ({ value: t.id, label: t.label }));
  const allLlms = task.models.every((id) => models.find((m) => m.id === id)?.kind === "llm");
  return (
    <>
      {family === "classify" && task.type !== "yes_no" && (
        <OptionsEditor
          scale={task.type === "scale"}
          options={task.options}
          onChange={(options) => onChange({ ...task, options })}
        />
      )}
      {task.type === "extract" &&
        (task.extraction_mode === "single" ? (
          <Field>
            <FieldLabel htmlFor={`scalar-${task.id}`}>Value type</FieldLabel>
            <Select
              items={scalarTypes}
              value={task.fields[0]?.type ?? "text"}
              onValueChange={(type) => {
                if (type)
                  onChange({
                    ...task,
                    fields: [{ ...EMPTY_FIELD, name: "value", type: type as FieldType }],
                  });
              }}
            >
              <SelectTrigger id={`scalar-${task.id}`} className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {scalarTypes.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        ) : (
          <FieldsEditor
            label="Fields"
            fields={task.fields}
            fieldTypes={types.field_types}
            onChange={(fields) => onChange({ ...task, fields })}
          />
        ))}
      <Field>
        <div className="flex items-center gap-1">
          <FieldLabel htmlFor={`column-${task.id}`}>Result column</FieldLabel>
          <Popover>
            <PopoverTrigger
              render={
                <Button variant="ghost" size="icon-xs" aria-label="How result columns are named" />
              }
            >
              <InfoIcon />
            </PopoverTrigger>
            <PopoverContent align="end" className="w-72 text-sm">
              {labels
                ? "Labels use this name, without a model suffix. Pick any and structured extraction add an option or field name when needed."
                : columnsDescription(task)}
            </PopoverContent>
          </Popover>
        </div>
        <Input
          id={`column-${task.id}`}
          value={task.column}
          onChange={(e) => onChange({ ...task, column: e.target.value })}
        />
      </Field>
      {!labels && family !== "write" && (
        <Field orientation="horizontal">
          <Checkbox
            id={`reason-${task.id}`}
            checked={task.reason}
            disabled={!allLlms && !task.reason}
            onCheckedChange={(checked) => onChange({ ...task, reason: checked === true })}
          />
          <FieldLabel htmlFor={`reason-${task.id}`} className="font-normal">
            Also write why
            {!allLlms && <span className="text-muted-foreground">· LLMs only</span>}
          </FieldLabel>
        </Field>
      )}
    </>
  );
}

function columnsDescription(task: Task): string {
  const column = task.column || "answer";
  const model = modelSlug(task.models[0] ?? "model");
  const reason = task.reason ? `, and ${column}__${model}_reason with why` : "";
  if (task.type === "write") {
    return `Each model writes its own column: ${column}__${model}, the text.`;
  }
  if (task.type === "extract") {
    const field = task.fields[0]?.name || "field";
    const answer =
      task.fields.length > 1
        ? `${column}_${field}__${model} for each field`
        : `${column}__${model}`;
    return `Each model writes its own columns: ${answer}, empty where the text doesn't say${reason}.`;
  }
  const answer =
    task.type === "pick_any"
      ? `${column}_${task.options[0]?.name || "option"}__${model} for each option`
      : `${column}__${model}`;
  const value = {
    yes_no: "true or false",
    pick_one: "the option's name",
    pick_any: "true or false",
    scale: "the level's name",
  }[task.type];
  return `Each model writes its own columns: ${answer} (${value}) and its _proba column, how likely it is right${reason}.`;
}

/** Fields to extract: a name and a type each; items hold fields of their own, one level deep. */
function FieldsEditor({
  label,
  fields,
  fieldTypes,
  nested = false,
  onChange,
}: {
  label: string;
  fields: ExtractField[];
  fieldTypes: TaskTypes["field_types"];
  nested?: boolean;
  onChange: (fields: ExtractField[]) => void;
}) {
  const update = (i: number, changes: Partial<ExtractField>) =>
    onChange(fields.map((f, j) => (j === i ? { ...f, ...changes } : f)));
  // Items can't hold items.
  const types = (nested ? fieldTypes.filter((t) => t.id !== "items") : fieldTypes).map((t) => ({
    value: t.id,
    label: t.label,
  }));

  return (
    <Field>
      <FieldLabel>{label}</FieldLabel>
      {fields.map((field, i) => (
        <div key={i} className="flex flex-col gap-2">
          <div className="flex gap-2">
            <Input
              className="w-36"
              placeholder="Name"
              aria-label={`Name of field ${i + 1}`}
              value={field.name}
              onChange={(e) => update(i, { name: e.target.value })}
              // Enter adds the next field, which takes the focus as it appears.
              autoFocus={i > 0 && i === fields.length - 1 && !field.name}
              onKeyDown={(e) => {
                if (e.key === "Enter" && field.name.trim()) onChange([...fields, EMPTY_FIELD]);
              }}
            />
            <Select
              items={types}
              value={field.type}
              onValueChange={(type) =>
                update(i, {
                  type: type as FieldType,
                  fields: type === "items" && !field.fields.length ? [EMPTY_FIELD] : field.fields,
                })
              }
            >
              <SelectTrigger className="w-40" aria-label={`Type of field ${i + 1}`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {types.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              placeholder="Description (optional)"
              aria-label={`Description of field ${i + 1}`}
              value={field.description}
              onChange={(e) => update(i, { description: e.target.value })}
            />
            <Button
              variant="ghost"
              size="icon"
              aria-label="Remove"
              disabled={fields.length <= 1}
              onClick={() => onChange(fields.filter((_, j) => j !== i))}
            >
              <XIcon />
            </Button>
          </div>
          {field.type === "items" && (
            <div className="ml-6">
              <FieldsEditor
                label={`Fields of each item in ${field.name || "the list"}`}
                fields={field.fields}
                fieldTypes={fieldTypes}
                nested
                onChange={(sub) => update(i, { fields: sub })}
              />
            </div>
          )}
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => onChange([...fields, EMPTY_FIELD])}
      >
        <PlusIcon data-icon="inline-start" />
        Add field
      </Button>
      {!nested && (
        <FieldDescription>
          Each field is empty when the text doesn&apos;t give it, rather than guessed.
        </FieldDescription>
      )}
    </Field>
  );
}

function OptionsEditor({
  scale,
  options,
  onChange,
}: {
  scale: boolean;
  options: Option[];
  onChange: (options: Option[]) => void;
}) {
  const update = (i: number, changes: Partial<Option>) =>
    onChange(options.map((o, j) => (j === i ? { ...o, ...changes } : o)));

  return (
    <Field>
      <FieldLabel>{scale ? "Levels, lowest first" : "Options"}</FieldLabel>
      {options.map((option, i) => (
        <div key={i} className="flex gap-2">
          <Input
            className="w-32"
            placeholder="Name"
            aria-label={`Name of ${scale ? "level" : "option"} ${i + 1}`}
            value={option.name}
            onChange={(e) => update(i, { name: e.target.value })}
          />
          <Input
            placeholder="Description (optional)"
            aria-label={`Description of ${scale ? "level" : "option"} ${i + 1}`}
            value={option.description}
            onChange={(e) => update(i, { description: e.target.value })}
          />
          <Button
            variant="ghost"
            size="icon"
            aria-label="Remove"
            disabled={options.length <= 2}
            onClick={() => onChange(options.filter((_, j) => j !== i))}
          >
            <XIcon />
          </Button>
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => onChange([...options, { name: "", description: "" }])}
      >
        <PlusIcon data-icon="inline-start" />
        {scale ? "Add level" : "Add option"}
      </Button>
      <FieldDescription>
        The name is what goes in the result column; the description helps the model choose.
      </FieldDescription>
    </Field>
  );
}

const KINDS = [
  { kind: "decision", label: "Decision models · fast and cheap" },
  { kind: "llm", label: "Language models · slower, can reason" },
] as const;
const RECOMMENDED = "recommended";

/** The models a task asks, as a searchable list: the organisation's own first, then rowlab's,
 * recommended first, then by kind. */
export function ModelPicker({
  value,
  llmOnly = false,
  onChange,
}: {
  value: string[];
  llmOnly?: boolean;
  onChange: (models: string[]) => void;
}) {
  const models = useModels();
  const [search, setSearch] = useState("");
  // The organisation's own, by id; then rowlab's list: recommended first, then the rest by kind,
  // each in the order the server lists them. The rest of OpenRouter's catalog shows only when
  // searching.
  const usable = models.filter((m) => !llmOnly || m.kind === "llm");
  const listed = usable.filter((m) => m.listed);
  const item = (m: Model) => ({
    value: m.id,
    label: m.listed || m.provider_id ? m.name : `${m.name} · ${m.id}`,
    detail: m.provider_id ? m.note || price(m) : price(m),
  });
  const groups: PickGroup[] = [
    { label: "Your models", items: usable.filter((m) => m.provider_id).map(item) },
    { label: "Recommended", items: listed.filter((m) => m.tags.includes(RECOMMENDED)).map(item) },
    ...KINDS.map((k) => ({
      label: k.label,
      items: listed
        .filter((m) => m.kind === k.kind && !m.tags.includes(RECOMMENDED))
        .map(item),
    })),
    {
      label: "More on OpenRouter",
      items: search ? usable.filter((m) => !m.listed && !m.provider_id).map(item) : [],
    },
  ];
  // Models the catalog doesn't (or doesn't yet) know are still shown, by id, so they can be removed.
  const unknown = value.filter((id) => !models.some((m) => m.id === id));
  if (unknown.length) groups.push({ label: "Not offered", items: unknown.map((id) => ({ value: id, label: id })) });

  return (
    <div className="flex flex-col gap-2">
      <PickList
        groups={groups}
        picked={value}
        onPick={(id) =>
          onChange(value.includes(id) ? value.filter((m) => m !== id) : [...value, id])
        }
        onSearch={setSearch}
        placeholder="Find a model…"
        empty="No matching models."
      />
      <p className="px-2 pb-1 text-xs text-muted-foreground">
        Pick several to compare them. Search to find any other model on OpenRouter. Prices are per 1M tokens.
        {!llmOnly &&
          " Decision models are fast and cheap; language models cost more and are slower, but can reason through harder questions."}
      </p>
    </div>
  );
}

function price(model: Model): string {
  if (model.prompt_price == null) return "No price";
  const input = `$${formatNumber(model.prompt_price * 1e6)}`;
  return model.kind === "llm" && model.completion_price != null
    ? `${input} in · $${formatNumber(model.completion_price * 1e6)} out`
    : input;
}
