"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { type Graph, layoutGraph } from "@/lib/studio";

const W = 148;
const H = 44;
const GAP_X = 56;
const GAP_Y = 22;

const TYPE_COLOUR: Record<string, string> = {
  route: "fill-violet-100 stroke-violet-400 dark:fill-violet-400/15",
  retrieve: "fill-sky-100 stroke-sky-400 dark:fill-sky-400/15",
  call_tool: "fill-rose-100 stroke-rose-400 dark:fill-rose-400/15",
  validate_evidence: "fill-amber-100 stroke-amber-400 dark:fill-amber-400/15",
  clarify: "fill-amber-100 stroke-amber-400 dark:fill-amber-400/15",
  approve: "fill-rose-100 stroke-rose-400 dark:fill-rose-400/15",
  respond: "fill-teal-100 stroke-teal-500 dark:fill-teal-400/15",
  escalate: "fill-slate-200 stroke-slate-400 dark:fill-slate-400/15",
};

/**
 * Read-only picture of a declarative graph (ST-11). With ``active``, the nodes and edges a run went
 * through are highlighted (Answer Inspector). A list version follows for screen readers.
 */
export function GraphView({ graph, active, className }: { graph: Graph; active?: { nodes: Set<string>; edges: Set<string> }; className?: string }) {
  const t = useTranslations("graph");
  const { nodes, layers, rows } = layoutGraph(graph);
  const pos = new Map(nodes.map((n) => [n.id, { x: 12 + n.layer * (W + GAP_X), y: 12 + n.row * (H + GAP_Y) }]));
  const width = 24 + layers * W + (layers - 1) * GAP_X;
  const height = 24 + rows * H + (rows - 1) * GAP_Y;
  const on = (id: string) => !active || active.nodes.has(id);
  const edgeOn = (from: string, to: string) => !active || active.edges.has(`${from}->${to}`);

  return (
    <figure className={cn("space-y-2", className)}>
      <div className="overflow-x-auto rounded-xl border bg-muted/30 p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" tabIndex={0} role="group" aria-label={t("scrollLabel")}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          role="img"
          aria-label={t("label", { count: graph.nodes.length })}
          className="max-w-none"
        >
          <defs>
            <marker id="nx-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" className="fill-muted-foreground" />
            </marker>
            <marker id="nx-arrow-on" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" className="fill-primary" />
            </marker>
          </defs>
          {graph.edges.map((e, i) => {
            const a = pos.get(e.from);
            const b = pos.get(e.to);
            if (!a || !b) return null;
            const back = b.x <= a.x;
            const x1 = a.x + W;
            const y1 = a.y + H / 2;
            const x2 = back ? b.x + W / 2 : b.x;
            const y2 = back ? b.y + H : b.y + H / 2;
            const mid = (x1 + x2) / 2;
            const d = back
              ? `M${a.x + W / 2},${a.y + H} C${a.x + W / 2},${a.y + H + 40} ${x2},${y2 + 40} ${x2},${y2}`
              : `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`;
            const lit = edgeOn(e.from, e.to);
            return (
              <g key={i} className={cn(!lit && "opacity-25")}>
                <path d={d} fill="none" strokeWidth={lit && active ? 2.5 : 1.5} className={lit && active ? "stroke-primary" : "stroke-muted-foreground"} markerEnd={`url(#${lit && active ? "nx-arrow-on" : "nx-arrow"})`} />
                {e.when ? (
                  <text x={back ? x2 + 6 : mid} y={back ? y2 + 30 : (y1 + y2) / 2 - 4} textAnchor="middle" className="fill-muted-foreground text-[10px]">
                    {e.when}
                  </text>
                ) : null}
              </g>
            );
          })}
          {nodes.map((n) => {
            const p = pos.get(n.id)!;
            return (
              <g key={n.id} className={cn(!on(n.id) && "opacity-30")} data-testid={`graph-node-${n.id}`} data-active={active ? String(on(n.id)) : undefined}>
                <rect x={p.x} y={p.y} width={W} height={H} rx={10} strokeWidth={active && on(n.id) ? 2.5 : 1.25} className={TYPE_COLOUR[n.type] ?? "fill-card stroke-border"} />
                {n.id === graph.entry ? <circle cx={p.x + 10} cy={p.y + 10} r={3.5} className="fill-primary" /> : null}
                <text x={p.x + W / 2} y={p.y + 19} textAnchor="middle" className="fill-foreground text-[12px] font-semibold">{n.id}</text>
                <text x={p.x + W / 2} y={p.y + 34} textAnchor="middle" className="fill-muted-foreground text-[10px]">{t(`types.${n.type}`)}</text>
              </g>
            );
          })}
        </svg>
      </div>
      <figcaption className="sr-only">
        <ol>
          {graph.edges.map((e, i) => (
            <li key={i}>{t("edge", { from: e.from, to: e.to, when: e.when ?? t("always") })}</li>
          ))}
        </ol>
      </figcaption>
    </figure>
  );
}
