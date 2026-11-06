"use client";

import {
  ChevronDownIcon,
  ChevronRightIcon,
  CopyIcon,
  EllipsisIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  AnswerSettings,
  ModelPicker,
  modelSlug,
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
import { FieldGroup } from "@/components/ui/field";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { AnswerType, Dataset, Job, Model, Task, TaskTypes } from "@/lib/api/client";
import { useModels, useTaskTypes } from "@/lib/catalog";

/** The job's tasks as compact rows: the answer type and models are edited in place, and a row
 * expands to its prompt, options and result column. */
export function JobEditor({
  dataset,
  job,
  opened,
  onTasksChange,
  onAddTask,
  runError,
  problem,
}: {
  dataset: Dataset;
  job: Job;
  opened: string | undefined;
  onTasksChange: (tasks: Task[]) => void;
  onAddTask: (task?: Task) => void;
  runError: string | undefined;
  problem: string | undefined;
}) {
  const types = useTaskTypes();
  const models = useModels();
  const setTask = (task: Task) =>
    onTasksChange(job.tasks.map((t) => (t.id === task.id ? task : t)));

  if (!types) return null;
  return (
    <div className="flex flex-col">
      {job.tasks.map((task) => (
        <TaskRow
          key={task.id}
          dataset={dataset}
          job={job}
          task={task}
          types={types}
          models={models}
          defaultOpen={task.id === opened || job.tasks.length === 1 || !task.template}
          onChange={setTask}
          onDuplicate={() => onAddTask({ ...task, column: `${task.column}_copy` })}
          onDelete={() => onTasksChange(job.tasks.filter((t) => t.id !== task.id))}
        />
      ))}
      <Button variant="ghost" size="sm" className="m-2 self-start" onClick={() => onAddTask()}>
        <PlusIcon data-icon="inline-start" />
        Add task
      </Button>

      {runError ? (
        <Alert variant="destructive" className="mx-3 w-auto">
          <AlertDescription>{runError}</AlertDescription>
        </Alert>
      ) : (
        // What still needs doing before it can run, as you type.
        problem && <p className="mx-4 text-sm text-muted-foreground">{problem}</p>
      )}
    </div>
  );
}

const FAMILIES = [
  { family: "classify", label: "Classify · any model" },
  { family: "extract", label: "Extract · language models" },
  { family: "write", label: "Write · language models" },
] as const;

function TaskRow({
  dataset,
  job,
  task,
  types,
  models,
  defaultOpen,
  onChange,
  onDuplicate,
  onDelete,
}: {
  dataset: Dataset;
  job: Job;
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
      <div className="flex items-center gap-1 px-2 py-1.5">
        <CollapsibleTrigger
          render={<Button variant="ghost" size="sm" className="min-w-0 flex-1 justify-start" />}
        >
          <ChevronRightIcon
            data-icon="inline-start"
            className="transition-transform in-data-[panel-open]:rotate-90"
          />
          <span className="truncate font-medium">{task.column || "Untitled task"}</span>
        </CollapsibleTrigger>

        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="outline" size="xs" />}>
            {type.label}
            <ChevronDownIcon data-icon="inline-end" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuRadioGroup
              value={task.type}
              onValueChange={(value) => change(withType(task, value as AnswerType, types))}
            >
              {FAMILIES.map(({ family, label }, i) => (
                <DropdownMenuGroup key={family}>
                  {i > 0 && <DropdownMenuSeparator />}
                  <DropdownMenuLabel>{label}</DropdownMenuLabel>
                  {types.types
                    .filter((t) => t.family === family)
                    .map((t) => (
                      <DropdownMenuRadioItem key={t.id} value={t.id} title={t.description}>
                        {t.label}
                      </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuGroup>
              ))}
            </DropdownMenuRadioGroup>
            {/* Starting points for writing: each fills in the prompt and names the column. */}
            {types.presets.map((preset) =>
              preset.id === "translate" ? (
                <DropdownMenuSub key={preset.id}>
                  <DropdownMenuSubTrigger inset>{preset.label}</DropdownMenuSubTrigger>
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
                <DropdownMenuItem
                  key={preset.id}
                  inset
                  onClick={() => change(withPreset(task, preset))}
                >
                  {preset.label}
                </DropdownMenuItem>
              ),
            )}
          </DropdownMenuContent>
        </DropdownMenu>

        <Popover>
          <PopoverTrigger render={<Button variant="outline" size="xs" className="max-w-40" />}>
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
            <DropdownMenuItem
              variant="destructive"
              disabled={job.tasks.length === 1}
              onClick={onDelete}
            >
              <Trash2Icon />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <CollapsibleContent>
        <FieldGroup className="gap-5 px-4 pt-1 pb-4">
          <PromptComposer
            dataset={dataset}
            scope={job.scope}
            template={task.template}
            onChange={(template) => onChange({ ...task, template })}
          />
          <AnswerSettings task={task} types={types} models={models} onChange={change} />
        </FieldGroup>
      </CollapsibleContent>
    </Collapsible>
  );
}
