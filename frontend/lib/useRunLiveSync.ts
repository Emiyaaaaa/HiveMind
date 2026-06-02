"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import {
  applyRunEvent,
  isLiveRunStatus,
  patchRunInList,
  shouldReconcileRun,
} from "@/lib/run-events";
import type { Run } from "@/lib/types";
import { useDebouncedCallback } from "@/lib/useDebouncedCallback";
import {
  useMultiRunEventSource,
  useRunEventSource,
} from "@/lib/useRunEventSource";

const RECONCILE_DELAY_MS = 1_000;

export function useRunsListLiveSync(liveRunIds: string[]) {
  const queryClient = useQueryClient();

  const reconcileRuns = useDebouncedCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["runs"] });
  }, RECONCILE_DELAY_MS);

  useMultiRunEventSource({
    runIds: liveRunIds,
    onEvent: (event) => {
      queryClient.setQueryData<Run[]>(["runs"], (current) =>
        current ? patchRunInList(current, event) : current,
      );
      if (shouldReconcileRun(event.type)) {
        reconcileRuns();
      }
    },
    onTerminal: () => {
      reconcileRuns.cancel();
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

export function useRunWithLiveUpdates(runId: string) {
  const queryClient = useQueryClient();

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId),
  });

  const enabled = run.data != null && isLiveRunStatus(run.data.status);

  const reconcileRun = useDebouncedCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["run", runId] });
  }, RECONCILE_DELAY_MS);

  const stream = useRunEventSource({
    runId,
    enabled,
    onEvent: (event) => {
      queryClient.setQueryData<Run>(["run", runId], (current) =>
        current ? applyRunEvent(current, event) : current,
      );
      queryClient.setQueryData<Run[]>(["runs"], (current) =>
        current ? patchRunInList(current, event) : current,
      );
      if (shouldReconcileRun(event.type)) {
        reconcileRun();
      }
    },
    onTerminal: () => {
      reconcileRun.cancel();
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });

  return {
    ...run,
    events: stream.events,
    streamStatus: stream.status,
    isLive: enabled,
  };
}

export function liveRunIdsFromRuns(runs: Run[] | undefined): string[] {
  if (!runs) return [];
  return runs
    .filter((run) => isLiveRunStatus(run.status))
    .map((run) => run.id);
}
