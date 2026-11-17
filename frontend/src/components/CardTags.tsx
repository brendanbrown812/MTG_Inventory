import { useState } from "react";
import { addCardTag, removeCardTag, type Tag, type TagColor } from "../api";

const COLOR_CLASSES: Record<TagColor, string> = {
  slate: "border-slate-400/30 bg-slate-500/15 text-slate-200",
  red: "border-red-400/30 bg-red-500/15 text-red-200",
  orange: "border-orange-400/30 bg-orange-500/15 text-orange-200",
  amber: "border-amber-400/30 bg-amber-500/15 text-amber-200",
  green: "border-green-400/30 bg-green-500/15 text-green-200",
  teal: "border-teal-400/30 bg-teal-500/15 text-teal-200",
  blue: "border-blue-400/30 bg-blue-500/15 text-blue-200",
  violet: "border-violet-400/30 bg-violet-500/15 text-violet-200",
  pink: "border-pink-400/30 bg-pink-500/15 text-pink-200",
};

export function tagColorClass(color: TagColor): string {
  return COLOR_CLASSES[color] ?? COLOR_CLASSES.slate;
}

export function TagChip({ tag, onRemove, compact = false }: {
  tag: Tag;
  onRemove?: () => void;
  compact?: boolean;
}) {
  return <span className={`inline-flex max-w-full items-center gap-1 rounded-full border ${compact ? "px-1.5 py-0.5 text-[9px]" : "px-2.5 py-1 text-xs"} font-medium ${tagColorClass(tag.color)}`}>
    <span className="truncate">{tag.name}</span>
    {onRemove && <button type="button" onClick={onRemove} aria-label={`Remove ${tag.name}`} className="rounded-full px-0.5 opacity-70 hover:bg-black/20 hover:opacity-100">×</button>}
  </span>;
}

export function CardTagEditor({ oracleId, assigned, available, onChange }: {
  oracleId: string;
  assigned: Tag[];
  available: Tag[];
  onChange: (tags: Tag[]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const choices = available.filter((tag) => !assigned.some((item) => item.id === tag.id));

  async function add(tagId: number) {
    if (!tagId) return;
    setBusy(true); setError("");
    try { onChange(await addCardTag(oracleId, tagId)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not add tag"); }
    finally { setBusy(false); }
  }

  async function remove(tagId: number) {
    setBusy(true); setError("");
    try { onChange(await removeCardTag(oracleId, tagId)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not remove tag"); }
    finally { setBusy(false); }
  }

  return <section>
    <p className="text-xs font-medium uppercase tracking-wider text-stone-500">Tags</p>
    <div className="mt-2 flex flex-wrap gap-2">
      {assigned.map((tag) => <TagChip key={tag.id} tag={tag} onRemove={() => void remove(tag.id)} />)}
      {!assigned.length && <span className="text-xs text-stone-600">No tags assigned.</span>}
    </div>
    <select disabled={busy || !choices.length} value="" onChange={(event) => void add(Number(event.target.value))} className="mt-3 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-sm text-stone-200 outline-none disabled:opacity-50">
      <option value="">{choices.length ? "Add a tag…" : available.length ? "All tags assigned" : "No tags have been created"}</option>
      {choices.map((tag) => <option key={tag.id} value={tag.id}>{tag.name}</option>)}
    </select>
    {error && <p className="mt-2 text-xs text-red-300">{error}</p>}
  </section>;
}
