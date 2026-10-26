"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ThreadDetailPage({ params }: PageProps) {
  const { id } = use(params);

  const thread = useQuery({
    queryKey: ["thread", id],
    queryFn: () => api.getThread(id),
  });
  const messages = useQuery({
    queryKey: ["thread", id, "messages"],
    queryFn: () => api.listThreadMessages(id, { limit: 100 }),
  });
  const runs = useQuery({
    queryKey: ["thread", id, "runs"],
    queryFn: () => api.listThreadRuns(id),
  });

  if (thread.isLoading) return <p className="text-muted">Loading…</p>;
  if (thread.error || !thread.data) {
    return (
      <p className="text-bad">Failed to load thread: {String(thread.error)}</p>
    );
  }

  const t = thread.data;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="text-xs text-muted font-mono">{t.id}</div>
          <h1 className="text-xl font-semibold">
            Thread{t.title ? ` · ${t.title}` : ""}
          </h1>
          <div className="text-xs text-muted">
            agent <span className="font-mono">{t.agent_id}</span>
            {t.user_id ? (
              <>
                {" "}
                · user <span className="font-mono">{t.user_id}</span>
              </>
            ) : null}{" "}
            · created {new Date(t.created_at).toLocaleString()}
          </div>
        </div>
        <Link
          href="/threads"
          className="rounded border border-border px-3 py-1.5 text-sm hover:bg-surface"
        >
          Back
        </Link>
      </header>

      <section className="rounded-lg border border-border bg-surface p-4 space-y-3">
        <h2 className="font-medium">Runs in thread</h2>
        {runs.isLoading ? (
          <p className="text-muted text-sm">Loading…</p>
        ) : runs.data && runs.data.length > 0 ? (
          <ul className="space-y-2 text-sm">
            {runs.data.map((r) => (
              <li
                key={r.id}
                className="flex items-center gap-3 font-mono text-xs"
              >
                <Link className="hover:text-accent" href={`/runs/${r.id}`}>
                  {r.id}
                </Link>
                <StatusBadge status={r.status} />
                <span className="text-muted">
                  {new Date(r.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted text-sm">No runs yet.</p>
        )}
      </section>

      <section className="rounded-lg border border-border bg-surface p-4 space-y-3">
        <h2 className="font-medium">Conversation</h2>
        {messages.isLoading ? (
          <p className="text-muted text-sm">Loading…</p>
        ) : messages.data && messages.data.items.length > 0 ? (
          <ul className="space-y-2">
            {messages.data.items.map((m) => (
              <li
                key={m.id}
                className="rounded border border-border p-3 text-sm space-y-1"
              >
                <div className="flex items-center gap-2 text-xs text-muted">
                  <span className="font-medium text-foreground">{m.role}</span>
                  <Link
                    href={`/runs/${m.run_id}`}
                    className="font-mono hover:text-accent"
                  >
                    {m.run_id}
                  </Link>
                  <span className="font-mono">#{m.index}</span>
                </div>
                <div className="whitespace-pre-wrap">{m.content}</div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted text-sm">No messages yet.</p>
        )}
      </section>
    </div>
  );
}
