"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import {
  liveRunIdsFromRuns,
  useRunsListLiveSync,
} from "@/lib/useRunLiveSync";
import { formatCostUsd, hasUsageMetrics } from "@/lib/usage";

export default function RunsPage() {
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.listRuns,
  });

  const liveRunIds = useMemo(
    () => liveRunIdsFromRuns(runs.data),
    [runs.data],
  );

  useRunsListLiveSync(liveRunIds);

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Runs</h1>
        <span className="text-xs text-muted">
          {liveRunIds.length > 0
            ? `live via SSE (${liveRunIds.length} active)`
            : "updates on refresh"}
        </span>
      </header>

      {runs.isLoading ? (
        <p className="text-muted">Loading…</p>
      ) : runs.data && runs.data.length > 0 ? (
        <table className="w-full text-sm border border-border rounded-lg overflow-hidden bg-surface">
          <thead className="text-left text-muted bg-bg">
            <tr>
              <th className="px-4 py-2 font-medium">Run</th>
              <th className="px-4 py-2 font-medium">Adapter</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Usage</th>
              <th className="px-4 py-2 font-medium">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {runs.data.map((r) => (
              <tr key={r.id} className="hover:bg-bg/50">
                <td className="px-4 py-2 font-mono">
                  <Link className="hover:text-accent" href={`/runs/${r.id}`}>
                    {r.id}
                  </Link>
                </td>
                <td className="px-4 py-2 font-mono text-xs">{r.adapter}</td>
                <td className="px-4 py-2">
                  <StatusBadge status={r.status} />
                </td>
                <td className="px-4 py-2 text-xs font-mono text-muted">
                  {hasUsageMetrics(r.usage) ? (
                    <span>
                      {r.usage.tokens_in + r.usage.tokens_out} tok ·{" "}
                      <span className="text-accent">
                        {formatCostUsd(r.usage.cost_usd)}
                      </span>
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-4 py-2 text-xs text-muted">
                  {new Date(r.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-muted">No runs yet.</p>
      )}
    </div>
  );
}
