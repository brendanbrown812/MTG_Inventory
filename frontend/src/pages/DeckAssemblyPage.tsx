import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createDeck,
  fetchDeck,
  fetchDecks,
  fetchInventory,
  previewDeckText,
  type Deck,
  type DeckDetail,
  type DeckTextPreview,
  type InventoryLine,
} from "../api";
import { CONSTRUCTED_FORMATS, formatOptionLabel } from "../lib/formats";

type SourceMode = "existing" | "moxfield";
type SortMode = "deck" | "name" | "color" | "type";

type AssemblyCard = {
  key: string;
  scryfallId: string;
  oracleId: string;
  name: string;
  typeLine: string | null;
  colors: string;
  imageUri: string | null;
  setCode: string | null;
  collectorNumber: string | null;
  foil: boolean;
  isCommander: boolean;
  copyIndex: number;
  copyTotal: number;
  ownedQuantity: number;
  available: boolean;
};

const MOXFIELD_EXAMPLE = `1 Splinter of the Shadows (PZA) 6
1 Arcane Signet (FIC) 334
1 Big Apple, 3 a.m. (TMC) 42
1 Black Market Connections (MSC) 155
1 Bloodline Bidding (ECL) 385 *F*
1 Bojuka Bog (CMD) 267
1 Bontu's Monument (DRC) 124
1 Bubbling Muck (PLST) UDS-54`;

const COLOR_ORDER = ["W", "U", "B", "R", "G"];
const TYPE_ORDER = [
  "Legendary Creature", "Creature", "Planeswalker", "Instant", "Sorcery",
  "Artifact", "Enchantment", "Battle", "Land", "Other",
];

function normalizedColors(raw: string): string[] {
  const values = raw.trim().startsWith("[")
    ? (() => {
        try { return JSON.parse(raw) as unknown; } catch { return []; }
      })()
    : raw.split(",");
  return Array.isArray(values)
    ? values.map(String).map((value) => value.trim().toUpperCase()).filter((value) => COLOR_ORDER.includes(value))
    : [];
}

function colorSortKey(card: AssemblyCard): number {
  const colors = normalizedColors(card.colors);
  if (colors.length === 1) return COLOR_ORDER.indexOf(colors[0] ?? "");
  if (colors.length > 1) return COLOR_ORDER.length;
  return COLOR_ORDER.length + 1;
}

function typeCategory(typeLine: string | null): string {
  const value = typeLine ?? "";
  if (value.includes("Legendary") && value.includes("Creature")) return "Legendary Creature";
  if (value.includes("Creature")) return "Creature";
  for (const category of TYPE_ORDER.slice(2, -1)) {
    if (value.includes(category)) return category;
  }
  return "Other";
}

function sortedCards(cards: AssemblyCard[], mode: SortMode): AssemblyCard[] {
  if (mode === "deck") return cards;
  return [...cards].sort((left, right) => {
    const primary = mode === "color"
      ? colorSortKey(left) - colorSortKey(right)
      : mode === "type"
        ? TYPE_ORDER.indexOf(typeCategory(left.typeLine)) - TYPE_ORDER.indexOf(typeCategory(right.typeLine))
        : 0;
    return primary || left.name.localeCompare(right.name) || left.copyIndex - right.copyIndex;
  });
}

function progressStorageKey(deckId: number): string {
  return `spellbinder:assembly:deck:${deckId}`;
}

function readProgress(key: string): Set<string> {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? "[]");
    return new Set(Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);
  } catch {
    return new Set();
  }
}

function expandDeck(deck: DeckDetail, ownedByOracle: Map<string, number>): AssemblyCard[] {
  const requiredByOracle = new Map<string, number>();
  const totalByOracle = new Map<string, number>();
  for (const entry of deck.cards) {
    const oracleId = entry.card?.oracle_id ?? entry.scryfall_id;
    totalByOracle.set(oracleId, (totalByOracle.get(oracleId) ?? 0) + entry.quantity);
  }
  return deck.cards.flatMap((entry) => {
    const oracleId = entry.card?.oracle_id ?? entry.scryfall_id;
    const ownedQuantity = ownedByOracle.get(oracleId) ?? 0;
    return Array.from({ length: entry.quantity }, (_, offset) => {
      const copyIndex = (requiredByOracle.get(oracleId) ?? 0) + 1;
      requiredByOracle.set(oracleId, copyIndex);
      return {
        key: `deck-${deck.id}-${entry.id}-${offset + 1}`,
        scryfallId: entry.scryfall_id,
        oracleId,
        name: entry.card?.name ?? entry.scryfall_id,
        typeLine: entry.card?.type_line ?? null,
        colors: entry.card?.colors ?? "",
        imageUri: entry.card?.image_uri_normal ?? null,
        setCode: null,
        collectorNumber: null,
        foil: false,
        isCommander: entry.is_commander,
        copyIndex,
        copyTotal: totalByOracle.get(oracleId) ?? entry.quantity,
        ownedQuantity,
        available: copyIndex <= ownedQuantity,
      };
    });
  });
}

function expandPreview(preview: DeckTextPreview): AssemblyCard[] {
  const requiredByOracle = new Map<string, number>();
  const totalByOracle = new Map<string, number>();
  for (const entry of preview.cards) {
    totalByOracle.set(entry.oracle_id, (totalByOracle.get(entry.oracle_id) ?? 0) + entry.quantity);
  }
  return preview.cards.flatMap((entry) => (
    Array.from({ length: entry.quantity }, (_, offset) => {
      const copyIndex = (requiredByOracle.get(entry.oracle_id) ?? 0) + 1;
      requiredByOracle.set(entry.oracle_id, copyIndex);
      return {
        key: `moxfield-${entry.line_index}-${entry.oracle_id}-${offset + 1}`,
        scryfallId: entry.scryfall_id,
        oracleId: entry.oracle_id,
        name: entry.name,
        typeLine: entry.type_line,
        colors: entry.colors,
        imageUri: entry.image_uri_normal,
        setCode: entry.set_code,
        collectorNumber: entry.collector_number,
        foil: entry.foil,
        isCommander: entry.is_commander,
        copyIndex,
        copyTotal: totalByOracle.get(entry.oracle_id) ?? entry.quantity,
        ownedQuantity: entry.owned_quantity,
        available: copyIndex <= entry.owned_quantity,
      };
    })
  ));
}

function CardChecklist({
  title,
  cards,
  checked,
  onToggle,
  grabbed = false,
}: {
  title: string;
  cards: AssemblyCard[];
  checked: Set<string>;
  onToggle: (key: string) => void;
  grabbed?: boolean;
}) {
  const hoverTimer = useRef<number | null>(null);
  const [hoverPreview, setHoverPreview] = useState<{
    card: AssemblyCard;
    left: number;
    top: number;
  } | null>(null);

  function cancelHoverPreview() {
    if (hoverTimer.current !== null) {
      window.clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
    setHoverPreview(null);
  }

  function scheduleHoverPreview(card: AssemblyCard, element: HTMLLabelElement) {
    cancelHoverPreview();
    if (!card.imageUri) return;
    const rect = element.getBoundingClientRect();
    const previewWidth = 320;
    const previewHeight = 448;
    let left = rect.right + 16;
    if (left + previewWidth > window.innerWidth - 12) {
      left = rect.left - previewWidth - 16;
    }
    left = Math.max(12, Math.min(left, window.innerWidth - previewWidth - 12));
    const top = Math.max(12, Math.min(rect.top, window.innerHeight - previewHeight - 12));
    hoverTimer.current = window.setTimeout(() => {
      setHoverPreview({ card, left, top });
      hoverTimer.current = null;
    }, 650);
  }

  useEffect(() => () => {
    if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
  }, []);

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-display text-2xl text-stone-100">{title}</h2>
        <span className="text-sm text-stone-500">{cards.length} card{cards.length === 1 ? "" : "s"}</span>
      </div>
      {cards.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-white/10 bg-ink-900/25 px-6 py-10 text-center text-sm text-stone-500">
          {grabbed ? "Checked cards will move down here." : "Everything in this list has been grabbed."}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
          {cards.map((card) => (
            <label
              key={card.key}
              onMouseEnter={(event) => scheduleHoverPreview(card, event.currentTarget)}
              onMouseLeave={cancelHoverPreview}
              className={`group relative cursor-pointer overflow-hidden rounded-xl border bg-ink-900/65 shadow-card transition hover:-translate-y-0.5 focus-within:ring-2 focus-within:ring-ember-400/60 ${
                grabbed ? "border-emerald-500/25 opacity-65 hover:opacity-100" : "border-white/10 hover:border-ember-400/40"
              }`}
            >
              <div className="relative aspect-[5/7] overflow-hidden bg-ink-800">
                {card.imageUri ? (
                  <img src={card.imageUri} alt={card.name} className="h-full w-full object-cover" loading="lazy" />
                ) : (
                  <div className="flex h-full items-center justify-center p-3 text-center text-xs text-stone-500">
                    {card.name}
                  </div>
                )}
                {(card.isCommander || card.copyTotal > 1) && (
                  <span className="absolute left-2 top-2 rounded-full bg-black/75 px-2 py-1 text-[10px] font-semibold text-stone-200 backdrop-blur-sm">
                    {card.isCommander ? "Commander" : `${card.copyIndex} of ${card.copyTotal}`}
                  </span>
                )}
                <span className={`absolute bottom-2 left-2 rounded-full px-2 py-1 text-[10px] font-semibold backdrop-blur-sm ${
                  card.available ? "bg-emerald-950/85 text-emerald-200" : "bg-red-950/90 text-red-200"
                }`}>
                  {card.available ? `Owned ${card.ownedQuantity}` : `Missing · owned ${card.ownedQuantity}`}
                </span>
                <input
                  type="checkbox"
                  checked={checked.has(card.key)}
                  onChange={() => {
                    cancelHoverPreview();
                    onToggle(card.key);
                  }}
                  aria-label={`${checked.has(card.key) ? "Return" : "Mark"} ${card.name} ${card.copyIndex} as grabbed`}
                  className="sr-only"
                />
              </div>
              <div className="space-y-1 p-3">
                <p className="line-clamp-2 text-sm font-medium leading-tight text-stone-100">{card.name}</p>
                <p className="truncate text-[10px] text-stone-500">
                  {[card.setCode?.toUpperCase(), card.collectorNumber, card.foil ? "Foil" : null]
                    .filter(Boolean)
                    .join(" · ") || card.typeLine || "Card"}
                </p>
              </div>
            </label>
          ))}
        </div>
      )}
      {hoverPreview && (
        <div
          data-testid="assembly-card-preview"
          className="pointer-events-none fixed z-[70] w-80 overflow-hidden rounded-2xl bg-black shadow-2xl ring-2 ring-white/20"
          style={{ left: hoverPreview.left, top: hoverPreview.top }}
          aria-hidden="true"
        >
          <img src={hoverPreview.card.imageUri ?? ""} alt="" className="aspect-[5/7] w-full object-cover" />
        </div>
      )}
    </section>
  );
}

export default function DeckAssemblyPage() {
  const [setupOpen, setSetupOpen] = useState(true);
  const [mode, setMode] = useState<SourceMode>("moxfield");
  const [sortMode, setSortMode] = useState<SortMode>(() => {
    const saved = localStorage.getItem("spellbinder:assembly:sort");
    return saved === "name" || saved === "color" || saved === "type" ? saved : "deck";
  });
  const [decks, setDecks] = useState<Deck[]>([]);
  const [inventory, setInventory] = useState<InventoryLine[]>([]);
  const [selectedDeckId, setSelectedDeckId] = useState("");
  const [activeDeck, setActiveDeck] = useState<DeckDetail | null>(null);
  const [cards, setCards] = useState<AssemblyCard[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [progressKey, setProgressKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [moxfieldText, setMoxfieldText] = useState("");
  const [preview, setPreview] = useState<DeckTextPreview | null>(null);
  const [deckName, setDeckName] = useState("");
  const [format, setFormat] = useState("commander");
  const [status, setStatus] = useState("building");
  const [notes, setNotes] = useState("");
  const [commanderOracleId, setCommanderOracleId] = useState("");

  const ownedByOracle = useMemo(() => {
    const result = new Map<string, number>();
    for (const row of inventory) {
      if (!row.card) continue;
      result.set(row.card.oracle_id, (result.get(row.card.oracle_id) ?? 0) + row.quantity);
    }
    return result;
  }, [inventory]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchDecks(), fetchInventory("", "name")])
      .then(([deckRows, inventoryRows]) => {
        if (cancelled) return;
        setDecks(deckRows);
        setInventory(inventoryRows);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load assembly data");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!progressKey) return;
    localStorage.setItem(progressKey, JSON.stringify([...checked]));
  }, [checked, progressKey]);

  useEffect(() => {
    localStorage.setItem("spellbinder:assembly:sort", sortMode);
  }, [sortMode]);

  const loadDeckForAssembly = useCallback(async (deckId: number) => {
    setWorking(true);
    setError(null);
    try {
      const deck = await fetchDeck(deckId);
      const expanded = expandDeck(deck, ownedByOracle);
      const key = progressStorageKey(deck.id);
      setActiveDeck(deck);
      setCards(expanded);
      setProgressKey(key);
      setChecked(readProgress(key));
      setSetupOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not open deck");
    } finally {
      setWorking(false);
    }
  }, [ownedByOracle]);

  function changeMode(nextMode: SourceMode) {
    setMode(nextMode);
    setActiveDeck(null);
    setCards([]);
    setChecked(new Set());
    setProgressKey(null);
    setError(null);
  }

  function toggleCard(key: string) {
    setChecked((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function previewMoxfield() {
    if (!moxfieldText.trim()) return;
    setWorking(true);
    setError(null);
    try {
      const result = await previewDeckText(moxfieldText);
      setPreview(result);
      setCards(expandPreview(result));
      setChecked(new Set());
      setProgressKey(null);
      setActiveDeck(null);
      setCommanderOracleId(result.cards.find((card) => card.is_commander)?.oracle_id ?? "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not resolve Moxfield list");
    } finally {
      setWorking(false);
    }
  }

  async function createPreviewedDeck() {
    if (!preview || !deckName.trim() || preview.row_errors.length > 0) return;
    setWorking(true);
    setError(null);
    try {
      const created = await createDeck({
        name: deckName.trim(),
        format,
        status,
        notes: notes.trim() || null,
        commander_scryfall_id:
          preview.cards.find((card) => card.oracle_id === commanderOracleId)?.scryfall_id ?? null,
        cards: preview.cards.map((card) => ({
          scryfall_id: card.scryfall_id,
          quantity: card.quantity,
          is_commander: Boolean(commanderOracleId) && card.oracle_id === commanderOracleId,
        })),
      });

      const checkedCounts = new Map<string, number>();
      for (const card of cards) {
        if (checked.has(card.key)) {
          checkedCounts.set(card.oracleId, (checkedCounts.get(card.oracleId) ?? 0) + 1);
        }
      }
      const expanded = expandDeck(created, ownedByOracle);
      const migratedChecked = new Set<string>();
      for (const card of expanded) {
        const remaining = checkedCounts.get(card.oracleId) ?? 0;
        if (remaining > 0) {
          migratedChecked.add(card.key);
          checkedCounts.set(card.oracleId, remaining - 1);
        }
      }
      const key = progressStorageKey(created.id);
      localStorage.setItem(key, JSON.stringify([...migratedChecked]));
      setDecks((previous) => [...previous, created].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedDeckId(String(created.id));
      setActiveDeck(created);
      setCards(expanded);
      setChecked(migratedChecked);
      setProgressKey(key);
      setMode("existing");
      setPreview(null);
      setSetupOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create deck");
    } finally {
      setWorking(false);
    }
  }

  const remainingCards = sortedCards(cards.filter((card) => !checked.has(card.key)), sortMode);
  const grabbedCards = sortedCards(cards.filter((card) => checked.has(card.key)), sortMode);
  const missingCount = cards.filter((card) => !card.available).length;
  const uniqueCommanderChoices = preview
    ? [...new Map(preview.cards.map((card) => [card.oracle_id, card])).values()]
    : [];

  return (
    <div className="space-y-8">
      <section className="rounded-2xl border border-white/10 bg-ink-900/35 p-5 shadow-card sm:p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl font-semibold text-stone-100">Deck assembly</h1>
            <p className="mt-2 max-w-2xl text-stone-400">
              {setupOpen
                ? "Open a saved deck or paste a Moxfield list, then check off each physical card as you pull it from bulk. Progress for saved decks stays on this browser."
                : `${activeDeck?.name ?? "Assembly list"} · setup controls hidden`}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setSetupOpen((open) => !open)}
            aria-expanded={setupOpen}
            className="shrink-0 rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs text-stone-300 transition hover:bg-ink-700"
          >
            {setupOpen ? "Hide setup" : "Show setup"}
          </button>
        </div>

        {setupOpen && <div className="mt-6 space-y-6">
        <div className="inline-flex rounded-xl border border-white/10 bg-ink-900/60 p-1">
        {(["existing", "moxfield"] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => changeMode(value)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
              mode === value ? "bg-ember-500/20 text-ember-100 ring-1 ring-ember-400/30" : "text-stone-400 hover:text-stone-200"
            }`}
          >
            {value === "existing" ? "Open existing deck" : "Paste from Moxfield"}
          </button>
        ))}
        </div>

        {mode === "existing" ? (
        <section className="rounded-2xl border border-white/10 bg-ink-900/40 p-6 shadow-card">
          <h2 className="font-display text-xl text-stone-100">Choose a deck</h2>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row">
            <select
              value={selectedDeckId}
              onChange={(event) => setSelectedDeckId(event.target.value)}
              className="min-w-0 flex-1 rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm text-stone-200"
            >
              <option value="">Select a saved deck…</option>
              {decks.map((deck) => (
                <option key={deck.id} value={deck.id}>{deck.name} · {formatOptionLabel(deck.format)}</option>
              ))}
            </select>
            <button
              type="button"
              disabled={working || !selectedDeckId}
              onClick={() => void loadDeckForAssembly(Number(selectedDeckId))}
              className="rounded-xl bg-stone-100 px-6 py-2.5 text-sm font-semibold text-ink-950 disabled:opacity-40"
            >
              {working ? "Opening…" : "Open deck"}
            </button>
          </div>
          {!loading && decks.length === 0 && <p className="mt-3 text-sm text-stone-500">No saved decks yet.</p>}
        </section>
      ) : (
        <section className="space-y-5 rounded-2xl border border-white/10 bg-ink-900/40 p-6 shadow-card">
          <div>
            <h2 className="font-display text-xl text-stone-100">Paste a Moxfield card list</h2>
            <p className="mt-2 text-sm text-stone-400">
              Printing hints and <span className="font-mono text-stone-300">*F*</span> foil markers are supported.
              Put commander cards after the final blank line, or choose one before creating the deck.
            </p>
          </div>
          <textarea
            value={moxfieldText}
            onChange={(event) => {
              setMoxfieldText(event.target.value);
              setPreview(null);
              setCards([]);
            }}
            rows={10}
            spellCheck={false}
            placeholder={MOXFIELD_EXAMPLE}
            className="w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-3 font-mono text-sm text-stone-200 outline-none focus:ring-2 focus:ring-ember-400/30"
          />
          <button
            type="button"
            disabled={working || !moxfieldText.trim()}
            onClick={() => void previewMoxfield()}
            className="rounded-xl bg-ember-500/20 px-5 py-2.5 text-sm font-medium text-ember-100 ring-1 ring-ember-400/30 disabled:opacity-40"
          >
            {working ? "Resolving cards…" : "Preview assembly list"}
          </button>

          {preview && (
            <div className="space-y-4 border-t border-white/5 pt-5">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <div className="sm:col-span-2">
                  <label className="text-xs uppercase tracking-wider text-stone-500">Deck name</label>
                  <input value={deckName} onChange={(event) => setDeckName(event.target.value)} maxLength={200} placeholder="My new deck…" className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm" />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-wider text-stone-500">Format</label>
                  <select value={format} onChange={(event) => setFormat(event.target.value)} className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm">
                    {CONSTRUCTED_FORMATS.map((value) => <option key={value} value={value}>{formatOptionLabel(value)}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs uppercase tracking-wider text-stone-500">Status</label>
                  <select value={status} onChange={(event) => setStatus(event.target.value)} className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm">
                    <option value="building">Building</option>
                    <option value="complete">Complete</option>
                  </select>
                </div>
                <div className="sm:col-span-2">
                  <label className="text-xs uppercase tracking-wider text-stone-500">Commander</label>
                  <select value={commanderOracleId} onChange={(event) => setCommanderOracleId(event.target.value)} className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm">
                    <option value="">No commander selected</option>
                    {uniqueCommanderChoices.map((card) => <option key={card.oracle_id} value={card.oracle_id}>{card.name}</option>)}
                  </select>
                </div>
                <div className="sm:col-span-2">
                  <label className="text-xs uppercase tracking-wider text-stone-500">Notes</label>
                  <input value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={50_000} placeholder="Optional deck notes…" className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm" />
                </div>
              </div>
              {preview.row_errors.length > 0 && (
                <div className="rounded-xl border border-red-500/30 bg-red-950/35 p-4">
                  <p className="text-sm font-medium text-red-200">Fix these lines before creating the deck:</p>
                  {preview.row_errors.map((item) => <p key={`${item.row_index}-${item.error}`} className="mt-1 text-xs text-red-300">Line {item.row_index + 1}: {item.error}</p>)}
                </div>
              )}
              <button
                type="button"
                disabled={working || !deckName.trim() || preview.cards.length === 0 || preview.row_errors.length > 0}
                onClick={() => void createPreviewedDeck()}
                className="rounded-xl bg-emerald-500/20 px-5 py-2.5 text-sm font-medium text-emerald-100 ring-1 ring-emerald-400/30 disabled:opacity-40"
              >
                {working ? "Creating…" : `Create deck with ${preview.total_quantity} card${preview.total_quantity === 1 ? "" : "s"}`}
              </button>
            </div>
          )}
        </section>
        )}
        </div>}
      </section>

      {error && <div className="rounded-xl border border-red-500/30 bg-red-950/40 px-4 py-3 text-sm text-red-200">{error}</div>}

      {cards.length > 0 && (
        <div className="space-y-10">
          <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-ink-900/45 px-5 py-4">
            <div>
              <p className="font-medium text-stone-200">{activeDeck?.name ?? "Moxfield preview"}</p>
              <p className="text-sm text-stone-500">
                {grabbedCards.length} of {cards.length} grabbed
                {missingCount > 0 ? ` · ${missingCount} not currently in collection` : " · collection has every card"}
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <label className="text-[10px] font-medium uppercase tracking-wider text-stone-500">
                Sort cards
                <select
                  value={sortMode}
                  onChange={(event) => setSortMode(event.target.value as SortMode)}
                  className="mt-1 block rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs normal-case tracking-normal text-stone-300"
                >
                  <option value="deck">Deck order</option>
                  <option value="name">Name</option>
                  <option value="color">Color · WUBRG</option>
                  <option value="type">Card type</option>
                </select>
              </label>
              <button type="button" onClick={() => setChecked(new Set(cards.map((card) => card.key)))} className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs text-stone-300 hover:bg-ink-700">Mark all grabbed</button>
              <button type="button" onClick={() => setChecked(new Set())} className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs text-stone-300 hover:bg-ink-700">Reset checks</button>
            </div>
          </div>

          <CardChecklist title="Still to grab" cards={remainingCards} checked={checked} onToggle={toggleCard} />
          <CardChecklist title="Grabbed already" cards={grabbedCards} checked={checked} onToggle={toggleCard} grabbed />
        </div>
      )}
    </div>
  );
}
