import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  fetchGuestCollection, fetchGuestDeck, fetchGuestDecks,
  type Deck, type DeckCard, type DeckDetail, type InventoryOracleGroup,
} from "../api";
import { GuestPrintingGallery } from "../components/GuestPrintingGallery";
import { collectionGuestPrintings, deckGuestPrintings } from "../lib/guestPrintings";
import { cardTypeCategory, compareDeckCards, TYPE_ORDER, TYPE_SECTION_LABELS, type DeckSortMode } from "../lib/deckSorting";
import { formatOptionLabel } from "../lib/formats";

const inputStyle = "rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm text-stone-200 outline-none focus:ring-2 focus:ring-ember-400/30";

function ErrorMessage({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-xl border border-red-500/30 bg-red-950/40 p-4 text-sm text-red-200">{message}</p> : null;
}

export function GuestCollectionPage() {
  const [cards, setCards] = useState<InventoryOracleGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => {
    let active = true;
    fetchGuestCollection().then((rows) => { if (active) setCards(rows); })
      .catch((e: Error) => { if (active) setError(e.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const filtered = useMemo(() => cards.filter(({ card }) =>
    `${card.name} ${card.type_line ?? ""} ${card.mana_cost ?? ""}`.toLowerCase().includes(query.toLowerCase().trim())
  ).sort((a, b) => a.card.name.localeCompare(b.card.name)), [cards, query]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / 60));
  return <div className="space-y-6">
    <div><h1 className="font-display text-4xl text-stone-100">Collection</h1>
      <p className="mt-2 text-stone-400">{cards.length.toLocaleString()} unique cards · {cards.reduce((total, row) => total + row.total_quantity, 0).toLocaleString()} total copies</p>
    </div>
    <label className="block text-sm text-stone-400">Search cards
      <input value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} placeholder="Card name, type, or mana cost…" className={`${inputStyle} mt-2 block w-full sm:max-w-lg`} />
    </label>
    <ErrorMessage message={error} />
    {loading ? <p className="text-stone-400">Loading collection…</p> : <>
      <p className="text-sm text-stone-500">{filtered.length.toLocaleString()} matching cards. Browse the owned prints with the arrows; click any image to enlarge it.</p>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(155px,1fr))] gap-3 sm:grid-cols-[repeat(auto-fill,minmax(175px,1fr))] xl:grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        {filtered.slice(page * 60, (page + 1) * 60).map((group) => <article key={group.oracle_id} className="overflow-hidden rounded-xl border border-white/10 bg-ink-900/40">
          <GuestPrintingGallery name={group.card.name} printings={collectionGuestPrintings(group)} />
          <p className="px-3 pb-3 text-xs text-stone-500">{group.total_quantity} total copies · {group.printing_count} {group.printing_count === 1 ? "printing" : "printings"}</p>
        </article>)}
      </div>
      {!filtered.length && <p className="text-stone-400">No cards found.</p>}
      {pageCount > 1 && <div className="flex items-center justify-center gap-4">
        <button disabled={page === 0} onClick={() => setPage(page - 1)} className={`${inputStyle} disabled:opacity-40`}>Previous</button>
        <span className="text-sm text-stone-400">Page {page + 1} of {pageCount}</span>
        <button disabled={page + 1 >= pageCount} onClick={() => setPage(page + 1)} className={`${inputStyle} disabled:opacity-40`}>Next</button>
      </div>}
    </>}
  </div>;
}

export function GuestDecksPage() {
  const [decks, setDecks] = useState<Deck[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    let active = true;
    fetchGuestDecks().then((rows) => { if (active) setDecks(rows); })
      .catch((e: Error) => { if (active) setError(e.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const filtered = decks.filter((deck) => `${deck.name} ${deck.commander_name ?? ""}`.toLowerCase().includes(query.toLowerCase().trim()));
  return <div className="space-y-6">
    <div><h1 className="font-display text-4xl text-stone-100">Decks</h1><p className="mt-2 text-stone-400">Browse {decks.length} shared decks and their card lists.</p></div>
    <input aria-label="Search decks" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search deck or commander…" className={`${inputStyle} w-full sm:max-w-lg`} />
    <ErrorMessage message={error} />
    {loading ? <p className="text-stone-400">Loading decks…</p> : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {filtered.map((deck) => <Link key={deck.id} to={`/decks/${deck.id}`} className="rounded-2xl border border-white/10 bg-ink-900/40 p-6 transition hover:border-ember-400/40">
        <h2 className="font-display text-2xl text-stone-100">{deck.name}</h2>
        {deck.commander_name && <p className="mt-2 text-stone-300">{deck.commander_name}</p>}
        <p className="mt-3 text-sm text-stone-500">{formatOptionLabel(deck.format)} · {deck.status}</p>
      </Link>)}
      {!filtered.length && <p className="text-stone-400">No decks found.</p>}
    </div>}
  </div>;
}

export function GuestDeckDetailPage() {
  const { id } = useParams();
  const [deck, setDeck] = useState<DeckDetail | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [sortMode, setSortMode] = useState<DeckSortMode>(() => {
    const saved = localStorage.getItem("spellbinder:deck-detail:sort");
    return saved === "type" || saved === "color" ? saved : "name";
  });
  useEffect(() => {
    localStorage.setItem("spellbinder:deck-detail:sort", sortMode);
  }, [sortMode]);
  useEffect(() => {
    let active = true;
    setDeck(null);
    setError("");
    setQuery("");
    fetchGuestDeck(Number(id)).then((row) => { if (active) setDeck(row); })
      .catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [id]);
  const sections: [string, DeckCard[]][] = deck ? [
    ["Commander", deck.cards.filter((row) => row.is_commander)],
    ["Main deck", deck.cards.filter((row) => !row.is_commander && !row.is_sideboard)],
    ["Sideboard", deck.cards.filter((row) => !row.is_commander && row.is_sideboard)],
  ] : [];
  return <div className="space-y-6">
    <Link to="/decks" className="text-sm text-ember-200 hover:underline">← All decks</Link>
    <ErrorMessage message={error} />
    {!deck && !error && <p className="text-stone-400">Loading deck…</p>}
    {deck && <>
      <div><h1 className="font-display text-4xl text-stone-100">{deck.name}</h1>
        {deck.commander_name && <p className="mt-2 text-arcane-200">Commander: {deck.commander_name}</p>}
        <p className="mt-2 text-stone-400">{formatOptionLabel(deck.format)} · {deck.status} · {deck.cards.reduce((total, row) => total + row.quantity, 0)} cards including sideboard</p>
      </div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <input aria-label="Search deck cards" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search cards in this deck…" className={`${inputStyle} w-full sm:max-w-lg`} />
        <label className="text-xs font-medium uppercase tracking-wider text-stone-500">Sort
          <select value={sortMode} onChange={(event) => setSortMode(event.target.value as DeckSortMode)} className={`${inputStyle} ml-2 normal-case tracking-normal`}>
            <option value="name">Alphabetical</option>
            <option value="type">Card type</option>
            <option value="color">Color · WUBRG</option>
          </select>
        </label>
      </div>
      {!deck.cards.length && <p className="text-stone-400">This deck has no cards yet.</p>}
      <div className="space-y-6">
        {sections.filter(([, rows]) => rows.length > 0).map(([title, rows]) => {
          const visible = rows.filter((row) => title === "Commander" || `${row.card?.name ?? row.scryfall_id} ${row.card?.type_line ?? ""}`.toLowerCase().includes(query.toLowerCase().trim()))
            .sort((a, b) => compareDeckCards(a.card, b.card, sortMode) || a.id - b.id);
          const groups = sortMode === "type" && title !== "Commander"
            ? TYPE_ORDER.map((category) => ({ label: TYPE_SECTION_LABELS[category] ?? category, cards: visible.filter((row) => cardTypeCategory(row.card) === category) })).filter((group) => group.cards.length > 0)
            : [{ label: null, cards: visible }];
          return <section key={title} className="rounded-2xl border border-white/10 bg-ink-900/40 p-5">
            <h2 className="font-display text-2xl text-stone-100">{title} <span className="text-lg text-stone-500">({rows.reduce((total, row) => total + row.quantity, 0)})</span></h2>
            {!visible.length && <p className="mt-4 text-sm text-stone-400">No matching cards.</p>}
            {groups.map((group) => <div key={group.label ?? "all"} className="mt-4">
              {group.label && <h3 className="mb-3 border-b border-white/10 pb-2 text-xs font-semibold uppercase tracking-wider text-stone-300">{group.label}</h3>}
              <ul className="grid grid-cols-[repeat(auto-fill,minmax(155px,1fr))] gap-3 sm:grid-cols-[repeat(auto-fill,minmax(175px,1fr))] xl:grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
                {group.cards.map((row) => <li key={row.id} className="overflow-hidden rounded-xl border border-white/10 bg-ink-950/40">
                  <GuestPrintingGallery name={row.card?.name ?? row.scryfall_id} printings={deckGuestPrintings(row)} commander={row.is_commander} />
                  <p className="px-3 pb-3 text-xs text-stone-500">{row.quantity} in deck · {row.card?.type_line}</p>
                </li>)}
              </ul>
            </div>)}
          </section>;
        })}
      </div>
    </>}
  </div>;
}
