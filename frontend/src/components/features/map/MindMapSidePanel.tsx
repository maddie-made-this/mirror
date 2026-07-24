"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/utils/apiClient";
import { useUser } from "@/context/UserContext";
import type { GraphNode, Mention, NodeReadings, Reading } from "@/types/graph";
import { VALENCE_COLORS } from "@/components/features/map/mapHelpers";
import { collapseNodeReadings } from "@/utils/readings";

interface Cooccurrence { node: GraphNode; count: number; }

const EMPTY_READINGS: NodeReadings = {
  headline: "", angle: [], origin: [], function: [], dynamics: [], reframing: [], beliefs: [], other: [],
};

export function MindMapSidePanel({
  node, onClose,
}: { node: GraphNode; onClose: () => void; }) {
  const { userId } = useUser();
  const [mentions, setMentions] = useState<Mention[]>([]);
  const [cooccurring, setCooccurring] = useState<Cooccurrence[]>([]);
  const [readings, setReadings] = useState<NodeReadings>(EMPTY_READINGS);
  const inferred = node.knowledge_source === "llm_inferred";
  const salience = Math.max(node.salience_score_mean ?? 0, 0);

  const load = useCallback(async () => {
    if (!userId) return;
    try {
      const base = `${process.env.NEXT_PUBLIC_API_URL}/api/v1/graph/${userId}/nodes/${encodeURIComponent(node.id)}`;
      const [m, c, r] = await Promise.all([
        apiClient<Mention[]>(`${base}/mentions?limit=10`),
        apiClient<Cooccurrence[]>(`${base}/cooccurring?limit=8`),
        apiClient<NodeReadings>(`${base}/readings`),
      ]);
      // Collapse duplicate readings on the way in — reclustering can leave two
      // live interpretations with identical text (see utils/readings).
      setMentions(m); setCooccurring(c);
      setReadings(r ? collapseNodeReadings(r) : EMPTY_READINGS);
    } catch {
      setMentions([]); setCooccurring([]); setReadings(EMPTY_READINGS);
    }
  }, [userId, node.id]);

  useEffect(() => {
    let cancelled = false;
    (async () => { if (!cancelled) await load(); })();
    return () => { cancelled = true; };
  }, [load]);

  // Reframing readings render as link-lines beneath the function section —
  // "born as a workaround for X; now its own thing" references BOTH (§3).
  const hasUnderstanding =
    readings.angle.length + readings.origin.length + readings.function.length +
    readings.dynamics.length + readings.reframing.length + readings.other.length > 0;

  return (
    <aside className="w-full border-l border-slate-800 bg-slate-900 p-5 overflow-y-auto h-full">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500 flex items-center gap-2 flex-wrap">
            {node.entity_type}
            <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
              inferred ? "bg-amber-500/15 text-amber-400" : "bg-slate-700/60 text-slate-400"
            }`}>
              {inferred ? "inferred" : "you said"}
            </span>
            {node.motif && (
              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-rose-500/15 text-rose-300"
                    title="Repetition has made this theme carry its own weight.">
                motif
              </span>
            )}
          </div>
          <h2 className="text-xl font-semibold text-white mt-1 break-words">{node.name}</h2>
          {readings.headline && (
            <p className="text-[13px] text-slate-300 mt-1 leading-snug">{readings.headline}</p>
          )}
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300 text-xl leading-none">×</button>
      </div>

      {/* Salience — where the weight is (§2.1). */}
      {salience > 0.05 && (
        <div className="mt-3 flex items-center gap-2">
          <span className="text-xs text-slate-500 w-12">salience</span>
          <div className="flex-1 h-2 bg-slate-800 rounded overflow-hidden">
            <div className="h-full rounded bg-gradient-to-r from-amber-500 to-rose-500"
                 style={{ width: `${Math.min(salience * 100, 100)}%` }} />
          </div>
          <span className="text-xs text-slate-400 w-10 text-right tabular-nums">{salience.toFixed(2)}</span>
        </div>
      )}

      {/* The coexisting readings (§2.3) — never collapsed into a verdict. */}
      {hasUnderstanding && (
        <div className="mt-4 space-y-3">
          {/* Tier-2: the felt character of this node's cluster — placed first, between
              the tier-1 headline and the tier-3 readings (phenomenological, not psychological). */}
          {readings.angle.length > 0 && (
            <ReadingSection title="What kind of interest this is" tone="emerald" onChanged={load}>
              {readings.angle.map((r) => (
                <ReadingCard key={r.id} reading={r} onChanged={load} />
              ))}
            </ReadingSection>
          )}
          {readings.function.length > 0 && (
            <ReadingSection title="Why it matters to you" tone="rose" onChanged={load}>
              {readings.function.map((r) => (
                <ReadingCard key={r.id} reading={r} onChanged={load}
                  reframing={readings.reframing.find(Boolean)} />
              ))}
            </ReadingSection>
          )}
          {readings.origin.length > 0 && (
            <ReadingSection title="Where it came from" tone="sky" onChanged={load}>
              {readings.origin.map((r) => (
                <ReadingCard key={r.id} reading={r} onChanged={load} />
              ))}
            </ReadingSection>
          )}
          {readings.dynamics.length > 0 && (
            <ReadingSection title="How it fits your rhythm" tone="violet" onChanged={load}>
              {readings.dynamics.map((r) => (
                <ReadingCard key={r.id} reading={r} onChanged={load} />
              ))}
            </ReadingSection>
          )}
          {readings.other.length > 0 && (
            <ReadingSection title="Patterns it's part of" tone="amber" onChanged={load}>
              {readings.other.map((r) => (
                <ReadingCard key={r.id} reading={r} onChanged={load} />
              ))}
            </ReadingSection>
          )}
        </div>
      )}
      {!hasUnderstanding && inferred && (
        <div className="mt-4 rounded-lg border border-slate-700/60 bg-slate-800/40 p-3 text-xs text-slate-400 italic">
          Inferred from the mentions below — no developed reading yet.
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
        <Stat label="Mentions" value={node.mention_count} />
        <Stat label="Spontaneous" value={node.spontaneous_mention_count} />
        <Stat label="First seen" value={`S${node.first_session}`} />
        <Stat label="Last seen" value={`S${node.last_session}`} />
      </div>

      <div className="mt-4">
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Valence</div>
        <ValenceBar label="now"  value={node.valence_score_last} />
        <ValenceBar label="mean" value={node.valence_score_mean} />
        <ValenceBar label="min"  value={node.valence_score_min}  />
        <ValenceBar label="max"  value={node.valence_score_max}  />
      </div>

      {cooccurring.length > 0 && (
        <div className="mt-6">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">
            Often mentioned alongside
          </div>
          <div className="space-y-1">
            {cooccurring.map((c) => (
              <div key={c.node.id} className="flex items-center justify-between text-sm text-slate-300">
                <span className="truncate">{c.node.name}</span>
                <span className="text-slate-600 text-xs">×{c.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-6">
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Recent mentions</div>
        <ul className="space-y-2">
          {mentions.length === 0 && <li className="text-slate-500 text-sm">None recorded.</li>}
          {mentions.map((m) => (
            <li key={m.id} className="text-sm text-slate-300 bg-slate-800/60 rounded p-2 border-l-2"
                style={{ borderLeftColor: VALENCE_COLORS[m.valence] }}>
              <div className="italic">&quot;{m.text}&quot;</div>
              <div className="text-xs text-slate-500 mt-1 flex gap-2">
                <span>S{m.session_number}</span>
                <span>v {m.valence_score.toFixed(2)}</span>
                <span>conf {m.confidence.toFixed(2)}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}

const SECTION_TONES: Record<string, string> = {
  emerald: "border-emerald-500/30 bg-emerald-500/5 text-emerald-300",  // tier-2 angle
  rose: "border-rose-500/30 bg-rose-500/5 text-rose-300",
  sky: "border-sky-500/30 bg-sky-500/5 text-sky-300",
  violet: "border-violet-500/30 bg-violet-500/5 text-violet-300",
  amber: "border-amber-500/30 bg-amber-500/5 text-amber-300",
};

function ReadingSection({
  title, tone, children,
}: { title: string; tone: string; children: React.ReactNode; onChanged: () => void }) {
  const toneCls = SECTION_TONES[tone] ?? SECTION_TONES.amber;
  const [border, bg, text] = toneCls.split(" ");
  return (
    <div className={`rounded-lg border ${border} ${bg} p-3`}>
      <div className={`text-[10px] uppercase tracking-wide ${text} mb-2`}>✦ {title}</div>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function ReadingCard({
  reading, onChanged, reframing,
}: { reading: Reading; onChanged: () => void; reframing?: Reading }) {
  // Confidence as visual certainty (§2.1): unsure readings LOOK unsure.
  const dim = reading.confidence < 0.55;
  const responded = ["affirmed", "rejected", "qualified"].includes(reading.status);

  return (
    <div className={dim ? "opacity-70" : ""}>
      <div className={`text-[13px] text-slate-200 leading-snug ${dim ? "italic" : ""}`}>
        {reading.statement}
      </div>

      {/* Origin distribution — tentative weightings, never a verdict. */}
      {reading.origin_distribution && (
        <div className="mt-1.5 space-y-1">
          <DistBar label="long-standing" value={reading.origin_distribution.innate} />
          <DistBar label="learned from experience" value={reading.origin_distribution.learned_episodic} />
          <DistBar label="developed over time" value={reading.origin_distribution.reframing_consolidated} />
        </div>
      )}
      {reading.origin_episode && (
        <div className="text-[11px] text-slate-400 italic mt-1">
          you mentioned — &quot;{reading.origin_episode}&quot;
        </div>
      )}

      {/* The reframing link under a function reading: references BOTH. */}
      {reframing?.belief_statement && (
        <div className="text-[11px] text-slate-400 mt-1">
          may have started as a response to <span className="italic">&quot;{reframing.belief_statement}&quot;</span> — now stands on its own.
        </div>
      )}

      {reading.evidence_quotes.length > 0 && (
        <div className="mt-1.5 space-y-0.5">
          {reading.evidence_quotes.map((q, i) => (
            <div key={i} className="text-[11px] text-slate-500 italic truncate">— &quot;{q}&quot;</div>
          ))}
        </div>
      )}

      {reading.what_would_change_this && (
        <div className="text-[10px] text-slate-500 mt-1">
          what would change this: {reading.what_would_change_this}
        </div>
      )}

      <div className="flex items-center justify-between gap-2 mt-2">
        <span className="text-[10px] text-slate-500">
          {dim ? "tentative · " : ""}conf {reading.confidence.toFixed(2)}
        </span>
        {responded ? (
          <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${
            reading.status === "affirmed" ? "bg-emerald-500/15 text-emerald-300"
            : reading.status === "rejected" ? "bg-rose-500/15 text-rose-300"
            : "bg-sky-500/15 text-sky-300"
          }`}>{reading.status}</span>
        ) : (
          <RespondControls readingId={reading.id} onChanged={onChanged} />
        )}
      </div>
    </div>
  );
}

function DistBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-slate-500 w-36 truncate">{label}</span>
      <div className="flex-1 h-1.5 bg-slate-800 rounded overflow-hidden">
        <div className="h-full bg-sky-500/70 rounded" style={{ width: `${Math.min(value * 100, 100)}%` }} />
      </div>
    </div>
  );
}

function RespondControls({ readingId, onChanged }: { readingId: string; onChanged: () => void }) {
  const [qualifying, setQualifying] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const respond = async (response: "affirmed" | "rejected" | "qualified", n = "") => {
    setBusy(true);
    try {
      await apiClient(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/interpretations/${readingId}/respond`,
        { data: { response, note: n } },
      );
      onChanged();
    } catch { /* leave controls visible to retry */ }
    finally { setBusy(false); setQualifying(false); setNote(""); }
  };

  if (qualifying) {
    return (
      <div className="flex items-center gap-1">
        <input
          autoFocus value={note} onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && note.trim()) respond("qualified", note.trim()); }}
          placeholder="close, but…"
          className="w-36 text-[11px] bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-slate-200 placeholder:text-slate-600"
        />
        <button disabled={busy || !note.trim()} onClick={() => respond("qualified", note.trim())}
          className="px-2.5 py-1 rounded-md border border-sky-500/50 bg-sky-500/15 text-[11px] font-semibold text-sky-200 hover:bg-sky-500/25 transition-colors disabled:opacity-40">save</button>
      </div>
    );
  }
  const btn = "px-2.5 py-1 rounded-md border text-[11px] font-semibold shadow-sm transition-colors disabled:opacity-40";
  return (
    <div className="flex items-center gap-1.5">
      <button disabled={busy} onClick={() => respond("affirmed")} title="This is right for me"
        className={`${btn} border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/15 hover:border-emerald-500/70`}>yes</button>
      <button disabled={busy} onClick={() => setQualifying(true)} title="Close — let me refine it (the most useful answer)"
        className={`${btn} border-sky-500/40 text-sky-300 hover:bg-sky-500/15 hover:border-sky-500/70`}>almost</button>
      <button disabled={busy} onClick={() => respond("rejected")} title="Not right for me"
        className={`${btn} border-rose-500/40 text-rose-300 hover:bg-rose-500/15 hover:border-rose-500/70`}>no</button>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-slate-800/50 rounded p-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-base font-semibold text-white">{value}</div>
    </div>
  );
}

function ValenceBar({ label, value }: { label: string; value: number }) {
  const pct = Math.min(100, Math.abs(value) * 100);
  const pos = value >= 0;
  return (
    <div className="flex items-center gap-2 mb-1.5">
      <span className="text-xs text-slate-500 w-10">{label}</span>
      <div className="flex-1 h-2 bg-slate-800 rounded relative overflow-hidden">
        <div
          className={`absolute top-0 h-full ${pos ? "left-1/2 bg-emerald-500" : "right-1/2 bg-rose-500"}`}
          style={{ width: `${pct / 2}%` }}
        />
        <div className="absolute top-0 bottom-0 left-1/2 w-px bg-slate-700" />
      </div>
      <span className="text-xs text-slate-400 w-12 text-right tabular-nums">{value.toFixed(2)}</span>
    </div>
  );
}
