"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Search, ChevronLeft, ChevronRight } from "lucide-react";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { fetcher } from "@/lib/api";

const cn = (...args: any[]) => twMerge(clsx(args));

const ROLE_COLORS: Record<string, string> = {
  BAT: "text-info",
  BOWL: "text-warning",
  AR: "text-accent",
  WK: "text-danger",
};

const ROLES = ["ALL", "BAT", "BOWL", "AR", "WK"];
const PAGE_SIZE = 50;

export default function PlayersPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("ALL");
  const [page, setPage] = useState(1);

  const searchKey =
    query.length >= 2
      ? `/players/search?q=${encodeURIComponent(query)}`
      : null;

  const listKey = searchKey
    ? null
    : `/players?${role !== "ALL" ? `role=${role}&` : ""}limit=${PAGE_SIZE}&page=${page}`;

  const { data: searchData } = useSWR(searchKey, fetcher);
  const { data: listData } = useSWR(listKey, fetcher);

  const activeData = searchKey ? searchData : listData;
  const players = activeData?.data ?? [];
  const total = activeData?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  function handleRoleChange(r: string) {
    setRole(r);
    setPage(1);
  }

  function handleQueryChange(q: string) {
    setQuery(q);
    setPage(1);
  }

  return (
    <div className="max-w-screen-xl mx-auto px-4 py-6 space-y-4">
      <div className="flex items-center gap-3">
        <span className="font-mono text-accent text-xs font-bold tracking-[0.2em]">
          PLAYERS
        </span>
        <div className="h-px w-24 bg-border" />
        {!searchKey && (
          <span className="font-mono text-muted text-xs">
            {total} players
          </span>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search
            size={12}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
          />
          <input
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="SEARCH PLAYERS..."
            className="w-full bg-surface border border-border rounded pl-8 pr-3 py-2 font-mono text-xs text-white placeholder:text-muted focus:outline-none focus:border-accent transition-colors min-h-[44px]"
          />
        </div>
        <div className="flex gap-1">
          {ROLES.map((r) => (
            <button
              key={r}
              onClick={() => handleRoleChange(r)}
              className={cn(
                "font-mono text-[10px] px-3 py-1 rounded min-h-[44px] min-w-[44px] transition-colors",
                role === r
                  ? "bg-accent text-background font-bold"
                  : "border border-border text-muted hover:text-white"
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Players Table */}
      <div className="border border-border rounded overflow-hidden">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="border-b border-border bg-surface">
              <th className="text-left px-4 py-2 text-muted tracking-wider">
                NAME
              </th>
              <th className="text-left px-4 py-2 text-muted tracking-wider">
                ROLE
              </th>
              <th className="text-left px-4 py-2 text-muted tracking-wider hidden sm:table-cell">
                TEAM
              </th>
              <th className="text-left px-4 py-2 text-muted tracking-wider hidden sm:table-cell">
                COUNTRY
              </th>
              <th className="text-right px-4 py-2 text-muted tracking-wider">
                CREDITS
              </th>
            </tr>
          </thead>
          <tbody>
            {players.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted">
                  {query.length >= 2 ? "NO RESULTS" : "LOADING..."}
                </td>
              </tr>
            ) : (
              players.map((p: any) => (
                <tr
                  key={p.id}
                  className="border-b border-border/40 hover:bg-surface cursor-pointer transition-colors"
                  onClick={() => router.push(`/players/${p.id}`)}
                >
                  <td className="px-4 py-3 text-white font-semibold hover:text-accent transition-colors">
                    {p.name}
                  </td>
                  <td
                    className={cn(
                      "px-4 py-3 font-semibold",
                      ROLE_COLORS[p.role] ?? "text-muted"
                    )}
                  >
                    {p.role}
                  </td>
                  <td className="px-4 py-3 text-muted hidden sm:table-cell">
                    {p.ipl_team ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-muted hidden sm:table-cell">
                    {p.country || "—"}
                  </td>
                  <td className="px-4 py-3 text-right text-warning font-semibold">
                    {p.dream11_price?.toFixed(1) ?? "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination — only show when not searching */}
      {!searchKey && totalPages > 1 && (
        <div className="flex items-center justify-between">
          <span className="font-mono text-xs text-muted">
            PAGE {page} OF {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="border border-border rounded p-2 text-muted hover:text-white hover:border-accent/40 disabled:opacity-30 transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
            >
              <ChevronLeft size={14} />
            </button>
            {/* Page number buttons — show up to 5 around current */}
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              const start = Math.max(1, Math.min(page - 2, totalPages - 4));
              return start + i;
            }).map((n) => (
              <button
                key={n}
                onClick={() => setPage(n)}
                className={cn(
                  "font-mono text-xs border rounded min-h-[44px] min-w-[44px] transition-colors",
                  n === page
                    ? "bg-accent text-background border-accent font-bold"
                    : "border-border text-muted hover:text-white hover:border-accent/40"
                )}
              >
                {n}
              </button>
            ))}
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="border border-border rounded p-2 text-muted hover:text-white hover:border-accent/40 disabled:opacity-30 transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
