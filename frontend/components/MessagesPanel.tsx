"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type { Message, Step } from "@/lib/types";

interface MessagesPanelProps {
  runId: string;
  messages: Message[];
  messagesTruncated: boolean;
  steps?: Step[];
}

function isPromptEcho(message: Message): boolean {
  return message.extra?.kind === "prompt_echo";
}

function isReasoning(message: Message): boolean {
  const kind = message.extra?.kind;
  return kind === "reasoning" || kind === "streaming_reasoning";
}

function isStreaming(message: Message): boolean {
  const kind = message.extra?.kind;
  return kind === "streaming" || kind === "streaming_reasoning";
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

function CollapsibleBlock({
  title,
  meta,
  content,
  expanded,
  onToggle,
  dashed = false,
}: {
  title: string;
  meta?: string | null;
  content: string;
  expanded: boolean;
  onToggle: () => void;
  dashed?: boolean;
}) {
  return (
    <li
      className={
        dashed
          ? "rounded border border-dashed border-border bg-surface/60 p-2 text-sm"
          : "rounded border border-border bg-surface/80 p-2 text-sm"
      }
    >
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left text-xs text-muted hover:text-foreground"
        onClick={onToggle}
      >
        <span>
          {title}
          {meta ? ` · ${meta}` : ""}
        </span>
        <span>{expanded ? "Hide" : "Show"}</span>
      </button>
      {expanded ? (
        <div className="mt-2 whitespace-pre-wrap text-foreground">{content}</div>
      ) : null}
    </li>
  );
}

export function MessagesPanel({
  runId,
  messages,
  messagesTruncated,
  steps = [],
}: MessagesPanelProps) {
  const stepById = useMemo(() => {
    const map = new Map<string, Step>();
    for (const step of steps) {
      map.set(step.id, step);
    }
    return map;
  }, [steps]);
  const [older, setOlder] = useState<Message[]>([]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(messagesTruncated);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(),
  );

  useEffect(() => {
    setOlder([]);
    setNextCursor(null);
    setHasMore(messagesTruncated);
    setExpanded(new Set());
  }, [runId, messagesTruncated]);

  const displayed = useMemo(
    () => mergeMessages(older, messages),
    [older, messages],
  );

  const promptEchoCount = useMemo(
    () => displayed.filter(isPromptEcho).length,
    [displayed],
  );
  const reasoningCount = useMemo(
    () => displayed.filter(isReasoning).length,
    [displayed],
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

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-medium">Messages</h2>
        {displayed.length > 0 ? (
          <span className="text-xs text-muted">
            {displayed.length} shown
            {promptEchoCount > 0
              ? ` · ${promptEchoCount} prompt echo${promptEchoCount === 1 ? "" : "es"} collapsed`
              : ""}
            {reasoningCount > 0
              ? ` · ${reasoningCount} reasoning block${reasoningCount === 1 ? "" : "s"}`
              : ""}
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
        {displayed.map((message) => {
          const key = message.id;
          if (isPromptEcho(message)) {
            const node =
              typeof message.extra.node === "string" ? message.extra.node : null;
            return (
              <CollapsibleBlock
                key={key}
                title={`${message.role} prompt echo`}
                meta={
                  node
                    ? `${node} #${message.index}`
                    : `#${message.index}`
                }
                content={message.content}
                expanded={expanded.has(key)}
                onToggle={() => toggle(key)}
                dashed
              />
            );
          }
          if (isReasoning(message)) {
            return (
              <CollapsibleBlock
                key={key}
                title={
                  isStreaming(message)
                    ? "assistant reasoning (streaming…)"
                    : "assistant reasoning"
                }
                meta={`#${message.index}`}
                content={message.content}
                expanded={expanded.has(key) || isStreaming(message)}
                onToggle={() => toggle(key)}
              />
            );
          }
          return (
            <li
              key={key}
              className="rounded border border-border bg-surface p-3 text-sm"
            >
              <div className="mb-1 text-xs uppercase tracking-wide text-muted">
                {message.role}
                {isStreaming(message) ? " · streaming…" : ""}
                {message.name ? ` · ${message.name}` : ""}
                {message.step_id ? (
                  <span className="ml-2 font-mono normal-case">
                    step{" "}
                    {(() => {
                      const step = stepById.get(message.step_id!);
                      return step
                        ? `#${step.index} ${step.node}`
                        : message.step_id!.slice(0, 8);
                    })()}
                  </span>
                ) : null}
                <span className="ml-2 font-mono normal-case">
                  #{message.index}
                </span>
              </div>
              <div className="whitespace-pre-wrap">{message.content}</div>
            </li>
          );
        })}
      </ol>

      {displayed.length === 0 ? (
        <p className="text-sm text-muted">No messages yet.</p>
      ) : null}
    </section>
  );
}
