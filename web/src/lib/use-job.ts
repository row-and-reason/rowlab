"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api, type Job, type JobConfig } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

// One load per dataset at a time, so React's double-run effects in development don't create two jobs.
const loading = new Map<string, Promise<Job | undefined>>();

/** The dataset's job, created on first use. Changes are saved automatically. */
export function useJob(datasetId: string) {
  const [job, setJob] = useState<Job>();
  const saved = useRef("");

  useEffect(() => {
    let current = true;
    if (!loading.has(datasetId)) {
      loading.set(
        datasetId,
        loadOrCreate(datasetId).finally(() => loading.delete(datasetId)),
      );
    }
    loading.get(datasetId)!.then((loaded) => {
      if (!current || !loaded) return;
      saved.current = JSON.stringify(configOf(loaded));
      setJob(loaded);
    });
    return () => {
      current = false;
    };
  }, [datasetId]);

  const save = useCallback(async (job: Job) => {
    const config = configOf(job);
    if (JSON.stringify(config) === saved.current) return;
    const { error } = await api.PUT("/v1/jobs/{job_id}", {
      params: { path: { job_id: job.id } },
      body: config,
    });
    if (error) toast.error(errorMessage(error));
    else saved.current = JSON.stringify(config);
  }, []);

  useEffect(() => {
    if (!job) return;
    const timer = setTimeout(() => save(job), 500);
    return () => clearTimeout(timer);
  }, [job, save]);

  const update = useCallback((changes: Partial<JobConfig> | ((job: Job) => Partial<JobConfig>)) => {
    setJob((job) => job && { ...job, ...(typeof changes === "function" ? changes(job) : changes) });
  }, []);

  /** Save pending changes now, e.g. before a preview runs the saved job. */
  const flush = useCallback(() => (job ? save(job) : Promise.resolve()), [job, save]);

  return { job, update, flush };
}

/** A dataset's job, created with one empty task if it has none yet. */
export async function loadOrCreate(datasetId: string): Promise<Job | undefined> {
  const path = { params: { path: { dataset_id: datasetId } } };
  const { data, error } = await api.GET("/v1/datasets/{dataset_id}/jobs", path);
  if (error) {
    toast.error(errorMessage(error));
    return undefined;
  }
  if (data.length) return data[0];
  // The server starts the job with one empty task.
  const created = await api.POST("/v1/datasets/{dataset_id}/jobs", {
    ...path,
    body: {} as JobConfig,
  });
  if (created.error) {
    toast.error(errorMessage(created.error));
    return undefined;
  }
  return created.data;
}

function configOf(job: Job): JobConfig {
  return { scope: job.scope, tasks: job.tasks };
}
