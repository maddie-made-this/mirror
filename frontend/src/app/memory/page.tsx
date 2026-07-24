"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { SearchIcon } from "@/components/ui/Icons";
import { apiClient } from "@/utils/apiClient";
import { useUser } from "@/context/UserContext";
import type { UserMention } from "@/types/graph";

const PAGE_SIZE = 50;

/**
 * The EPISODIC memory page — what you actually said, verbatim (the receipts).
 * Server-truth (Neo4j mentions), replacing the old localStorage vector view.
 * Every abstraction on the map traces back to a row here; its semantic twin
 * is /understanding (what it means).
 */
export default function MemoriesPage() {
  const { userId } = useUser();
  const [mentions, setMentions] = useState<UserMention[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  // The full type list, fetched once and unfiltered, so the chips never
  // collapse to whatever survived the current filter.
  const [allTypes, setAllTypes] = useState<string[]>([]);
  const offsetRef = useRef(0);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(searchQuery.trim()), 300);
    return () => clearTimeout(t);
  }, [searchQuery]);

  const load = useCallback(
    async (reset: boolean) => {
      if (!userId) return;
      const offset = reset ? 0 : offsetRef.current;
      try {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String(offset),
        });
        for (const t of selectedTypes) params.append("entity_type", t);
        if (debouncedQ) params.set("q", debouncedQ);
        const rows = await apiClient<UserMention[]>(
          `${process.env.NEXT_PUBLIC_API_URL}/api/v1/graph/${userId}/mentions?${params}`,
        );
        setMentions((prev) => (reset ? rows : [...prev, ...rows]));
        offsetRef.current = offset + rows.length;
        setHasMore(rows.length === PAGE_SIZE);
      } catch {
        if (reset) setMentions([]);
        setHasMore(false);
      } finally {
        setIsLoaded(true);
      }
    },
    [userId, selectedTypes, debouncedQ],
  );

  useEffect(() => { load(true); }, [load]);
  useEffect(() => {
    const handler = () => load(true);
    window.addEventListener("graphUpdated", handler);
    return () => window.removeEventListener("graphUpdated", handler);
  }, [load]);

  // The chips come from the whole record, not the visible rows — otherwise
  // picking one filter hides every other option and there's no way to add a
  // second. Fetched once per user; the set only grows as new types appear.
  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    apiClient<string[]>(
      `${process.env.NEXT_PUBLIC_API_URL}/api/v1/graph/${userId}/mentions/entity-types`,
    )
      .then((types) => { if (!cancelled) setAllTypes(types ?? []); })
      .catch(() => { if (!cancelled) setAllTypes([]); });
    return () => { cancelled = true; };
  }, [userId]);

  const toggleType = useCallback((t: string) => {
    setSelectedTypes((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t],
    );
  }, []);

  // Keep the same array when it's already empty — a fresh [] would change
  // `load`'s identity and refetch on every click of an already-active "all".
  const clearTypes = useCallback(() => {
    setSelectedTypes((prev) => (prev.length === 0 ? prev : []));
  }, []);

  // Group by session for a readable timeline.
  const bySession = useMemo(() => {
    const groups = new Map<number, UserMention[]>();
    for (const m of mentions) {
      const list = groups.get(m.session_number) ?? [];
      list.push(m);
      groups.set(m.session_number, list);
    }
    return Array.from(groups.entries()).sort((a, b) => b[0] - a[0]);
  }, [mentions]);

  if (!isLoaded) return <div className="flex-1 bg-[var(--background)]" />;

  return (
    <div className="flex-1 w-full h-full overflow-y-auto bg-transparent p-4 sm:p-6 lg:p-8 transition-colors duration-500">
      <div className="max-w-4xl mx-auto flex flex-col gap-6 pb-24">

        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 border-b border-[var(--border)] pb-6">
          <div>
            <h1 className="text-3xl font-bold text-[var(--foreground)]">Memories</h1>
            <p className="text-sm text-[var(--muted)] mt-2 max-w-xl">
              What you&apos;ve actually said, word for word — the record everything
              else is built on. For what it means, see{" "}
              <Link href="/understanding" className="text-[var(--primary)] hover:underline">
                Understanding
              </Link>.
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              <SearchIcon className="w-5 h-5 text-[var(--muted)]" />
            </div>
            <input
              type="text" value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search what you've said…"
              className="w-full pl-11 pr-4 py-3 bg-[var(--surface)] border border-[var(--border)] rounded-xl text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all shadow-sm"
            />
          </div>

          {allTypes.length > 0 && (
            <div className="flex flex-col gap-1 pb-2 -mb-2">
              <div className="flex overflow-x-auto hide-scrollbar gap-2">
                <FilterChip
                  label="all"
                  active={selectedTypes.length === 0}
                  onClick={clearTypes}
                />
                {allTypes.map((t) => (
                  <FilterChip
                    key={t}
                    label={t}
                    active={selectedTypes.includes(t)}
                    onClick={() => toggleType(t)}
                  />
                ))}
              </div>
              {selectedTypes.length > 1 && (
                <p className="text-[11px] text-[var(--muted)]">
                  Showing what you said about{" "}
                  {selectedTypes.length === 2 ? "both" : "all of those"} at once.
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-6 min-h-[300px]">
          {bySession.length === 0 ? (
            <div className="text-center p-12 text-[var(--muted)] border border-dashed border-[var(--border)] rounded-2xl bg-[var(--surface)]">
              Nothing recorded yet{debouncedQ || selectedTypes.length
                ? (selectedTypes.length > 1
                    ? " with all of those themes at once"
                    : " for this filter")
                : " — it fills in as you chat"}.
            </div>
          ) : (
            bySession.map(([session, rows]) => (
              <div key={session}>
                <div className="text-xs uppercase tracking-wide text-[var(--muted)] mb-2">
                  Session {session}
                </div>
                <div className="flex flex-col gap-2">
                  {rows.map((m) => <MentionRow key={m.id} mention={m} />)}
                </div>
              </div>
            ))
          )}

          {hasMore && (
            <button
              onClick={() => load(false)}
              className="self-center text-sm font-semibold text-[var(--muted)] hover:text-[var(--foreground)] border border-[var(--border)] bg-[var(--surface)] px-5 py-2 rounded-lg transition-colors"
            >
              Load more
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-3.5 py-1.5 rounded-lg text-sm font-semibold whitespace-nowrap transition-all ${
        active
          ? "bg-[var(--primary)] text-[var(--primary-fg)] shadow-sm"
          : "bg-[var(--surface)] text-[var(--muted)] border border-[var(--border)] hover:text-[var(--foreground)]"
      }`}
    >
      {label}
    </button>
  );
}

function MentionRow({ mention }: { mention: UserMention }) {
  const v = mention.valence_score;
  const a = Math.max(mention.salience_score, 0);
  // Valence shows as a small labeled dot only when it's actually leaning — a thin
  // colored left-border read as decoration, not meaning. The salience dot appears
  // only when genuinely notable and its opacity scales with the value (no constant
  // marker on every row). Uniform px-4 padding gives the date + text a left gutter.
  const valence = v > 0.2 ? "positive" : v < -0.2 ? "negative" : null;
  const when = mention.created_at
    ? new Date(mention.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })
    : "";

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl px-4 py-3.5">
      <div className="text-[15px] text-[var(--foreground)] italic leading-relaxed">
        &quot;{mention.text}&quot;
      </div>
      <div className="flex items-center flex-wrap gap-x-2.5 gap-y-1.5 mt-3 text-xs text-[var(--muted)]">
        {when && <span className="tabular-nums">{when}</span>}
        {valence && (
          <span className="inline-flex items-center gap-1" title={`${valence} feeling`}>
            <span className={`w-1.5 h-1.5 rounded-full ${valence === "positive" ? "bg-emerald-500" : "bg-rose-500"}`} />
          </span>
        )}
        {a >= 0.6 && (
          <span title={`high salience (${a.toFixed(2)})`} className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500"
                  style={{ opacity: 0.45 + 0.55 * Math.min(a, 1) }} />
          </span>
        )}
        {mention.nodes.filter((n) => n.entity_type !== "self").map((n) => (
          <span key={n.id} className="px-2 py-0.5 rounded-md bg-[var(--background)] border border-[var(--border)]">
            {n.name}
          </span>
        ))}
      </div>
    </div>
  );
}
