"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { api } from "@/lib/api";

export default function ThreadsPage() {
  const threads = useQuery({
    queryKey: ["threads"],
    queryFn: api.listThreads,
  });

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Threads</h1>
        <span className="text-xs text-muted">cross-run conversation memory</span>
      </header>

      {threads.isLoading ? (
        <p className="text-muted">Loading…</p>
      ) : threads.data && threads.data.length > 0 ? (
        <table className="w-full text-sm border border-border rounded-lg overflow-hidden bg-surface">
          <thead className="text-left text-muted bg-bg">
            <tr>
              <th className="px-4 py-2 font-medium">Thread</th>
              <th className="px-4 py-2 font-medium">Title</th>
              <th className="px-4 py-2 font-medium">Agent</th>
              <th className="px-4 py-2 font-medium">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {threads.data.map((t) => (
              <tr key={t.id} className="hover:bg-bg/50">
                <td className="px-4 py-2 font-mono">
                  <Link className="hover:text-accent" href={`/threads/${t.id}`}>
                    {t.id}
                  </Link>
                </td>
                <td className="px-4 py-2">{t.title || "—"}</td>
                <td className="px-4 py-2 font-mono text-xs">{t.agent_id}</td>
                <td className="px-4 py-2 text-xs text-muted">
                  {new Date(t.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-muted text-sm">No threads yet.</p>
      )}
    </div>
  );
}
