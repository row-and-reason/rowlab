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

import {
  AnswerSettings,
  ModelPicker,
  modelSlug,
  TYPES,
  withType,
} from "@/components/answer-settings";
import { PromptComposer } from "@/components/prompt-composer";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { FieldGroup } from "@/components/ui/field";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { AnswerType, Dataset, Job, Task } from "@/lib/api/client";

/** The job's tasks as compact rows: the answer type and models are edited in place, and a row
 * expands to its prompt, options and result column. */
export function JobEditor({
  dataset,
  job,
  opened,
  onTasksChange,
  onAddTask,
  runError,
}: {
  dataset: Dataset;
  job: Job;
  opened: string | undefined;
  onTasksChange: (tasks: Task[]) => void;
  onAddTask: (task?: Task) => void;
  runError: string | undefined;
}) {
  const setTask = (task: Task) =>
    onTasksChange(job.tasks.map((t) => (t.id === task.id ? task : t)));

  return (
    <div className="flex flex-col">
      {job.tasks.map((task) => (
        <TaskRow
          key={task.id}
          dataset={dataset}
          job={job}
          task={task}
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

      {runError && (
        <Alert variant="destructive" className="mx-3 w-auto">
          <AlertDescription>{runError}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

function TaskRow({
  dataset,
  job,
  task,
  defaultOpen,
  onChange,
  onDuplicate,
  onDelete,
}: {
  dataset: Dataset;
  job: Job;
  task: Task;
  defaultOpen: boolean;
  onChange: (task: Task) => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  // Whether it starts open is decided once, when the row appears; after that it's yours to toggle.
  const [open, setOpen] = useState(defaultOpen);
  const type = TYPES.find((t) => t.value === task.type)!;
  const models = task.models.map(modelSlug);

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
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuRadioGroup
              value={task.type}
              onValueChange={(value) => onChange(withType(task, value as AnswerType))}
            >
              {TYPES.map((t) => (
                <DropdownMenuRadioItem key={t.value} value={t.value}>
                  {t.label}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>

        <Popover>
          <PopoverTrigger render={<Button variant="outline" size="xs" className="max-w-40" />}>
            <span className="truncate">
              {models[0] ?? "No model"}
              {models.length > 1 && ` +${models.length - 1}`}
            </span>
            <ChevronDownIcon data-icon="inline-end" />
          </PopoverTrigger>
          <PopoverContent align="end" className="w-96">
            <ModelPicker
              id={`models-${task.id}`}
              value={task.models}
              onChange={(models) => onChange({ ...task, models })}
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
          <AnswerSettings task={task} onChange={onChange} />
        </FieldGroup>
      </CollapsibleContent>
    </Collapsible>
  );
}
