"use client";

import { MindMap } from "./MindMap";
import { SAMPLE_GRAPH, SAMPLE_INSIGHTS } from "./sampleGraph";
import { clusterColor } from "./mapHelpers";

// Mirrors InsightsPanel's palette so the demo and the real surface read the same.
const KIND_COLORS: Record<string, string> = {
  pattern: "#06b6d4",
  tension: "#a855f7",
  bridge: "#f59e0b",
  function: "#10b981",
  angle: "#34d399",
};

/**
 * The signed-out proof for the homepage claim. Renders the REAL map component
 * against a static fictional dataset — no auth, no backend call — so a visitor
 * can see the thing the hero copy describes instead of taking it on faith.
 *
 * The angle strip below is a READ-ONLY stand-in for the real InsightsPanel: that
 * component fetches interpretations and offers affirm/reject actions, both of
 * which need an account. Same information, none of the interactivity that would
 * fail signed-out.
 */
export function SampleGraphSection() {
  const clusterLabel = (id: string) =>
    SAMPLE_GRAPH.clusters.find((c) => c.id === id)?.label ?? "";

  const clusterIdx = (id: string) => SAMPLE_GRAPH.clusters.findIndex((c) => c.id === id);

  // Group by statement. The same angle landing on two clusters is the point of
  // this sample, but rendered one-row-per-interpretation it reads as a duplicated
  // row — i.e. as a bug, the opposite of the intended effect. Grouped, it reads as
  // the finding it is. Shared entries span the grid.
  const insights = Object.values(
    SAMPLE_INSIGHTS.reduce<
      Record<
        string,
        {
          statement: string;
          kind: string;
          cluster_ids: string[];
          hits: { cluster_id: string; confidence: number; inferential_step: string }[];
        }
      >
    >((acc, it) => {
      acc[it.statement] ??= {
        statement: it.statement,
        kind: it.kind,
        cluster_ids: [],
        hits: [],
      };
      // Union across the group — a shared angle is two rows, each naming one
      // cluster, so taking the first row's ids would silently drop the second
      // theme from the card that exists to show both.
      for (const cid of it.cluster_ids) {
        if (!acc[it.statement].cluster_ids.includes(cid)) {
          acc[it.statement].cluster_ids.push(cid);
        }
      }
      acc[it.statement].hits.push({
        cluster_id: it.cluster_ids[0],
        confidence: it.confidence,
        inferential_step: it.inferential_step,
      });
      return acc;
    }, {}),
  );

  return (
    <section id="sample-model" className="w-full border-t border-[var(--border)] bg-[var(--background)] scroll-mt-14">
      <div className="max-w-5xl mx-auto px-4 py-12 sm:py-16 flex flex-col gap-5">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-2xl font-bold text-[var(--foreground)]">
              A sample model
            </h2>
            <span className="text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full border border-[var(--border)] text-[var(--muted)]">
              Example — not real data
            </span>
          </div>
          <p className="text-sm text-[var(--muted)] max-w-2xl">
            A fictional user&apos;s map after a handful of conversations. Each dot is
            a concept pulled from what they said; colour groups them into themes;
            solid lines are relationships the engine extracted. The faint dashed
            threads are <span className="text-[var(--foreground)]">co-occurrence</span>
            {" "}— things they mention together without ever explicitly connecting
            them. You can turn those off in the legend.
          </p>
        </div>

        <div className="h-[440px] w-full rounded-xl overflow-hidden border border-[var(--border)] shadow-sm">
          <MindMap userId={null} sampleData={SAMPLE_GRAPH} />
        </div>

        {/* Read-only insight strip — the typed output, which is the actual claim.
            Deliberately short: two findings that hold up beat a full panel of
            plausible ones, and a fabricated cross-cluster bridge in particular
            reads as glib, because a real bridge earns itself over many turns. */}
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-[var(--foreground)]">
            What it concluded
          </h3>
          <div className="flex flex-col gap-2">
            {insights.map((it) => {
              const shared = it.hits.length > 1;
              const color = KIND_COLORS[it.kind] ?? "#94a3b8";
              return (
                <div
                  key={it.statement}
                  className={`flex flex-col gap-1 rounded-lg border bg-[var(--surface)] p-3 ${
                    shared ? "border-[var(--primary)]" : "border-[var(--border)]"
                  }`}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className="text-[10px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded"
                      style={{ color, background: `${color}1a` }}
                    >
                      {it.kind}
                    </span>
                    <span className="text-[10px] text-[var(--muted)]">
                      conf {it.hits.map((h) => h.confidence.toFixed(2)).join(" · ")}
                    </span>
                    <span className="flex -space-x-1" aria-hidden>
                      {it.cluster_ids.map((cid) => (
                        <span
                          key={cid}
                          className="w-2.5 h-2.5 rounded-full ring-1 ring-[var(--surface)]"
                          style={{ backgroundColor: clusterColor(cid, clusterIdx(cid)) }}
                        />
                      ))}
                    </span>
                    <span className="text-[10px] text-[var(--muted)] truncate">
                      {it.cluster_ids.map(clusterLabel).join(" + ")}
                    </span>
                    {shared && (
                      <span className="ml-auto text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full border border-[var(--primary)] text-[var(--primary)]">
                        same angle, two themes
                      </span>
                    )}
                  </div>
                  <p className="text-[13px] leading-snug text-[var(--foreground)]">
                    {it.statement}
                  </p>
                  {it.hits.map((h) => (
                    <p
                      key={h.cluster_id}
                      className="text-[11px] italic text-[var(--muted)] leading-snug"
                    >
                      {shared && (
                        <span className="not-italic">{clusterLabel(h.cluster_id)}: </span>
                      )}
                      inference: {h.inferential_step}
                    </p>
                  ))}
                </div>
              );
            })}
          </div>
          <p className="text-sm text-[var(--foreground)]">
            Two different kinds of claim. The{" "}
            <span className="font-medium">angle</span>{" "}
            turned up on two themes that don&apos;t obviously belong together — a
            postmortem and someone&apos;s description of their own process are both
            written accounts, and this person goes to the raw thing instead. The{" "}
            <span className="font-medium">tension</span>{" "}
            isn&apos;t a conclusion at all: it names something still unresolved and
            keeps it in view rather than deciding it.
          </p>
        </div>

        <p className="text-xs text-[var(--muted)]">
          Static illustration. Your own map is built from your conversations and is
          private to your account.
        </p>
      </div>
    </section>
  );
}
