"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { api, type Model, type TaskTypes } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

// Fetched once per page load: the models and answer types don't change while the app is open.
let models: Promise<Model[]> | undefined;
let taskTypes: Promise<TaskTypes | undefined> | undefined;
type ModelCatalog = { models: Model[]; loading: boolean; error?: string };
const initialModels: ModelCatalog = { models: [], loading: true };
let modelCatalog = initialModels;
const modelListeners = new Set<() => void>();

function publishModels(value: ModelCatalog) {
  modelCatalog = value;
  for (const listener of modelListeners) listener();
}
function subscribeModels(listener: () => void) {
  modelListeners.add(listener);
  return () => {
    modelListeners.delete(listener);
  };
}
function loadModels() {
  if (models) return;
  publishModels({ ...modelCatalog, loading: true, error: undefined });
  models = api
    .GET("/v1/utils/models")
    .then(({ data, error }) => {
      if (!data) throw new Error(errorMessage(error));
      publishModels({ models: data, loading: false });
      return data;
    })
    .catch((error) => {
      models = undefined;
      publishModels({
        models: [],
        loading: false,
        error: error instanceof Error ? error.message : "Could not load models.",
      });
      return [];
    });
}

/** OpenRouter's decision models and LLMs, cheapest first within each kind. */
export function useModels(): Model[] {
  return useModelCatalog().models;
}

export function useModelCatalog() {
  const loaded = useSyncExternalStore(
    subscribeModels,
    () => modelCatalog,
    () => initialModels,
  );
  useEffect(loadModels, []);
  return {
    ...loaded,
    retry: () => {
      models = undefined;
      loadModels();
    },
  };
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
