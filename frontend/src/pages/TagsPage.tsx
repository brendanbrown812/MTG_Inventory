import { useEffect, useMemo, useState } from "react";
import {
  bulkRemoveCardTags,
  fetchGroupedInventory,
  fetchGuestCollection,
  fetchTags,
  type InventoryOracleGroup,
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
  const [sort, setSort] = useState<CollectionSortMode>("name");
  const [printingSelections] = useState(readCollectionPrintingSelections);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

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

  async function untagSelected() {
    if (!selectedCards.size || !selectedTags.size) return;
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
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not remove tags");
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
          Choose one or more tags, select cards as you collect them, then remove the displayed tags in one step.
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

    {error && <p role="alert" className="rounded-xl border border-red-500/30 bg-red-950/40 px-4 py-3 text-sm text-red-200">{error}</p>}

    {selectedTags.size > 0 && <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl text-stone-100">Matching cards</h2>
          <p className="mt-1 text-sm text-stone-500">{visibleCards.length} cards match at least one selected tag.</p>
        </div>
        <div className="flex items-center gap-3">
          {visibleCards.length > 0 && <button type="button" onClick={() => setSelectedCards(allVisibleSelected ? new Set() : new Set(visibleCards.map((card) => card.oracle_id)))} className="rounded-xl border border-white/10 px-3 py-2 text-sm text-stone-400 transition hover:border-white/25 hover:text-stone-200">
            {allVisibleSelected ? "Clear selection" : "Select all"}
          </button>}
          {selectedCards.size > 0 && <button type="button" disabled={saving} onClick={() => void untagSelected()} className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-2.5 text-sm font-medium text-red-200 hover:bg-red-500/20 disabled:opacity-50">
            {saving ? "Removing tags…" : `Untag Selected (${selectedCards.size})`}
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
            onClick={() => toggleCard(group.oracle_id)}
            className={`relative min-w-0 cursor-pointer self-start rounded-2xl border bg-ink-900/55 p-2 text-left shadow-card transition duration-150 ${checked ? "border-emerald-300/80 bg-emerald-950/30 ring-2 ring-emerald-400/30" : "border-white/10 hover:border-white/25"}`}
          >
            <div className="relative aspect-[5/7] overflow-hidden rounded-xl bg-ink-800">
              {printing?.image_uri_normal ? <img src={printing.image_uri_normal} alt={group.card.name} className="h-full w-full object-cover" loading="lazy" /> : <div className="flex h-full items-center justify-center p-3 text-center text-xs text-stone-400">{group.card.name}</div>}
              <span className="absolute bottom-1.5 right-1.5 rounded-full bg-black/75 px-2 py-0.5 font-mono text-xs font-semibold text-stone-200">×{group.total_quantity}</span>
              {checked && <div className="absolute inset-0 flex items-center justify-center bg-emerald-500/30 backdrop-saturate-150">
                <span className="flex h-20 w-20 items-center justify-center rounded-full border-4 border-emerald-100 bg-emerald-600/85 text-6xl font-black leading-none text-white shadow-[0_0_35px_rgba(16,185,129,0.85)]">✓</span>
              </div>}
            </div>
            <div className="mt-2 border-t border-white/10 pt-2">
              <div className="flex flex-wrap gap-1">{group.tags.map((tag) => <TagChip key={tag.id} tag={tag} />)}</div>
            </div>
          </button>;
        })}
      </div>}
    </section>}
  </div>;
}
