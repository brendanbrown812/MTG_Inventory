import { useEffect, useMemo, useState } from "react";
import {
  bulkRemoveInventory,
  bulkRemoveCardTags,
  fetchGroupedInventory,
  fetchGuestCollection,
  fetchTags,
  type InventoryOracleGroup,
  type InventoryRemovalEntry,
  type Tag,
} from "../api";
import { TagChip } from "../components/CardTags";
import {
  collectionSelectedPrinting,
  compareCollectionCards,
  readCollectionPrintingSelections,
  type CollectionSortMode,
} from "../lib/collectionSorting";

export default function TagsPage({ guest = false }: { guest?: boolean }) {
  const [tags, setTags] = useState<Tag[]>([]);
  const [cards, setCards] = useState<InventoryOracleGroup[]>([]);
  const [selectedTags, setSelectedTags] = useState<Set<number>>(new Set());
  const [selectedCards, setSelectedCards] = useState<Set<string>>(new Set());
  const [removalPlans, setRemovalPlans] = useState<Record<string, Record<number, number>>>({});
  const [editingCard, setEditingCard] = useState<InventoryOracleGroup | null>(null);
  const [removalDraft, setRemovalDraft] = useState<Record<number, string>>({});
  const [sort, setSort] = useState<CollectionSortMode>("name");
  const [printingSelections] = useState(readCollectionPrintingSelections);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([fetchTags(), guest ? fetchGuestCollection() : fetchGroupedInventory("")])
      .then(([availableTags, collection]) => {
        if (!active) return;
        setTags(availableTags);
        setCards(collection);
      })
      .catch((reason: Error) => { if (active) setError(reason.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [guest]);

  const visibleCards = useMemo(() => {
    if (!selectedTags.size) return [];
    return cards
      .filter((group) => group.tags.some((tag) => selectedTags.has(tag.id)))
      .sort((left, right) => compareCollectionCards(left, right, sort, printingSelections));
  }, [cards, selectedTags, sort, printingSelections]);

  useEffect(() => {
    const visibleIds = new Set(visibleCards.map((card) => card.oracle_id));
    setSelectedCards((current) => new Set([...current].filter((oracleId) => visibleIds.has(oracleId))));
  }, [visibleCards]);

  function toggleTag(tagId: number) {
    setSelectedTags((current) => {
      const next = new Set(current);
      if (next.has(tagId)) next.delete(tagId);
      else next.add(tagId);
      return next;
    });
  }

  function toggleCard(oracleId: string) {
    setSelectedCards((current) => {
      const next = new Set(current);
      if (next.has(oracleId)) next.delete(oracleId);
      else next.add(oracleId);
      return next;
    });
  }

  function openRemovalPlanner(group: InventoryOracleGroup) {
    const existing = removalPlans[group.oracle_id] ?? {};
    const lines = group.printings.flatMap((printing) => printing.lines);
    const initial = Object.keys(existing).length > 0
      ? Object.fromEntries(lines.map((line) => [line.id, String(existing[line.id] ?? 0)]))
      : Object.fromEntries(lines.map((line) => [line.id, lines.length === 1 ? "1" : "0"]));
    setRemovalDraft(initial);
    setEditingCard(group);
    setError("");
  }

  function saveRemovalPlan() {
    if (!editingCard) return;
    const available = new Map(
      editingCard.printings.flatMap((printing) => printing.lines.map((line) => [line.id, line.quantity])),
    );
    const next: Record<number, number> = {};
    for (const [rawLineId, rawQuantity] of Object.entries(removalDraft)) {
      const lineId = Number(rawLineId);
      const quantity = Number(rawQuantity);
      const owned = available.get(lineId) ?? 0;
      if (!Number.isInteger(quantity) || quantity < 0 || quantity > owned) {
        setError(`Removal quantities must be whole numbers between 0 and the owned quantity.`);
        return;
      }
      if (quantity > 0) next[lineId] = quantity;
    }
    if (!Object.keys(next).length) {
      setError("Choose at least one physical copy to remove.");
      return;
    }
    const oracleId = editingCard.oracle_id;
    setRemovalPlans((current) => ({ ...current, [oracleId]: next }));
    setSelectedCards((current) => new Set(current).add(oracleId));
    setEditingCard(null);
    setError("");
  }

  function clearRemovalPlan(oracleId: string) {
    setRemovalPlans((current) => {
      const next = { ...current };
      delete next[oracleId];
      return next;
    });
    setSelectedCards((current) => {
      const next = new Set(current);
      next.delete(oracleId);
      return next;
    });
    setEditingCard(null);
  }

  function plannedCopies(oracleId: string): number {
    return Object.values(removalPlans[oracleId] ?? {}).reduce((total, quantity) => total + quantity, 0);
  }

  function adjustRemovalQuantity(lineId: number, delta: number, maximum: number) {
    setRemovalDraft((current) => {
      const parsed = Number(current[lineId] ?? "0");
      const quantity = Number.isFinite(parsed) ? parsed : 0;
      return {
        ...current,
        [lineId]: String(Math.min(maximum, Math.max(0, quantity + delta))),
      };
    });
  }

  async function untagSelected() {
    if (guest || !selectedCards.size || !selectedTags.size) return;
    setSaving(true);
    setError("");
    try {
      const oracleIds = [...selectedCards];
      const tagIds = [...selectedTags];
      await bulkRemoveCardTags(oracleIds, tagIds);
      const oracleSet = new Set(oracleIds);
      const tagSet = new Set(tagIds);
      setCards((current) => current.map((group) => oracleSet.has(group.oracle_id)
        ? { ...group, tags: group.tags.filter((tag) => !tagSet.has(tag.id)) }
        : group));
      setSelectedCards(new Set());
      setRemovalPlans({});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not remove tags");
    } finally {
      setSaving(false);
    }
  }

  async function removeSelectedFromCollection() {
    if (guest || !selectedCards.size || !selectedTags.size) return;
    const removals: InventoryRemovalEntry[] = [];
    for (const group of cards) {
      if (!selectedCards.has(group.oracle_id)) continue;
      for (const [rawLineId, quantity] of Object.entries(removalPlans[group.oracle_id] ?? {})) {
        if (quantity > 0) removals.push({
          oracle_id: group.oracle_id,
          line_id: Number(rawLineId),
          quantity,
        });
      }
    }
    if (!removals.length) return;
    const copyCount = removals.reduce((total, entry) => total + entry.quantity, 0);
    if (!confirm(`Remove ${copyCount} physical ${copyCount === 1 ? "card" : "cards"} from the collection and complete the selected tag tasks?`)) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const result = await bulkRemoveInventory(removals, [...selectedTags]);
      const collection = await fetchGroupedInventory("");
      setCards(collection);
      setSelectedCards(new Set());
      setRemovalPlans({});
      setNotice(`Removed ${result.removed_copies} physical ${result.removed_copies === 1 ? "card" : "cards"} from ${result.removed_cards} ${result.removed_cards === 1 ? "card entry" : "card entries"}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not remove inventory copies");
    } finally {
      setSaving(false);
    }
  }

  const allVisibleSelected = visibleCards.length > 0 && visibleCards.every((card) => selectedCards.has(card.oracle_id));

  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-4xl font-semibold text-stone-100">Tags</h1>
        <p className="mt-2 max-w-2xl text-stone-400">
          {guest ? "Choose one or more tags and select cards as you collect them." : "Choose one or more tags, select cards as you collect them, then remove the displayed tags in one step."}
        </p>
      </div>
      <select value={sort} onChange={(event) => setSort(event.target.value as CollectionSortMode)} className="rounded-xl border border-white/10 bg-ink-900/80 px-4 py-2.5 text-sm text-stone-200 outline-none">
        <option value="name">Sort: Name</option>
        <option value="quantity">Sort: Quantity</option>
        <option value="set">Sort: Set / number</option>
      </select>
    </div>

    <section className="rounded-2xl border border-white/10 bg-ink-900/55 p-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-display text-xl text-stone-100">Choose tags</h2>
        {selectedTags.size > 0 && <button type="button" onClick={() => setSelectedTags(new Set())} className="text-xs text-stone-500 hover:text-stone-300">Clear</button>}
      </div>
      <div className="mt-4 flex flex-wrap gap-3">
        {tags.map((tag) => <button
          key={tag.id}
          type="button"
          aria-pressed={selectedTags.has(tag.id)}
          onClick={() => toggleTag(tag.id)}
          className={`flex items-center rounded-xl border px-3 py-2 transition duration-150 ${selectedTags.has(tag.id) ? "scale-105 border-ember-300/70 bg-ember-500/20 font-bold shadow-[0_0_24px_rgba(212,137,106,0.22)] ring-2 ring-ember-400/25" : "border-white/10 bg-ink-950/40 opacity-55 hover:border-white/30 hover:opacity-90"}`}
        >
          <TagChip tag={tag} />
        </button>)}
        {!loading && !tags.length && <p className="text-sm text-stone-500">No tags have been created yet.</p>}
      </div>
    </section>

    {error && !editingCard && <p role="alert" className="rounded-xl border border-red-500/30 bg-red-950/40 px-4 py-3 text-sm text-red-200">{error}</p>}
    {notice && <p className="rounded-xl border border-emerald-500/30 bg-emerald-950/40 px-4 py-3 text-sm text-emerald-200">{notice}</p>}

    {selectedTags.size > 0 && <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl text-stone-100">Matching cards</h2>
          <p className="mt-1 text-sm text-stone-500">{visibleCards.length} cards match at least one selected tag.</p>
        </div>
        <div className="flex items-center gap-3">
          {guest && visibleCards.length > 0 && <button type="button" onClick={() => setSelectedCards(allVisibleSelected ? new Set() : new Set(visibleCards.map((card) => card.oracle_id)))} className="rounded-xl border border-white/10 px-3 py-2 text-sm text-stone-400 transition hover:border-white/25 hover:text-stone-200">
            {allVisibleSelected ? "Clear selection" : "Select all"}
          </button>}
          {!guest && selectedCards.size > 0 && <button type="button" disabled={saving} onClick={() => void untagSelected()} className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-2.5 text-sm font-medium text-red-200 hover:bg-red-500/20 disabled:opacity-50">
            {saving ? "Removing tags…" : `Untag Selected (${selectedCards.size})`}
          </button>}
          {!guest && selectedCards.size > 0 && <button type="button" disabled={saving} onClick={() => void removeSelectedFromCollection()} className="rounded-xl border border-emerald-400/40 bg-emerald-500/15 px-4 py-2.5 text-sm font-semibold text-emerald-100 hover:bg-emerald-500/25 disabled:opacity-50">
            {saving ? "Updating collection…" : `Remove from Collection (${Object.keys(removalPlans).filter((oracleId) => selectedCards.has(oracleId)).reduce((total, oracleId) => total + plannedCopies(oracleId), 0)})`}
          </button>}
        </div>
      </div>

      {loading ? <p className="py-16 text-center text-stone-500">Loading collection…</p> : visibleCards.length === 0 ? <p className="py-16 text-center text-stone-500">No cards currently have the selected tags.</p> :
      <div className="grid grid-cols-[repeat(auto-fill,minmax(155px,1fr))] gap-3 sm:grid-cols-[repeat(auto-fill,minmax(175px,1fr))] xl:grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        {visibleCards.map((group) => {
          const printing = collectionSelectedPrinting(group, printingSelections);
          const checked = selectedCards.has(group.oracle_id);
          return <button
            key={group.oracle_id}
            type="button"
            aria-pressed={checked}
            onClick={() => guest ? toggleCard(group.oracle_id) : openRemovalPlanner(group)}
            className={`relative min-w-0 cursor-pointer self-start rounded-2xl border bg-ink-900/55 p-2 text-left shadow-card transition duration-150 ${checked ? "border-emerald-300/80 bg-emerald-950/30 ring-2 ring-emerald-400/30" : "border-white/10 hover:border-white/25"}`}
          >
            <div className="relative aspect-[5/7] overflow-hidden rounded-xl bg-ink-800">
              {printing?.image_uri_normal ? <img src={printing.image_uri_normal} alt={group.card.name} className="h-full w-full object-cover" loading="lazy" /> : <div className="flex h-full items-center justify-center p-3 text-center text-xs text-stone-400">{group.card.name}</div>}
              <span className="absolute bottom-1.5 right-1.5 rounded-full bg-black/75 px-2 py-0.5 font-mono text-xs font-semibold text-stone-200">×{group.total_quantity}</span>
              {checked && <div className="absolute inset-0 flex items-center justify-center bg-emerald-500/30 backdrop-saturate-150">
                <span className="flex h-20 w-20 items-center justify-center rounded-full border-4 border-emerald-100 bg-emerald-600/85 text-6xl font-black leading-none text-white shadow-[0_0_35px_rgba(16,185,129,0.85)]">✓</span>
              </div>}
              {!guest && checked && <span className="absolute right-2 top-2 z-10 rounded-full bg-emerald-950/90 px-2.5 py-1 text-xs font-bold text-emerald-100 ring-1 ring-emerald-300/50">Remove ×{plannedCopies(group.oracle_id)}</span>}
            </div>
            <div className="mt-2 border-t border-white/10 pt-2">
              <div className="flex flex-wrap gap-1">{group.tags.map((tag) => <TagChip key={tag.id} tag={tag} />)}</div>
            </div>
          </button>;
        })}
      </div>}
    </section>}

    {editingCard && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <button type="button" className="absolute inset-0" aria-label="Close removal planner" onClick={() => { setEditingCard(null); setError(""); }} />
      <div className="relative max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-white/10 bg-ink-900 p-6 shadow-card">
        <button type="button" onClick={() => { setEditingCard(null); setError(""); }} className="absolute right-3 top-3 rounded-full bg-black/40 px-2.5 py-1 text-stone-300">×</button>
        <h2 className="font-display text-2xl text-stone-100">Choose copies of {editingCard.card.name}</h2>
        <p className="mt-2 text-sm text-stone-400">
          {editingCard.printing_count > 1
            ? "This card has multiple owned printings. Enter the exact quantities you physically removed from each inventory line."
            : "Enter how many physical copies you removed."}
        </p>
        <div className="mt-5 space-y-4">
          {editingCard.printings.map((printing) => <section key={printing.scryfall_id} className="rounded-xl border border-white/10 bg-ink-950/45 p-4">
            <div className="flex gap-4">
              {printing.image_uri_normal && <img src={printing.image_uri_normal} alt="" className="hidden w-20 self-start rounded-lg sm:block" />}
              <div className="min-w-0 flex-1">
                <p className="font-medium text-stone-200">{[printing.set_code?.toUpperCase(), printing.collector_number ? `#${printing.collector_number}` : null].filter(Boolean).join(" · ") || "Unknown printing"}</p>
                <div className="mt-3 space-y-3">
                  {printing.lines.map((line) => <div key={line.id} className="flex items-center justify-between gap-4 rounded-lg border border-white/5 bg-ink-900/60 px-3 py-2">
                    <span className="min-w-0 text-sm text-stone-400">
                      <strong className="text-stone-200">{line.quantity} owned</strong>
                      {line.foil ? " · Foil" : " · Nonfoil"}
                      {line.condition ? ` · ${line.condition}` : ""}
                      {line.language ? ` · ${line.language.toUpperCase()}` : ""}
                    </span>
                    <div className="flex shrink-0 items-center overflow-hidden rounded-lg border border-white/10 bg-ink-950 shadow-inner">
                      <button type="button" aria-label="Decrease quantity" onClick={() => adjustRemovalQuantity(line.id, -1, line.quantity)} disabled={Number(removalDraft[line.id] ?? "0") <= 0} className="flex h-10 w-10 items-center justify-center border-r border-white/10 text-xl font-medium text-stone-400 transition hover:bg-white/5 hover:text-stone-100 disabled:cursor-not-allowed disabled:opacity-25">−</button>
                      <input type="text" inputMode="numeric" pattern="[0-9]*" value={removalDraft[line.id] ?? "0"} onChange={(event) => setRemovalDraft((current) => ({ ...current, [line.id]: event.target.value.replace(/[^0-9]/g, "") }))} aria-label={`Quantity to remove from ${printing.set_code ?? "printing"} ${printing.collector_number ?? ""}`} className="h-10 w-12 bg-transparent px-1 text-center font-mono text-base font-semibold text-stone-100 outline-none focus:bg-emerald-500/10" />
                      <button type="button" aria-label="Increase quantity" onClick={() => adjustRemovalQuantity(line.id, 1, line.quantity)} disabled={Number(removalDraft[line.id] ?? "0") >= line.quantity} className="flex h-10 w-10 items-center justify-center border-l border-white/10 text-xl font-medium text-stone-400 transition hover:bg-white/5 hover:text-stone-100 disabled:cursor-not-allowed disabled:opacity-25">+</button>
                    </div>
                  </div>)}
                </div>
              </div>
            </div>
          </section>)}
        </div>
        {error && <p role="alert" className="mt-4 rounded-xl border border-red-500/30 bg-red-950/40 px-3 py-2 text-sm text-red-200">{error}</p>}
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          {removalPlans[editingCard.oracle_id] && <button type="button" onClick={() => clearRemovalPlan(editingCard.oracle_id)} className="rounded-xl border border-red-400/30 px-4 py-2 text-sm text-red-200 hover:bg-red-950/30">Clear plan</button>}
          <button type="button" onClick={() => { setEditingCard(null); setError(""); }} className="rounded-xl border border-white/10 px-4 py-2 text-sm text-stone-300">Cancel</button>
          <button type="button" onClick={saveRemovalPlan} className="rounded-xl border border-emerald-400/40 bg-emerald-500/15 px-4 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-500/25">Use these copies</button>
        </div>
      </div>
    </div>}
  </div>;
}
