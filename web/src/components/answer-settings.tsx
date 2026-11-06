"use client";

import { PlusIcon, XIcon } from "lucide-react";
import { useEffect, useState } from "react";

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
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { api, type AnswerType, type Model, type Option, type Task } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";

export const TYPES: { value: AnswerType; label: string; description: string }[] = [
  { value: "yes_no", label: "Yes / no", description: "A yes or no for each row." },
  { value: "pick_one", label: "Pick one", description: "One of your options for each row." },
  { value: "pick_any", label: "Pick any", description: "Any number of your options per row." },
  { value: "scale", label: "Scale", description: "A level on your scale for each row." },
];

const DEFAULT_LEVELS: Option[] = ["1", "2", "3", "4", "5"].map((name) => ({ name, description: "" }));
const EMPTY_OPTIONS: Option[] = [
  { name: "", description: "" },
  { name: "", description: "" },
];

/** The task with a different answer type. Options carry over unless their meaning changes. */
export function withType(task: Task, type: AnswerType): Task {
  // Scale levels and pick options mean different things, so switching between them starts over.
  const keep = (task.type === "scale") === (type === "scale") && task.options.length > 0;
  const options = keep ? task.options : type === "scale" ? DEFAULT_LEVELS : EMPTY_OPTIONS;
  return { ...task, type, options: type === "yes_no" ? [] : options };
}

/** A task's options (for pick and scale answers) and its result column. */
export function AnswerSettings({ task, onChange }: { task: Task; onChange: (task: Task) => void }) {
  return (
    <>
      {task.type !== "yes_no" && (
        <OptionsEditor
          scale={task.type === "scale"}
          options={task.options}
          onChange={(options) => onChange({ ...task, options })}
        />
      )}
      <Field>
        <FieldLabel htmlFor={`column-${task.id}`}>Result column</FieldLabel>
        <Input
          id={`column-${task.id}`}
          value={task.column}
          onChange={(e) => onChange({ ...task, column: e.target.value })}
        />
        <FieldDescription>{columnsDescription(task)}</FieldDescription>
      </Field>
    </>
  );
}

function columnsDescription(task: Task): string {
  const column = task.column || "answer";
  const model = modelSlug(task.models[0] ?? "model");
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
  return `Each model writes its own columns: ${answer} (${value}) and its _proba column, how likely it is right.`;
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
  const [models, setModels] = useState<Model[]>([]);
  const anchor = useComboboxAnchor();

  useEffect(() => {
    api.GET("/v1/models").then(({ data }) => data && setModels(data));
  }, []);

  const groups = KINDS.map((k) => ({
    value: k.label,
    items: models.filter((m) => m.kind === k.kind),
  }));
  // Models the catalog doesn't (or doesn't yet) know are still shown, by id.
  const selected = value.map(
    (id) =>
      models.find((m) => m.id === id) ??
      ({ id, name: id, kind: "decision", prompt_price: 0, completion_price: 0, context_length: 0 } as Model),
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
        Pick several to compare them. Decision models are fast and cheap; language models cost
        more and are slower, but can reason through harder questions.
      </FieldDescription>
    </Field>
  );
}

function price(model: Model): string {
  const input = `$${formatNumber(model.prompt_price * 1e6)}`;
  return model.kind === "llm" ? `${input} in · $${formatNumber(model.completion_price * 1e6)} out` : input;
}
