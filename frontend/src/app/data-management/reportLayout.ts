import type { ExportSpec, HeaderBand, LayoutSpec } from '@/types';

/**
 * Column identity and layout bookkeeping, mirroring export_pipeline on the
 * server. An output column is an instance of a field: "date" or "date::2".
 * Output-shaped things (columns, aliases, formats, bands, blocks) key off the
 * instance; row-shaped things (filters, sorts, grouping) key off the field.
 */

export const INSTANCE_SEP = '::';

export function fieldOf(instanceId: string): string {
  const i = instanceId.lastIndexOf(INSTANCE_SEP);
  if (i <= 0) return instanceId;
  const tail = instanceId.slice(i + INSTANCE_SEP.length);
  return /^\d+$/.test(tail) && Number(tail) >= 2 ? instanceId.slice(0, i) : instanceId;
}

export function newInstanceId(field: string, existing: string[]): string {
  const base = fieldOf(field);
  const taken = new Set(existing);
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base}${INSTANCE_SEP}${n}`)) n += 1;
  return `${base}${INSTANCE_SEP}${n}`;
}

/** The instance ids a spec outputs, in order — what bands and blocks may name. */
export function outputKeys(spec: ExportSpec): string[] {
  if (spec.group_by.length > 0) {
    return [
      ...spec.group_by,
      ...spec.aggregations.map((a) => a.output_key || a.label || a.column),
    ];
  }
  return [...spec.columns, ...spec.custom_columns.map((c) => c.name)];
}

export function emptyLayout(): LayoutSpec {
  return { heading_rows: [], header_tiers: [], blocks: null, sheet_name: null, style: 'plain', freeze_header: true };
}

function isEmpty(l: LayoutSpec): boolean {
  return (
    l.heading_rows.length === 0 &&
    l.header_tiers.every((t) => t.length === 0) &&
    !l.blocks &&
    !l.sheet_name &&
    l.style === 'plain'
  );
}

/**
 * Keep a layout valid after the columns change.
 *
 * Removing or moving a column can leave a band pointing at nothing, running
 * backwards or overlapping its neighbour. Rather than let the save fail, the
 * broken band quietly goes (and the steps panel stops mentioning it): what is
 * on screen is always what the file will be.
 */
export function reconcileLayout(spec: ExportSpec): ExportSpec {
  const layout = spec.layout;
  if (!layout) return spec;
  const keys = outputKeys(spec);
  const pos = new Map(keys.map((k, i) => [k, i] as const));
  const tiers: HeaderBand[][] = [];
  for (const tier of layout.header_tiers) {
    const kept: HeaderBand[] = [];
    for (const b of tier) {
      const a = pos.get(b.from);
      const z = pos.get(b.to);
      if (a === undefined || z === undefined || a > z) continue;
      const clash = kept.some((k) => {
        const ka = pos.get(k.from)!;
        const kz = pos.get(k.to)!;
        return a <= kz && ka <= z;
      });
      if (!clash) kept.push(b);
    }
    if (kept.length) tiers.push(kept);
  }
  const blocks = layout.blocks && pos.has(layout.blocks.by) ? layout.blocks : null;
  const next: LayoutSpec = { ...layout, header_tiers: tiers, blocks };
  return { ...spec, layout: isEmpty(next) ? null : next };
}

/** Which bands of a tier cover each column index, for drawing the preview. */
export function bandStarts(tier: HeaderBand[], keys: string[]): Map<number, { band: HeaderBand; index: number; span: number }> {
  const pos = new Map(keys.map((k, i) => [k, i] as const));
  const out = new Map<number, { band: HeaderBand; index: number; span: number }>();
  tier.forEach((band, index) => {
    const a = pos.get(band.from);
    const z = pos.get(band.to);
    if (a === undefined || z === undefined || a > z) return;
    out.set(a, { band, index, span: z - a + 1 });
  });
  return out;
}

/** Server messages, minus the validator's "Value error, " prefix. */
export function errorText(e: unknown, fallback: string): string {
  if (!(e instanceof Error) || !e.message) return fallback;
  return e.message.replace(/^(?:[^:]*: )?Value error, /, '').replace(/; (?:[^:;]*: )?Value error, /g, '; ');
}

export function ordinal(n: number): string {
  const s = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] || 'th';
  return `${n}${s}`;
}
