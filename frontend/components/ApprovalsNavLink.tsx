"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { waitingHumanRuns } from "@/lib/approval";
import { api } from "@/lib/api";

export function ApprovalsNavLink() {
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.listRuns,
    staleTime: 15_000,
  });
  const pending = waitingHumanRuns(runs.data).length;

  return (
    <Link href="/approvals" className="hover:text-text inline-flex items-center gap-1.5">
      Approvals
      {pending > 0 ? (
        <span className="rounded bg-warn/20 text-warn px-1.5 py-0.5 text-[10px] font-mono leading-none">
          {pending}
        </span>
      ) : null}
    </Link>
  );
}
