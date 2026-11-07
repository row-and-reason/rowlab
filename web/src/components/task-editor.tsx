"use client";

import {
  ChevronDownIcon,
  ChevronRightIcon,
  CopyIcon,
  EllipsisIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import {
  AnswerSettings,
  ModelPicker,
  modelSlug,
  withExtraction,
  withFittingModels,
  withPreset,
  withType,
} from "@/components/answer-settings";
import { PromptComposer } from "@/components/prompt-composer";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCan } from "@/components/me";
import { FieldGroup } from "@/components/ui/field";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Dataset, Model, Task, TaskTypes } from "@/lib/api/client";
import { useModels, useTaskTypes } from "@/lib/catalog";
import { settingsUrl } from "@/lib/settings";

/** The next run's tasks as compact rows: the answer type and models are edited in place, and a row
 * expands to its prompt, options and result column. `sql` picks the rows its prompt is previewed on. */
export function TaskEditor({
  dataset,
  tasks,
  sql,
  opened,
  onTasksChange,
  onAddTask,
  runError,
  problem,
  needsKey,
}: {
  dataset: Dataset;
  tasks: Task[];
  sql: string;
  opened: string | undefined;
  onTasksChange: (tasks: Task[]) => void;
  onAddTask: (task?: Task) => void;
  runError: string | undefined;
  problem: string | undefined;
  /** No OpenRouter key yet: runs can't start until an admin adds one. */
  needsKey: boolean;
}) {
  const types = useTaskTypes();
  const params = useSearchParams();
  const isAdmin = useCan("admin");
  // The first thing to fix, before anything about the tasks.
  const keyLink = (
    <Link href={settingsUrl(params, "providers")} className="underline">
      Settings → Providers
    </Link>
  );
  const hint = needsKey ? (
    <>
      No OpenRouter key yet: {isAdmin ? <>add one in {keyLink}</> : "an admin adds one in Settings"}
      .
    </>
  ) : (
    problem
  );
  const models = useModels();
  const setTask = (task: Task) => onTasksChange(tasks.map((t) => (t.id === task.id ? task : t)));

  if (!types) return null;
  return (
    <div className="flex flex-col">
      {tasks.map((task) => (
        <TaskRow
          key={task.id}
          dataset={dataset}
          sql={sql}
          only={tasks.length === 1}
          task={task}
          types={types}
          models={models}
          defaultOpen={task.id === opened || tasks.length === 1 || !task.template}
          onChange={setTask}
          onDuplicate={() => onAddTask({ ...task, column: `${task.column}_copy` })}
          onDelete={() => onTasksChange(tasks.filter((t) => t.id !== task.id))}
        />
      ))}
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <Button variant="ghost" size="sm" className="text-xs" onClick={() => onAddTask()}>
          <PlusIcon data-icon="inline-start" />
          Add task
        </Button>
        {!runError && hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
      {runError && (
        <Alert variant="destructive" className="mx-3 w-auto">
          <AlertDescription>
            <p>
              {runError}
              {needsKey && isAdmin && <> Add one in {keyLink}.</>}
            </p>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}

const FAMILIES = [
  { family: "classify", label: "Classification" },
  { family: "extract", label: "Extraction" },
  { family: "write", label: "Generation" },
] as const;

function TaskRow({
  dataset,
  sql,
  only,
  task,
  types,
  models,
  defaultOpen,
  onChange,
  onDuplicate,
  onDelete,
}: {
  dataset: Dataset;
  sql: string;
  /** The only task, which can't be deleted. */
  only: boolean;
  task: Task;
  types: TaskTypes;
  models: Model[];
  defaultOpen: boolean;
  onChange: (task: Task) => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  // Whether it starts open is decided once, when the row appears; after that it's yours to toggle.
  const [open, setOpen] = useState(defaultOpen);
  const type = types.types.find((t) => t.id === task.type)!;
  const extraction = task.extraction_mode ?? "structure";
  const preset =
    task.type === "write" ? types.presets.find((p) => p.id === task.preset) : undefined;
  const choice = task.type === "extract" ? extraction : (preset?.id ?? task.type);
  const label =
    task.type === "extract"
      ? extraction === "single"
        ? "Single value"
        : "Typed structure"
      : (preset?.label ?? type.label);

  // A new answer type may need other models: say so when switching to them.
  function change(changed: Task) {
    const fitted = withFittingModels(changed, types, models);
    onChange(fitted.task);
    if (fitted.switchedTo) {
      const label = types.types.find((t) => t.id === changed.type)!.label;
      toast(`Switched to ${fitted.switchedTo.name}: ${label} needs a language model.`);
    }
  }
  const slugs = task.models.map(modelSlug);

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border-b">
      <div className="flex items-center gap-2 px-3 py-2">
        <CollapsibleTrigger
          render={
            <Button
              variant="ghost"
              size="sm"
              className="min-w-0 flex-1 justify-start text-sm aria-expanded:bg-transparent"
            />
          }
        >
          <ChevronRightIcon
            data-icon="inline-start"
            className="transition-transform in-data-[panel-open]:rotate-90"
          />
          <span className="truncate font-medium">{task.column || "Untitled task"}</span>
        </CollapsibleTrigger>

        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="outline" size="sm" className="text-xs" />}>
            {label}
            <ChevronDownIcon data-icon="inline-end" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuRadioGroup value={choice}>
              {FAMILIES.map(({ family, label }, i) => (
                <DropdownMenuGroup key={family}>
                  {i > 0 && <DropdownMenuSeparator />}
                  <DropdownMenuLabel>{label}</DropdownMenuLabel>
                  {family === "extract" ? (
                    <>
                      <DropdownMenuRadioItem
                        value="single"
                        onClick={() => change(withExtraction(task, "single", types))}
                      >
                        Single value
                      </DropdownMenuRadioItem>
                      <DropdownMenuRadioItem
                        value="structure"
                        onClick={() => change(withExtraction(task, "structure", types))}
                      >
                        Typed structure
                      </DropdownMenuRadioItem>
                    </>
                  ) : (
                    types.types
                      .filter((t) => t.family === family)
                      .map((t) => (
                        <DropdownMenuRadioItem
                          key={t.id}
                          value={t.id}
                          title={t.description}
                          onClick={() => change(withType(task, t.id, types))}
                        >
                          {t.label}
                        </DropdownMenuRadioItem>
                      ))
                  )}
                  {family === "write" &&
                    types.presets.map((preset) =>
                      preset.id === "translate" ? (
                        <DropdownMenuSub key={preset.id}>
                          <DropdownMenuSubTrigger>{preset.label}</DropdownMenuSubTrigger>
                          <DropdownMenuSubContent>
                            {types.languages.map((language) => (
                              <DropdownMenuItem
                                key={language}
                                onClick={() => change(withPreset(task, preset, language))}
                              >
                                {language}
                              </DropdownMenuItem>
                            ))}
                          </DropdownMenuSubContent>
                        </DropdownMenuSub>
                      ) : (
                        <DropdownMenuRadioItem
                          key={preset.id}
                          value={preset.id}
                          onClick={() => change(withPreset(task, preset))}
                        >
                          {preset.label}
                        </DropdownMenuRadioItem>
                      ),
                    )}
                </DropdownMenuGroup>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>

        <Popover>
          <PopoverTrigger
            render={<Button variant="outline" size="sm" className="max-w-36 text-xs" />}
          >
            <span className="truncate">
              {slugs[0] ?? "No model"}
              {slugs.length > 1 && ` +${slugs.length - 1}`}
            </span>
            <ChevronDownIcon data-icon="inline-end" />
          </PopoverTrigger>
          <PopoverContent align="end" className="w-96">
            <ModelPicker
              id={`models-${task.id}`}
              value={task.models}
              llmOnly={type.llm_only}
              onChange={(picked) => onChange({ ...task, models: picked })}
            />
          </PopoverContent>
        </Popover>

        <DropdownMenu>
          <DropdownMenuTrigger
            render={<Button variant="ghost" size="icon-sm" aria-label="Task actions" />}
          >
            <EllipsisIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={onDuplicate}>
              <CopyIcon />
              Duplicate
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" disabled={only} onClick={onDelete}>
              <Trash2Icon />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <CollapsibleContent>
        <FieldGroup className="gap-4 px-3 pt-2 pb-4">
          <PromptComposer
            dataset={dataset}
            sql={sql}
            template={task.template}
            onChange={(template) => onChange({ ...task, template })}
          />
          <AnswerSettings task={task} types={types} models={models} onChange={change} />
        </FieldGroup>
      </CollapsibleContent>
    </Collapsible>
  );
}
