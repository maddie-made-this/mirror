"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { SearchIcon } from "@/components/ui/Icons";
import { apiClient } from "@/utils/apiClient";
import { useUser } from "@/context/UserContext";
import { collapseReadings } from "@/utils/readings";
import type { UnderstandingNode } from "@/types/graph";

type SortKey = "salience" | "confidence" | "mentions";

const KIND_LABEL: Record<string, string> = {
  angle: "interest type",
  function: "what it does",
  origin: "where it came from",
  dynamics: "rhythm",
  reframing: "adaptation",
  belief: "limiting belief",
  pattern: "pattern",
  tension: "tension",
  bridge: "bridge",
};

const KIND_TONE: Record<string, string> = {
  angle: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  function: "bg-rose-500/10 text-rose-400 border-rose-500/20",
  origin: "bg-sky-500/10 text-sky-400 border-sky-500/20",
  dynamics: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  reframing: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  belief: "bg-slate-500/10 text-slate-400 border-slate-500/20",
};

/**
 * The SEMANTIC memory page — the list twin of the map (§3.2). Same motifs and
 * readings as the canvas, browsable: a quiet, low-pressure place to read what
 * the engine thinks and correct it, outside a live conversation. Its episodic
 * twin is /memory (what you actually said).
 */
export default function UnderstandingPage() {
  const { userId } = useUser();
  const [nodes, setNodes] = useState<UnderstandingNode[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("salience");
  const [onlyWithReadings, setOnlyWithReadings] = useState(false);

  const load = useCallback(async () => {
    if (!userId) return;
    try {
      const rows = await apiClient<UnderstandingNode[]>(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/graph/${userId}/understanding?limit=200`,
      );
      // Collapse duplicate readings before anything counts or sorts them —
      // reclustering can leave two live interpretations with identical text,
      // which would otherwise inflate the corroboration tie-break below.
      setNodes(rows.map((n) => ({ ...n, readings: collapseReadings(n.readings) })));
    } catch {
      setNodes([]);
    } finally {
      setIsLoaded(true);
    }
  }, [userId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const handler = () => load();
    window.addEventListener("graphUpdated", handler);
    return () => window.removeEventListener("graphUpdated", handler);
  }, [load]);

  // What the search alone leaves, before the readings toggle — the denominator
  // the "has readings" chip counts against.
  const searched = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return nodes;
    return nodes.filter(
      (n) =>
        n.name.toLowerCase().includes(q) ||
        n.readings.some((r) => r.statement.toLowerCase().includes(q)),
    );
  }, [nodes, searchQuery]);

  const visible = useMemo(() => {
    let rows = searched;
    if (onlyWithReadings) rows = rows.filter((n) => n.readings.length > 0);
    const sorted = [...rows];
    if (sort === "salience") {
      sorted.sort((a, b) => Number(b.motif) - Number(a.motif) || b.salience - a.salience);
    } else if (sort === "confidence") {
      const best = (n: UnderstandingNode) =>
        Math.max(0, ...n.readings.map((r) => r.confidence));
      // Confidence bunches hard at 1.00 — a dozen nodes can tie, and a stable
      // sort then just replays the incoming salience order, making this chip
      // look like it did nothing. Break ties on corroboration (how many
      // readings back the claim), then salience.
      sorted.sort(
        (a, b) =>
          best(b) - best(a) ||
          b.readings.length - a.readings.length ||
          b.salience - a.salience,
      );
    } else {
      sorted.sort((a, b) => b.mention_count - a.mention_count);
    }
    return sorted;
  }, [searched, sort, onlyWithReadings]);

  if (!isLoaded) return <div className="flex-1 bg-[var(--background)]" />;

  return (
    <div className="flex-1 w-full h-full overflow-y-auto bg-transparent p-4 sm:p-6 lg:p-8 transition-colors duration-500">
      <div className="max-w-4xl mx-auto flex flex-col gap-6 pb-24">

        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 border-b border-[var(--border)] pb-6">
          <div>
            <h1 className="text-3xl font-bold text-[var(--foreground)]">Understanding</h1>
            <p className="text-sm text-[var(--muted)] mt-2 max-w-xl">
              What it all seems to mean — the same terrain as the{" "}
              <Link href="/map" className="text-[var(--primary)] hover:underline">map</Link>,
              as a list. Every reading is a hypothesis you can confirm, refine, or
              reject; the receipts live in{" "}
              <Link href="/memory" className="text-[var(--primary)] hover:underline">Memories</Link>.
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
              placeholder="Search concepts and readings…"
              className="w-full pl-11 pr-4 py-3 bg-[var(--surface)] border border-[var(--border)] rounded-xl text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all shadow-sm"
            />
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <SortChip label="by salience" active={sort === "salience"} onClick={() => setSort("salience")} />
            <SortChip label="by confidence" active={sort === "confidence"} onClick={() => setSort("confidence")} />
            <SortChip label="by mentions" active={sort === "mentions"} onClick={() => setSort("mentions")} />
            <div className="flex-1" />
            {/* Counts what you're actually looking at, so the number drops when
                you turn the filter on. A fixed count never moved on click and
                read as broken. */}
            <SortChip
              label={`has readings (${visible.length})`}
              active={onlyWithReadings}
              onClick={() => setOnlyWithReadings((v) => !v)}
            />
          </div>
        </div>

        <div className="flex flex-col gap-3 min-h-[300px]">
          {visible.length === 0 ? (
            <div className="text-center p-12 text-[var(--muted)] border border-dashed border-[var(--border)] rounded-2xl bg-[var(--surface)]">
              Nothing here yet — the understanding develops as you talk.
            </div>
          ) : (
            visible.map((n) => <UnderstandingCard key={n.id} node={n} onChanged={load} />)
          )}
        </div>
      </div>
    </div>
  );
}

function SortChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
        active
          ? "bg-[var(--primary)] text-[var(--primary-fg)] shadow-sm"
          : "bg-[var(--surface)] text-[var(--muted)] border border-[var(--border)] hover:text-[var(--foreground)]"
      }`}
    >
      {label}
    </button>
  );
}

function UnderstandingCard({ node, onChanged }: { node: UnderstandingNode; onChanged: () => void }) {
  const salience = Math.max(node.salience, 0);
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-base font-semibold text-[var(--foreground)]">{node.name}</span>
        <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{node.entity_type}</span>
        {node.motif && (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-rose-500/15 text-rose-400"
                title="Repetition has made this a recurring theme.">
            motif
          </span>
        )}
        <div className="flex-1" />
        <span className="text-xs text-[var(--muted)]">×{node.mention_count}</span>
      </div>

      {salience > 0.05 && (
        <div className="flex items-center gap-2 mt-2">
          <div className="flex-1 h-1.5 bg-[var(--background)] rounded overflow-hidden">
            <div className="h-full rounded bg-gradient-to-r from-amber-500 to-rose-500"
                 style={{ width: `${Math.min(salience * 100, 100)}%` }} />
          </div>
          <span className="text-[10px] text-[var(--muted)] tabular-nums">{salience.toFixed(2)}</span>
        </div>
      )}

      {node.readings.length > 0 && (
        <div className="mt-3 space-y-2">
          {node.readings.map((r) => (
            <ReadingLine key={r.id} reading={r} onChanged={onChanged} />
          ))}
        </div>
      )}
    </div>
  );
}

function ReadingLine({
  reading, onChanged,
}: {
  reading: UnderstandingNode["readings"][number];
  onChanged: () => void;
}) {
  const [qualifying, setQualifying] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const responded = ["affirmed", "rejected", "qualified"].includes(reading.status);
  const dim = reading.confidence < 0.55;
  const tone = KIND_TONE[reading.kind] ?? "bg-amber-500/10 text-amber-400 border-amber-500/20";

  const respond = async (response: "affirmed" | "rejected" | "qualified", n = "") => {
    setBusy(true);
    try {
      await apiClient(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/interpretations/${reading.id}/respond`,
        { data: { response, note: n } },
      );
      onChanged();
    } catch { /* retryable */ }
    finally { setBusy(false); setQualifying(false); setNote(""); }
  };

  return (
    <div className={`rounded-lg border border-[var(--border)] bg-[var(--background)] p-2.5 ${dim ? "opacity-75" : ""}`}>
      <div className="flex items-start gap-2">
        <span className={`shrink-0 px-1.5 py-0.5 rounded border text-[9px] font-bold ${tone}`}>
          {KIND_LABEL[reading.kind] ?? reading.kind}
        </span>
        <span className={`text-[13px] text-[var(--foreground)] leading-snug ${dim ? "italic" : ""}`}>
          {reading.statement}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2 mt-2">
        <span className="text-[10px] text-[var(--muted)]">
          {dim ? "tentative · " : ""}conf {reading.confidence.toFixed(2)}
        </span>
        {responded && (
          <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${
            reading.status === "affirmed" ? "bg-emerald-500/15 text-emerald-500"
            : reading.status === "rejected" ? "bg-rose-500/15 text-rose-500"
            : "bg-sky-500/15 text-sky-500"
          }`}>{reading.status}</span>
        )}
        {!responded && !qualifying && (
          <div className="flex items-center gap-1.5">
            <button disabled={busy} onClick={() => respond("affirmed")} title="This is right for me"
              className="px-2.5 py-1 rounded-md border border-emerald-500/40 text-[11px] font-semibold text-emerald-500 shadow-sm hover:bg-emerald-500/15 hover:border-emerald-500/70 transition-colors disabled:opacity-40">yes</button>
            <button disabled={busy} onClick={() => setQualifying(true)} title="Close — let me refine it"
              className="px-2.5 py-1 rounded-md border border-sky-500/40 text-[11px] font-semibold text-sky-500 shadow-sm hover:bg-sky-500/15 hover:border-sky-500/70 transition-colors disabled:opacity-40">almost</button>
            <button disabled={busy} onClick={() => respond("rejected")} title="Not right for me"
              className="px-2.5 py-1 rounded-md border border-rose-500/40 text-[11px] font-semibold text-rose-500 shadow-sm hover:bg-rose-500/15 hover:border-rose-500/70 transition-colors disabled:opacity-40">no</button>
          </div>
        )}
        {qualifying && (
          <div className="flex items-center gap-1.5">
            <input
              autoFocus value={note} onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && note.trim()) respond("qualified", note.trim()); }}
              placeholder="close, but…"
              className="w-40 text-[11px] bg-[var(--background)] border border-[var(--border)] rounded-md px-2 py-1 text-[var(--foreground)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
            />
            <button disabled={busy || !note.trim()} onClick={() => respond("qualified", note.trim())}
              className="px-2.5 py-1 rounded-md border border-sky-500/50 bg-sky-500/15 text-[11px] font-semibold text-sky-500 hover:bg-sky-500/25 transition-colors disabled:opacity-40">save</button>
          </div>
        )}
      </div>
    </div>
  );
}
