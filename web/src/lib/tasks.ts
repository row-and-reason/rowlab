import type {
  AnswerType,
  ExtractField,
  Model,
  Option,
  Preset,
  Task,
  TaskTypes,
} from "@/lib/api/client";

const DEFAULT_LEVELS: Option[] = ["1", "2", "3", "4", "5"].map((name) => ({
  name,
  description: "",
}));
const EMPTY_OPTIONS: Option[] = [
  { name: "", description: "" },
  { name: "", description: "" },
];
export const EMPTY_FIELD: ExtractField = { name: "", type: "text", description: "", fields: [] };

const STARTING_PROMPTS: Record<AnswerType, string> = {
  yes_no: "Does the following text meet [condition to check]? Answer yes or no:\n\n",
  pick_one: "Choose the one option that best describes the following text:\n\n",
  pick_any: "Select all options that apply to the following text:\n\n",
  scale: "Rate the following text on the configured scale for [quality to assess]:\n\n",
  extract:
    "Extract the configured fields from the following text. Leave missing information empty:\n\n",
  write: "Write [what to produce] based on the following text:\n\n",
};

/** Replace the instructions while keeping the row's column references. */
function startingPrompt(template: string, instruction: string): string {
  const columns = template.match(/\{\{[^}]+\}\}/g) ?? [];
  return instruction + columns.join("\n");
}

/**
 * The task with a different answer type. Options carry over unless their meaning changes, and a
 * column still named after the old type is renamed after the new one. Each choice starts a fresh
 * prompt with the existing column references.
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
    preset: null,
    template: startingPrompt(task.template, STARTING_PROMPTS[type]),
    options,
    fields: type === "extract" ? (task.fields.length ? task.fields : [EMPTY_FIELD]) : [],
    reason: type === "write" ? false : task.reason,
    column: task.column === from.column || !task.column ? to.column : task.column,
  };
}

/** Single-value extraction has one internal field; the prompt says what to extract. */
export function withExtraction(task: Task, shape: "single" | "structure", types: TaskTypes): Task {
  const changed = { ...withType(task, "extract", types), extraction_mode: shape };
  if (shape === "single") {
    const type = changed.fields[0].type;
    return {
      ...changed,
      template: startingPrompt(
        task.template,
        "Extract [value to extract] from the following text. Leave it empty if not stated:\n\n",
      ),
      fields: [
        {
          ...EMPTY_FIELD,
          name: "value",
          type: type === "items" || type === "list" ? "text" : type,
        },
      ],
    };
  }
  return changed;
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
  const compatible = task.models.filter((id) => !decision(id));
  return {
    task: { ...task, models: compatible.length ? compatible : [type.model] },
    switchedTo: models.find((m) => m.id === (compatible[0] ?? type.model)),
  };
}

/** A write task started from a preset. The columns the prompt already uses are kept. */
export function withPreset(task: Task, preset: Preset, language?: string): Task {
  const start = language ? preset.template.replace("English", language) : preset.template;
  return {
    ...task,
    type: "write",
    preset: preset.id,
    options: [],
    fields: [],
    reason: false,
    column: language ? `${preset.column}_${language.toLowerCase()}` : preset.column,
    template: startingPrompt(task.template, start),
  };
}

/** How a model appears in column names, as on the server: `typesafe/jev-1.14` → `jev-1.14`. */
export function modelSlug(model: string): string {
  return model.split("/").pop()!;
}
