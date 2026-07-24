// react-force-graph-2d bundles d3-force-3d, which ships no TypeScript types.
// We only reach into it for forceCollide (to add a non-overlap force to the
// existing simulation), so a minimal ambient declaration is enough to satisfy
// strict mode without pulling in a full @types package.
declare module "d3-force-3d" {
  type RadiusAccessor<N> = number | ((node: N, i: number, nodes: N[]) => number);

  /** A d3-force collision force; setters return the force for chaining. */
  interface CollideForce<N> {
    (alpha: number): void;
    radius(r: RadiusAccessor<N>): CollideForce<N>;
    strength(s: number): CollideForce<N>;
    iterations(n: number): CollideForce<N>;
  }

  /** radius may be a constant or a per-node accessor. */
  export function forceCollide<N = unknown>(radius?: RadiusAccessor<N>): CollideForce<N>;
}
