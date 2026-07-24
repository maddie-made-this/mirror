"use client";

import { useState } from "react";
import { useMessageDebug } from "@/hooks/useMessageDebug";
import { VALENCE_COLORS } from "@/components/features/map/mapHelpers";
import type { Proposition, GraphNode, PromptContext, PieceBrief } from "@/types/graph";

export function DebugPanel() {
  const { last, history } = useMessageDebug();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"props" | "nodes" | "edges" | "context" | "brief" | "raw">("props");

  if (!last && !open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-50 px-3 py-1.5 rounded-full bg-slate-800 text-slate-300 text-xs border border-slate-700 hover:bg-slate-700"
      >
        debug
      </button>
    );
  }

  if (!open) {
    const propsCount = last?.propositions.length ?? 0;
    const skipped = last?.propositions_skipped?.length ?? 0;
    const nodesCount = (last?.nodes_created.length ?? 0) + (last?.nodes_updated.length ?? 0);
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-50 px-3 py-1.5 rounded-full bg-slate-800 text-slate-300 text-xs border border-slate-700 hover:bg-slate-700 font-mono"
      >
        {propsCount}p · {nodesCount}n {skipped > 0 && `· ${skipped} skipped`}
      </button>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 w-[min(420px,calc(100vw-2rem))] max-h-[70vh] bg-slate-900 border border-slate-700 rounded-lg shadow-2xl flex flex-col overflow-hidden font-mono text-xs">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800 bg-slate-950">
        <div className="text-slate-400">
          {last ? `msg ${last.message_id.slice(0, 8)}` : "no messages yet"}
        </div>
        <div className="flex gap-1">
          {(["props", "nodes", "edges", "context", "brief", "raw"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-2 py-0.5 rounded ${
                tab === t ? "bg-slate-700 text-white" : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {t}
            </button>
          ))}
          <button
            onClick={() => setOpen(false)}
            className="px-2 py-0.5 text-slate-500 hover:text-slate-300"
          >
            ×
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="overflow-y-auto p-3 flex-1">
        {!last && <div className="text-slate-500">Send a message to see extraction output.</div>}

        {last && tab === "props" && (
          <div className="space-y-2">
            {last.propositions.length === 0 && (
              <div className="text-amber-400">⚠ No propositions extracted.</div>
            )}
            {last.propositions.map((p) => (
              <PropositionCard key={p.id} prop={p} />
            ))}
            {(last.propositions_skipped?.length ?? 0) > 0 && (
              <>
                <div className="text-slate-500 mt-3 mb-1 uppercase text-[10px] tracking-wide">
                  Skipped (low confidence)
                </div>
                {last.propositions_skipped!.map((p) => (
                  <PropositionCard key={p.id} prop={p} dim />
                ))}
              </>
            )}
          </div>
        )}

        {last && tab === "nodes" && (
          <div className="space-y-3">
            {last.nodes_created.length > 0 && (
              <NodeSection label="created" nodes={last.nodes_created} accent="green" />
            )}
            {last.nodes_updated.length > 0 && (
              <NodeSection label="updated" nodes={last.nodes_updated} accent="blue" />
            )}
            {last.nodes_created.length + last.nodes_updated.length === 0 && (
              <div className="text-slate-500">No node mutations.</div>
            )}
          </div>
        )}

        {last && tab === "edges" && (
          <div className="space-y-2">
            <Section label={`created (${last.edges_created.length})`}>
              {last.edges_created.map((e) => (
                <div key={e.id} className="text-slate-300">
                  <span className="text-slate-500">{e.source_id}</span>
                  <span className="mx-1 text-amber-400">─ {e.relation_type} →</span>
                  <span className="text-slate-500">{e.target_id}</span>
                </div>
              ))}
            </Section>
            {last.edges_updated.length > 0 && (
              <Section label={`updated (${last.edges_updated.length})`}>
                {last.edges_updated.map((e) => (
                  <div key={e.id} className="text-slate-300">
                    <span className="text-slate-500">{e.source_id}</span>
                    <span className="mx-1 text-blue-400">─ {e.relation_type} →</span>
                    <span className="text-slate-500">{e.target_id}</span>
                    <span className="ml-2 text-slate-600">w={e.weight.toFixed(1)}</span>
                  </div>
                ))}
              </Section>
            )}
          </div>
        )}

        {last && tab === "context" && (
          <ContextInspector ctx={last.prompt_context} />
        )}

        {last && tab === "brief" && (
          <BriefInspector brief={last.piece_brief} />
        )}

        {last && tab === "raw" && (
          <pre className="text-slate-400 whitespace-pre-wrap text-[11px] leading-snug">
            {JSON.stringify(last, null, 2)}
          </pre>
        )}
      </div>

      {/* Footer — session info. */}
      <div className="border-t border-slate-800 px-3 py-2 bg-slate-950 flex items-center justify-end gap-3 text-slate-400">
        {history.length > 1 && (
          <span className="text-slate-600">{history.length} msgs</span>
        )}
      </div>
    </div>
  );
}

function PropositionCard({ prop, dim = false }: { prop: Proposition; dim?: boolean }) {
  return (
    <div
      className={`border border-slate-800 rounded p-2 ${dim ? "opacity-50" : ""}`}
      style={{ borderLeftColor: VALENCE_COLORS[prop.valence], borderLeftWidth: 3 }}
    >
      <div className="text-slate-200 leading-snug">
        <span className="text-slate-100">{prop.subject}</span>
        <span className="mx-1 text-amber-400">{prop.predicate}</span>
        <span className="text-slate-100">{prop.object}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-slate-500">
        <span>conf {prop.confidence.toFixed(2)}</span>
        <span>v {prop.valence_score.toFixed(2)}</span>
        <span>a {prop.salience_score.toFixed(2)}</span>
        <span>{prop.subject_entity_type} → {prop.object_entity_type}</span>
        <span>{prop.causal_class}</span>
      </div>
      <div className="mt-1 text-slate-600 italic truncate" title={prop.source_span}>
        &quot;{prop.source_span}&quot;
      </div>
    </div>
  );
}

function NodeSection({ label, nodes, accent }: { label: string; nodes: GraphNode[]; accent: "green" | "blue" }) {
  const dot = accent === "green" ? "bg-emerald-500" : "bg-blue-500";
  return (
    <Section label={`${label} (${nodes.length})`}>
      {nodes.map((n) => (
        <div key={n.id} className="flex items-center gap-2 text-slate-300">
          <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
          <span className="text-slate-500 text-[10px]">{n.entity_type}</span>
          <span>{n.name}</span>
          <span className="ml-auto text-slate-600">
            n={n.mention_count} v={n.valence_score_last.toFixed(2)}
          </span>
        </div>
      ))}
    </Section>
  );
}

function ContextInspector({ ctx }: { ctx?: PromptContext | null }) {
  if (!ctx) {
    return (
      <div className="text-slate-500">
        No prompt context. Set EXPOSE_PROMPT_DEBUG=true in backend/.env and restart.
      </div>
    );
  }

  const LAYER_ORDER = [
    "core_identity", "safety_rules", "capability_rules",
    "format_rules", "graph_context", "user_preferences",
  ];

  return (
    <div className="space-y-3">
      <div className="text-slate-500 text-[10px]">
        model: {ctx.model} · temp: {ctx.temperature}
      </div>

      <div>
        <div className="text-slate-500 uppercase text-[10px] tracking-wide mb-1">
          System layers
        </div>
        <div className="space-y-2">
          {LAYER_ORDER.map((key) => {
            const content = ctx.system_layers[key];
            const disabled = content == null;
            return (
              <details key={key} className="border border-slate-800 rounded">
                <summary className={`px-2 py-1 cursor-pointer select-none ${
                  disabled ? "text-slate-600" : "text-slate-300"
                }`}>
                  {key} {disabled && "(disabled)"}
                  {!disabled && (
                    <span className="text-slate-600 ml-2">
                      {content!.length} chars
                    </span>
                  )}
                </summary>
                {!disabled && (
                  <pre className="px-2 py-1 text-[10px] text-slate-400 whitespace-pre-wrap border-t border-slate-800">
                    {content}
                  </pre>
                )}
              </details>
            );
          })}
        </div>
      </div>

      {ctx.history_messages.length > 0 && (
        <div>
          <div className="text-slate-500 uppercase text-[10px] tracking-wide mb-1">
            History ({ctx.history_messages.length})
          </div>
          <div className="space-y-1">
            {ctx.history_messages.map((m, i) => (
              <div key={i} className="border border-slate-800 rounded px-2 py-1">
                <span className={`text-[10px] uppercase ${
                  m.role === "user" ? "text-blue-400" : "text-emerald-400"
                }`}>{m.role}</span>
                <div className="text-slate-400 text-[11px] mt-0.5 whitespace-pre-wrap">
                  {m.content}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="text-slate-500 uppercase text-[10px] tracking-wide mb-1">
          User message
        </div>
        <div className="border border-blue-500/30 rounded px-2 py-1 text-slate-300 text-[11px] whitespace-pre-wrap">
          {ctx.user_message}
        </div>
      </div>
    </div>
  );
}

function BriefInspector({ brief }: { brief?: PieceBrief | null }) {
  if (!brief) {
    return (
      <div className="text-slate-500">
        No piece brief. Requires the director/renderer split (USE_DIRECTOR_SPLIT=1) and
        EXPOSE_PROMPT_DEBUG=true, on a piece (non-analytic) turn.
      </div>
    );
  }

  const dnr = brief.do_not_repeat?.filter(Boolean) ?? [];
  const prereq = brief.prerequisites_to_establish?.filter(Boolean) ?? [];
  const avoid = brief.hard_avoid?.filter(Boolean) ?? [];
  const reg = brief.delivery ?? ({} as PieceBrief["delivery"]);
  const ss = brief.piece_frame ?? ({} as PieceBrief["piece_frame"]);

  return (
    <div className="space-y-3">
      <Section label="Decision">
        <div className="text-slate-200">
          action: <span className="text-amber-300">{brief.action}</span>
        </div>
        {brief.question && <div className="text-slate-300 italic">“{brief.question}”</div>}
      </Section>

      {/* Advancement — the anti-loop signal; if empty/ignored, the repetition bug is visible here */}
      <div className="border border-amber-500/40 rounded p-2 bg-amber-500/5">
        <div className="text-amber-400/80 mb-1 uppercase text-[10px] tracking-wide">
          Advancement (anti-loop)
        </div>
        <div className="text-slate-300 whitespace-pre-wrap">
          {brief.advance_directive || <span className="text-slate-600">—</span>}
        </div>
        {dnr.length > 0 && (
          <div className="mt-1.5">
            <div className="text-slate-500 text-[10px]">do not repeat:</div>
            <ul className="list-disc list-inside text-slate-400">
              {dnr.map((x, i) => <li key={i}>{x}</li>)}
            </ul>
          </div>
        )}
      </div>

      {prereq.length > 0 && (
        <Section label="Prerequisites still missing">
          <ul className="list-disc list-inside text-slate-400">
            {prereq.map((x, i) => <li key={i}>{x}</li>)}
          </ul>
        </Section>
      )}

      <Section label="Function served">
        <div className="text-slate-300 whitespace-pre-wrap">
          {brief.function_to_serve || <span className="text-slate-600">—</span>}
        </div>
        {brief.interest_anchor && (
          <div className="mt-1 text-slate-400">
            <span className="text-slate-500 text-[10px]">interest anchor: </span>
            {brief.interest_anchor}
          </div>
        )}
      </Section>

      <Section label="Register">
        <DialRow label="vividness" value={reg.vividness} />
        <DialRow label="prose density" value={reg.prose_density} />
        <DialRow label="person/tense" value={reg.person_tense} />
        <DialRow label="emphasis" value={reg.emphasis} />
      </Section>

      <Section label="Piece state">
        <DialRow label="point of view" value={ss.subject_pov} />
        <DialRow label="other subjects" value={ss.subjects} />
        <DialRow label="setting" value={ss.context} />
        <DialRow label="current beat" value={ss.current_section} />
      </Section>

      <Section label="Pacing / avoid">
        <DialRow label="pacing" value={brief.pacing} />
        {avoid.length > 0 && (
          <div className="mt-1">
            <div className="text-slate-500 text-[10px]">hard avoid:</div>
            <ul className="list-disc list-inside text-rose-300/70">
              {avoid.map((x, i) => <li key={i}>{x}</li>)}
            </ul>
          </div>
        )}
      </Section>
    </div>
  );
}

function DialRow({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="flex gap-2">
      <span className="text-slate-500 text-[10px] w-24 shrink-0">{label}</span>
      <span className="text-slate-300 text-[11px]">{value}</span>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-slate-500 mb-1 uppercase text-[10px] tracking-wide">{label}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}
