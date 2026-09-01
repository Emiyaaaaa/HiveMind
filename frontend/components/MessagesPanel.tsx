"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type { Message } from "@/lib/types";

interface MessagesPanelProps {
  runId: string;
  messages: Message[];
  messagesTruncated: boolean;
}

function mergeMessages(...groups: Message[][]): Message[] {
  const byIndex = new Map<number, Message>();
  for (const group of groups) {
    for (const message of group) {
      byIndex.set(message.index, message);
    }
  }
  return [...byIndex.values()].sort((a, b) => a.index - b.index);
}

export function MessagesPanel({
  runId,
  messages,
  messagesTruncated,
}: MessagesPanelProps) {
  const [older, setOlder] = useState<Message[]>([]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(messagesTruncated);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setOlder([]);
    setNextCursor(null);
    setHasMore(messagesTruncated);
  }, [runId, messagesTruncated]);

  const displayed = useMemo(
    () => mergeMessages(older, messages),
    [older, messages],
  );

  async function loadOlder() {
    if (loading || !hasMore) return;
    const cursor = nextCursor ?? displayed[0]?.index;
    if (cursor == null) return;

    setLoading(true);
    try {
      const page = await api.listRunMessages(runId, { cursor, limit: 50 });
      setOlder((prev) => mergeMessages(page.items, prev));
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-medium">Messages</h2>
        {displayed.length > 0 ? (
          <span className="text-xs text-muted">
            {displayed.length} shown
            {hasMore ? " · older available" : ""}
          </span>
        ) : null}
      </div>

      {hasMore ? (
        <button
          type="button"
          className="rounded border border-border px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-50"
          onClick={() => void loadOlder()}
          disabled={loading}
        >
          {loading ? "Loading…" : "Load older messages"}
        </button>
      ) : null}

      <ol className="max-h-[32rem] space-y-2 overflow-y-auto pr-1">
        {displayed.map((message) => (
          <li
            key={message.id}
            className="rounded border border-border bg-surface p-3 text-sm"
          >
            <div className="mb-1 text-xs uppercase tracking-wide text-muted">
              {message.role}
              {message.name ? ` · ${message.name}` : ""}
              <span className="ml-2 font-mono normal-case">#{message.index}</span>
            </div>
            <div className="whitespace-pre-wrap">{message.content}</div>
          </li>
        ))}
      </ol>

      {displayed.length === 0 ? (
        <p className="text-sm text-muted">No messages yet.</p>
      ) : null}
    </section>
  );
}
