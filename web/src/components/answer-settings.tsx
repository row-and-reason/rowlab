"use client";

import { InfoIcon, PlusIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Combobox,
  ComboboxChip,
  ComboboxChips,
  ComboboxChipsInput,
  ComboboxCollection,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxGroup,
  ComboboxItem,
  ComboboxLabel,
  ComboboxList,
  ComboboxValue,
  useComboboxAnchor,
} from "@/components/ui/combobox";
import { Checkbox } from "@/components/ui/checkbox";
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
  AnswerType,
  ExtractField,
  FieldType,
  Model,
  Option,
  Preset,
  Task,
  TaskTypes,
} from "@/lib/api/client";
import { useModels } from "@/lib/catalog";
import { formatNumber } from "@/lib/format";

const DEFAULT_LEVELS: Option[] = ["1", "2", "3", "4", "5"].map((name) => ({
  name,
  description: "",
}));
const EMPTY_OPTIONS: Option[] = [
  { name: "", description: "" },
  { name: "", description: "" },
];
const EMPTY_FIELD: ExtractField = { name: "", type: "text", description: "", fields: [] };

/**
 * The task with a different answer type. Options carry over unless their meaning changes, and a
 * column still named after the old type is renamed after the new one.
 */
export function withType(task: Task, type: AnswerType, types: TaskTypes): Task {
  const from = types.types.find((t) => t.id === task.type)!;
  const to = types.types.find((t) => t.id === type)!;
  // Scale levels and pick options mean different things, so switching between them starts over.
  const keep = (task.type === "scale") === (type === "scale") && task.options.length > 0;
  const options =
    to.family !== "classify" || type === "yes_no"
      ? []
      : keep
        ? task.options
        : type === "scale"
          ? DEFAULT_LEVELS
          : EMPTY_OPTIONS;
  return {
    ...task,
    type,
    options,
    fields: type === "extract" ? (task.fields.length ? task.fields : [EMPTY_FIELD]) : [],
    reason: type === "write" ? false : task.reason,
    column: task.column === from.column || !task.column ? to.column : task.column,
  };
}

/**
 * The task with models that can give its type of answer: decision models give way to the type's
 * default language model if it needs one. Returns the model it switched to, if it did.
 */
export function withFittingModels(
  task: Task,
  types: TaskTypes,
  models: Model[],
): { task: Task; switchedTo?: Model } {
  const type = types.types.find((t) => t.id === task.type)!;
  const decision = (id: string) => models.find((m) => m.id === id)?.kind === "decision";
  if (!type.llm_only || !task.models.some(decision)) return { task };
  return {
    task: { ...task, models: [type.model] },
    switchedTo: models.find((m) => m.id === type.model),
  };
}

/** A write task started from a preset. The columns the prompt already uses are kept. */
export function withPreset(task: Task, preset: Preset, language?: string): Task {
  const start = language ? preset.template.replace("English", language) : preset.template;
  const columns = task.template.match(/\{\{[^}]+\}\}/g) ?? [];
  return {
    ...task,
    type: "write",
    options: [],
    fields: [],
    reason: false,
    column: language ? `${preset.column}_${language.toLowerCase()}` : preset.column,
    template: start + columns.join("\n"),
  };
}

/** A task's options, fields, reason and result column, as its answer type needs. */
export function AnswerSettings({
  task,
  types,
  models,
  onChange,
}: {
  task: Task;
  types: TaskTypes;
  models: Model[];
  onChange: (task: Task) => void;
}) {
  const family = types.types.find((t) => t.id === task.type)?.family;
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
      {task.type === "extract" && (
        <FieldsEditor
          label="Fields"
          fields={task.fields}
          fieldTypes={types.field_types}
          onChange={(fields) => onChange({ ...task, fields })}
        />
      )}
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
              {columnsDescription(task)}
            </PopoverContent>
          </Popover>
        </div>
        <Input
          id={`column-${task.id}`}
          value={task.column}
          onChange={(e) => onChange({ ...task, column: e.target.value })}
        />
      </Field>
      {family !== "write" && (
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

/** How a model appears in column names, as on the server: `typesafe/jev-1.14` → `jev-1.14`. */
export function modelSlug(model: string): string {
  return model.split("/").pop()!;
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

export function ModelPicker({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string[];
  onChange: (models: string[]) => void;
}) {
  const models = useModels();
  const anchor = useComboboxAnchor();

  const groups = KINDS.map((k) => ({
    value: k.label,
    items: models.filter((m) => m.kind === k.kind),
  }));
  // Models the catalog doesn't (or doesn't yet) know are still shown, by id.
  const selected = value.map(
    (id) =>
      models.find((m) => m.id === id) ??
      ({
        id,
        name: id,
        kind: "decision",
        prompt_price: 0,
        completion_price: 0,
        context_length: 0,
      } as Model),
  );

  return (
    <Field>
      <FieldLabel htmlFor={id}>Models</FieldLabel>
      <Combobox
        multiple
        items={groups}
        value={selected}
        onValueChange={(picked: Model[], details) => {
          // Escape on a closed picker would otherwise remove every model.
          if (details.reason !== "escape-key") onChange(picked.map((m) => m.id));
        }}
        itemToStringLabel={(model: Model) => model.name}
        isItemEqualToValue={(a: Model, b: Model) => a.id === b.id}
      >
        <ComboboxChips ref={anchor}>
          <ComboboxValue>
            {(picked: Model[]) => (
              <>
                {picked.map((model) => (
                  <ComboboxChip key={model.id}>{model.name}</ComboboxChip>
                ))}
                <ComboboxChipsInput id={id} placeholder={picked.length ? "" : "Pick models"} />
              </>
            )}
          </ComboboxValue>
        </ComboboxChips>
        <ComboboxContent anchor={anchor}>
          <ComboboxEmpty>No matching models.</ComboboxEmpty>
          <ComboboxList>
            {(group: (typeof groups)[number]) => (
              <ComboboxGroup key={group.value} items={group.items}>
                <ComboboxLabel>{group.value}</ComboboxLabel>
                <ComboboxCollection>
                  {(model: Model) => (
                    <ComboboxItem key={model.id} value={model}>
                      <span className="truncate">{model.name}</span>
                      <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                        {price(model)}
                      </span>
                    </ComboboxItem>
                  )}
                </ComboboxCollection>
              </ComboboxGroup>
            )}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
      <FieldDescription>
        Pick several to compare them. Decision models are fast and cheap; language models cost more
        and are slower, but can reason through harder questions.
      </FieldDescription>
    </Field>
  );
}

function price(model: Model): string {
  const input = `$${formatNumber(model.prompt_price * 1e6)}`;
  return model.kind === "llm"
    ? `${input} in · $${formatNumber(model.completion_price * 1e6)} out`
    : input;
}
