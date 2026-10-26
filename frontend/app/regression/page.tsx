"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import type { Run, RunComparison, RunStatus } from "@/lib/types";

const TERMINAL: RunStatus[] = ["succeeded", "failed", "cancelled"];

function isTerminal(status: RunStatus): boolean {
  return TERMINAL.includes(status);
}

function ChangeFlags({ comparison }: { comparison: RunComparison }) {
  const flags: { key: string; changed: boolean; diagnostic?: boolean }[] = [
    { key: "version", changed: comparison.agent_version_changed },
    { key: "status", changed: comparison.status_changed },
    { key: "error", changed: comparison.error_changed },
    { key: "input", changed: comparison.input_changed },
    {
      key: "output",
      changed: comparison.output_changed,
      diagnostic: true,
    },
  ];
  return (
    <div className="flex flex-wrap gap-2 text-xs font-mono">
      {flags.map((f) => (
        <span
          key={f.key}
          className={
            f.changed
              ? f.diagnostic
                ? "rounded px-2 py-0.5 bg-warn/20 text-warn"
                : "rounded px-2 py-0.5 bg-bad/20 text-bad"
              : "rounded px-2 py-0.5 bg-border text-muted"
          }
        >
          {f.key}
          {f.changed ? (f.diagnostic ? " Δ" : " changed") : " same"}
        </span>
      ))}
    </div>
  );
}

function SideSummary({
  label,
  side,
}: {
  label: string;
  side: RunComparison["baseline"];
}) {
  return (
    <div className="rounded border border-border bg-bg p-3 space-y-1 text-sm">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="font-mono">
        <Link className="hover:text-accent" href={`/runs/${side.run_id}`}>
          {side.run_id}
        </Link>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted">
        <StatusBadge status={side.status as RunStatus} />
        <span>
          v{side.agent_version ?? "—"} · agent {side.agent_id}
        </span>
      </div>
      {side.error ? (
        <p className="text-xs text-bad font-mono break-all">{side.error}</p>
      ) : null}
    </div>
  );
}

export default function RegressionPage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.listRuns });

  const [baselineId, setBaselineId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [selectedBaselines, setSelectedBaselines] = useState<string[]>([]);
  const [executionId, setExecutionId] = useState<string | null>(null);

  const terminalRuns = useMemo(
    () => (runs.data ?? []).filter((r) => isTerminal(r.status)),
    [runs.data],
  );

  const selectedAgentId = useMemo(() => {
    if (selectedBaselines.length === 0) return null;
    const first = terminalRuns.find((r) => r.id === selectedBaselines[0]);
    return first?.agent_id ?? null;
  }, [selectedBaselines, terminalRuns]);

  const compare = useMutation({
    mutationFn: () =>
      api.previewRunComparison({
        baseline_run_id: baselineId.trim(),
        candidate_run_id: candidateId.trim(),
      }),
  });

  const startRegression = useMutation({
    mutationFn: () =>
      api.createRegressionExecution({ baseline_run_ids: selectedBaselines }),
    onSuccess: (exec) => {
      setExecutionId(exec.execution_id);
    },
  });

  const execution = useQuery({
    queryKey: ["regression-execution", executionId],
    queryFn: () => api.getRegressionExecution(executionId!),
    enabled: !!executionId,
    refetchInterval: (query) =>
      query.state.data?.status === "completed" ? false : 1500,
  });

  const results = useQuery({
    queryKey: ["regression-results", executionId],
    queryFn: () => api.getRegressionResults(executionId!),
    enabled: !!executionId && execution.data?.status === "completed",
  });

  function toggleBaseline(run: Run) {
    setSelectedBaselines((prev) => {
      if (prev.includes(run.id)) {
        return prev.filter((id) => id !== run.id);
      }
      if (prev.length === 0) return [run.id];
      const agentId = terminalRuns.find((r) => r.id === prev[0])?.agent_id;
      if (agentId && run.agent_id !== agentId) return prev;
      if (prev.length >= 100) return prev;
      return [...prev, run.id];
    });
  }

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Regression</h1>
        <p className="text-sm text-muted">
          Compare terminal runs or replay baselines against the agent&apos;s
          current version. Output deltas are diagnostic only; pass/fail uses
          status and error.
        </p>
      </header>

      <section className="rounded-lg border border-border bg-surface p-5 space-y-4">
        <h2 className="font-medium">Compare two runs</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1">
            <span className="text-xs uppercase tracking-wide text-muted">
              Baseline run ID
            </span>
            <input
              className="w-full rounded bg-bg border border-border px-3 py-2 text-sm font-mono"
              value={baselineId}
              onChange={(e) => setBaselineId(e.target.value)}
              placeholder="01HZ…"
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs uppercase tracking-wide text-muted">
              Candidate run ID
            </span>
            <input
              className="w-full rounded bg-bg border border-border px-3 py-2 text-sm font-mono"
              value={candidateId}
              onChange={(e) => setCandidateId(e.target.value)}
              placeholder="01HZ…"
            />
          </label>
        </div>
        <button
          className="rounded bg-accent text-bg px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50"
          onClick={() => compare.mutate()}
          disabled={
            compare.isPending || !baselineId.trim() || !candidateId.trim()
          }
        >
          {compare.isPending ? "Comparing…" : "Preview comparison"}
        </button>
        {compare.error ? (
          <p className="text-bad text-sm">{(compare.error as Error).message}</p>
        ) : null}
        {compare.data ? (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <SideSummary label="Baseline" side={compare.data.baseline} />
              <SideSummary label="Candidate" side={compare.data.candidate} />
            </div>
            <ChangeFlags comparison={compare.data} />
          </div>
        ) : null}
      </section>

      <section className="rounded-lg border border-border bg-surface p-5 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-medium">Regression suite</h2>
            <p className="text-xs text-muted mt-1">
              Select 1–100 terminal baselines from the same agent. Candidates
              are pinned to the current agent version and enqueued normally.
            </p>
          </div>
          <button
            className="rounded bg-accent text-bg px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50 shrink-0"
            onClick={() => startRegression.mutate()}
            disabled={
              startRegression.isPending || selectedBaselines.length === 0
            }
          >
            {startRegression.isPending
              ? "Starting…"
              : `Run suite (${selectedBaselines.length})`}
          </button>
        </div>
        {selectedAgentId ? (
          <p className="text-xs text-muted font-mono">
            agent {selectedAgentId} · {selectedBaselines.length} selected
          </p>
        ) : null}
        {startRegression.error ? (
          <p className="text-bad text-sm">
            {(startRegression.error as Error).message}
          </p>
        ) : null}

        {runs.isLoading ? (
          <p className="text-muted text-sm">Loading runs…</p>
        ) : terminalRuns.length === 0 ? (
          <p className="text-muted text-sm">
            No terminal runs yet.{" "}
            <Link href="/runs" className="hover:text-accent">
              Browse runs
            </Link>
          </p>
        ) : (
          <table className="w-full text-sm border border-border rounded-lg overflow-hidden bg-bg">
            <thead className="text-left text-muted">
              <tr>
                <th className="px-3 py-2 font-medium w-10" />
                <th className="px-3 py-2 font-medium">Run</th>
                <th className="px-3 py-2 font-medium">Agent</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {terminalRuns.map((r) => {
                const checked = selectedBaselines.includes(r.id);
                const blocked =
                  selectedAgentId != null &&
                  r.agent_id !== selectedAgentId &&
                  !checked;
                return (
                  <tr
                    key={r.id}
                    className={
                      blocked
                        ? "opacity-40"
                        : "hover:bg-surface/80 cursor-pointer"
                    }
                    onClick={() => {
                      if (!blocked) toggleBaseline(r);
                    }}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={blocked}
                        onChange={() => toggleBaseline(r)}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </td>
                    <td className="px-3 py-2 font-mono">
                      <Link
                        className="hover:text-accent"
                        href={`/runs/${r.id}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {r.id}
                      </Link>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{r.agent_id}</td>
                    <td className="px-3 py-2">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="px-3 py-2 text-xs text-muted">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {executionId ? (
        <section className="rounded-lg border border-border bg-surface p-5 space-y-4">
          <header className="flex items-center justify-between gap-4">
            <div>
              <h2 className="font-medium">Execution</h2>
              <p className="text-xs text-muted font-mono mt-1">{executionId}</p>
            </div>
            {execution.data ? (
              <div className="text-sm text-muted">
                <span className="font-mono uppercase text-accent">
                  {execution.data.status}
                </span>
                {" · "}
                {execution.data.completed_cases}/{execution.data.total_cases}{" "}
                cases · candidate v
                {execution.data.candidate_agent_version}
              </div>
            ) : null}
          </header>
          {execution.error ? (
            <p className="text-bad text-sm">
              {(execution.error as Error).message}
            </p>
          ) : null}
          {execution.data ? (
            <table className="w-full text-sm border border-border rounded-lg overflow-hidden bg-bg">
              <thead className="text-left text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Baseline</th>
                  <th className="px-3 py-2 font-medium">Candidate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {execution.data.cases.map((c) => (
                  <tr key={`${c.baseline_run_id}-${c.candidate_run_id}`}>
                    <td className="px-3 py-2 font-mono">
                      <Link
                        className="hover:text-accent"
                        href={`/runs/${c.baseline_run_id}`}
                      >
                        {c.baseline_run_id}
                      </Link>
                    </td>
                    <td className="px-3 py-2 font-mono">
                      <Link
                        className="hover:text-accent"
                        href={`/runs/${c.candidate_run_id}`}
                      >
                        {c.candidate_run_id}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-muted text-sm">Loading execution…</p>
          )}

          {results.isLoading ? (
            <p className="text-muted text-sm">Loading results…</p>
          ) : null}
          {results.error ? (
            <p className="text-bad text-sm">
              {(results.error as Error).message}
            </p>
          ) : null}
          {results.data ? (
            <div className="space-y-3">
              <div className="text-sm">
                <span
                  className={
                    results.data.passed ? "text-good font-medium" : "text-bad font-medium"
                  }
                >
                  {results.data.passed ? "Suite passed" : "Suite failed"}
                </span>
                <span className="text-muted">
                  {" "}
                  · {results.data.passed_cases} passed ·{" "}
                  {results.data.failed_cases} failed
                </span>
              </div>
              <table className="w-full text-sm border border-border rounded-lg overflow-hidden bg-bg">
                <thead className="text-left text-muted">
                  <tr>
                    <th className="px-3 py-2 font-medium">Result</th>
                    <th className="px-3 py-2 font-medium">Baseline</th>
                    <th className="px-3 py-2 font-medium">Candidate</th>
                    <th className="px-3 py-2 font-medium">Failures</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {results.data.cases.map((c) => (
                    <tr key={`${c.baseline_run_id}-${c.candidate_run_id}`}>
                      <td className="px-3 py-2">
                        <span
                          className={
                            c.passed
                              ? "text-good text-xs font-mono uppercase"
                              : "text-bad text-xs font-mono uppercase"
                          }
                        >
                          {c.passed ? "pass" : "fail"}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono">
                        <Link
                          className="hover:text-accent"
                          href={`/runs/${c.baseline_run_id}`}
                        >
                          {c.baseline_run_id}
                        </Link>
                      </td>
                      <td className="px-3 py-2 font-mono">
                        <Link
                          className="hover:text-accent"
                          href={`/runs/${c.candidate_run_id}`}
                        >
                          {c.candidate_run_id}
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted">
                        {c.failures.length === 0
                          ? "—"
                          : c.failures
                              .map((f) => `${f.code}: ${f.message}`)
                              .join("; ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
