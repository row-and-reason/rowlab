"use client";

import { useEffect, useState } from "react";

import { api, type Model, type TaskTypes } from "@/lib/api/client";

// Fetched once per page load: the models and answer types don't change while the app is open.
let models: Promise<Model[]> | undefined;
let taskTypes: Promise<TaskTypes | undefined> | undefined;

/** OpenRouter's decision models and LLMs, cheapest first within each kind. */
export function useModels(): Model[] {
  const [loaded, setLoaded] = useState<Model[]>([]);
  useEffect(() => {
    models ??= api.GET("/v1/utils/models").then(({ data }) => data ?? []);
    models.then(setLoaded);
  }, []);
  return loaded;
}

/** The answer types (classify, extract, write), write presets and field types. */
export function useTaskTypes(): TaskTypes | undefined {
  const [loaded, setLoaded] = useState<TaskTypes>();
  useEffect(() => {
    taskTypes ??= api.GET("/v1/utils/task-types").then(({ data }) => data);
    taskTypes.then(setLoaded);
  }, []);
  return loaded;
}
