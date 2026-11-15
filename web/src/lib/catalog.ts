"use client";

import { useEffect, useState } from "react";

import { api, type Model, type TaskTypes } from "@/lib/api/client";

// Fetched once per page load: the models and answer types don't change while the app is open.
let models: Promise<Model[]> | undefined;
let taskTypes: Promise<TaskTypes | undefined> | undefined;

/** The models a task can use, decision models and LLMs: rowlab's list (`listed`), in the order we'd
 * pick them, then the rest of OpenRouter's catalog. */
export function useModels(): Model[] {
  const [loaded, setLoaded] = useState<Model[]>([]);
  useEffect(() => {
    models ??= api.GET("/v1/utils/models", { params: { query: { all: true } } }).then(({ data }) => {
      // rowlab may be unreachable: ask again next time rather than keep an empty list.
      if (!data) models = undefined;
      return data ?? [];
    });
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
