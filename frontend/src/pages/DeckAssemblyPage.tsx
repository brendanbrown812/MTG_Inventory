import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  createDeck,
  fetchDeck,
  fetchDecks,
  fetchInventory,
  previewDeckText,
  updateDeckCardAssembly,
  updateDeckAssembly,
  type Deck,
  type DeckDetail,
  type DeckTextPreview,
  type InventoryLine,
} from "../api";
import {
  DeckPrintingModal,
  deckAllocationUnits,
} from "../components/DeckPrintingModal";
import { CONSTRUCTED_FORMATS, formatOptionLabel } from "../lib/formats";

type SourceMode = "existing" | "moxfield";
type SortMode = "deck" | "name" | "color" | "type";
type AssemblyStatus = "pending" | "grabbed" | "proxy";

type AssemblyCard = {
  key: string;
  deckCardId: number | null;
  allocationUnitIndex: number;
  allocatedScryfallId: string | null;
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
  status: AssemblyStatus;
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
    const units = deckAllocationUnits(entry);
    return units.map((unit, offset) => {
      const copyIndex = (requiredByOracle.get(oracleId) ?? 0) + 1;
      requiredByOracle.set(oracleId, copyIndex);
      const exactPrinting = entry.allocations.find(
        (allocation) => allocation.scryfall_id === unit.scryfallId,
      )?.printing;
      return {
        key: `deck-${deck.id}-${entry.id}-${offset + 1}`,
        deckCardId: entry.id,
        allocationUnitIndex: offset,
        allocatedScryfallId: unit.scryfallId,
        scryfallId: exactPrinting?.scryfall_id ?? entry.scryfall_id,
        oracleId,
        name: entry.card?.name ?? entry.scryfall_id,
        typeLine: entry.card?.type_line ?? null,
        colors: entry.card?.colors ?? "",
        imageUri: exactPrinting?.image_uri_normal ?? entry.card?.image_uri_normal ?? null,
        setCode: exactPrinting?.set_code ?? entry.card?.set_code ?? null,
        collectorNumber: exactPrinting?.collector_number ?? entry.card?.collector_number ?? null,
        foil: unit.foil ?? false,
        isCommander: entry.is_commander,
        copyIndex,
        copyTotal: totalByOracle.get(oracleId) ?? entry.quantity,
        ownedQuantity,
        available: copyIndex <= ownedQuantity,
        status: unit.status,
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
        deckCardId: null,
        allocationUnitIndex: offset,
        allocatedScryfallId: entry.scryfall_id,
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
        status: "pending",
      };
    })
  ));
}

function CardChecklist({
  title,
  cards,
  onSetStatus,
  onOpenCard,
  emptyText,
}: {
  title: string;
  cards: AssemblyCard[];
  onSetStatus: (card: AssemblyCard, status: AssemblyStatus) => void;
  onOpenCard?: (card: AssemblyCard) => void;
  emptyText: string;
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

  function scheduleHoverPreview(card: AssemblyCard, element: HTMLElement) {
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
          {emptyText}
        </div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(155px,1fr))] gap-3 sm:grid-cols-[repeat(auto-fill,minmax(175px,1fr))] xl:grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
          {cards.map((card) => (
            <article
              key={card.key}
              onMouseEnter={(event) => scheduleHoverPreview(card, event.currentTarget)}
              onMouseLeave={cancelHoverPreview}
              className={`group relative overflow-hidden rounded-xl border bg-ink-900/65 shadow-card transition hover:-translate-y-0.5 ${
                card.status === "grabbed" ? "border-emerald-500/25" : card.status === "proxy" ? "border-violet-500/30" : "border-white/10 hover:border-ember-400/40"
              }`}
            >
              <button
                type="button"
                onClick={() => {
                  cancelHoverPreview();
                  onOpenCard?.(card);
                }}
                disabled={!onOpenCard}
                className="relative block aspect-[5/7] w-full overflow-hidden bg-ink-800 text-left disabled:cursor-default"
                aria-label={onOpenCard ? `Choose printing for ${card.name}` : undefined}
              >
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
              </button>
              <div className="space-y-1 p-3">
                <button
                  type="button"
                  onClick={() => {
                    cancelHoverPreview();
                    onOpenCard?.(card);
                  }}
                  disabled={!onOpenCard}
                  className="line-clamp-2 text-left text-sm font-medium leading-tight text-stone-100 enabled:hover:text-ember-200 disabled:cursor-default"
                >
                  {card.name}
                </button>
                <p className="truncate text-[10px] text-stone-500">
                  {[card.setCode?.toUpperCase(), card.collectorNumber, card.foil ? "Foil" : null]
                    .filter(Boolean)
                  .join(" · ") || card.typeLine || "Card"}
                </p>
                <div className="grid grid-cols-3 gap-1 pt-2">
                  {(["pending", "grabbed", "proxy"] as const).map((status) => (
                    <button
                      key={status}
                      type="button"
                      onClick={() => {
                        cancelHoverPreview();
                        onSetStatus(card, status);
                      }}
                      disabled={card.status === status}
                      className={`rounded-md px-1 py-1 text-[9px] font-semibold uppercase tracking-wide transition ${
                        card.status === status
                          ? status === "grabbed"
                            ? "bg-emerald-500/25 text-emerald-100"
                            : status === "proxy"
                              ? "bg-violet-500/25 text-violet-100"
                              : "bg-amber-500/20 text-amber-100"
                          : "bg-white/5 text-stone-500 hover:bg-white/10 hover:text-stone-200"
                      }`}
                    >
                      {status === "pending" ? "Need" : status}
                    </button>
                  ))}
                </div>
              </div>
            </article>
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
  const [searchParams] = useSearchParams();
  const requestedDeckParam = searchParams.get("deck") ?? "";
  const [setupOpen, setSetupOpen] = useState(!requestedDeckParam);
  const [mode, setMode] = useState<SourceMode>(requestedDeckParam ? "existing" : "moxfield");
  const [sortMode, setSortMode] = useState<SortMode>(() => {
    const saved = localStorage.getItem("spellbinder:assembly:sort");
    return saved === "name" || saved === "color" || saved === "type" ? saved : "deck";
  });
  const [decks, setDecks] = useState<Deck[]>([]);
  const [inventory, setInventory] = useState<InventoryLine[]>([]);
  const [selectedDeckId, setSelectedDeckId] = useState(requestedDeckParam);
  const [activeDeck, setActiveDeck] = useState<DeckDetail | null>(null);
  const [cards, setCards] = useState<AssemblyCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [printingEditor, setPrintingEditor] = useState<{
    deckCardId: number;
    unitIndex: number;
  } | null>(null);
  const loadedDeepLinkRef = useRef<string | null>(null);
  const cardsRef = useRef<AssemblyCard[]>([]);
  const activeDeckRef = useRef<DeckDetail | null>(null);
  const statusQueuesRef = useRef(new Map<number, Promise<void>>());
  const statusMutationVersionRef = useRef(0);
  const canonicalRefreshTimerRef = useRef<number | null>(null);

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
    localStorage.setItem("spellbinder:assembly:sort", sortMode);
  }, [sortMode]);

  useEffect(() => {
    cardsRef.current = cards;
  }, [cards]);

  useEffect(() => {
    activeDeckRef.current = activeDeck;
  }, [activeDeck]);

  useEffect(() => () => {
    if (canonicalRefreshTimerRef.current !== null) {
      window.clearTimeout(canonicalRefreshTimerRef.current);
    }
  }, []);

  function scheduleCanonicalRefresh(deckId: number) {
    if (canonicalRefreshTimerRef.current !== null) {
      window.clearTimeout(canonicalRefreshTimerRef.current);
    }
    canonicalRefreshTimerRef.current = window.setTimeout(() => {
      canonicalRefreshTimerRef.current = null;
      if (statusQueuesRef.current.size > 0) {
        scheduleCanonicalRefresh(deckId);
        return;
      }
      const refreshVersion = statusMutationVersionRef.current;
      void Promise.all([fetchDeck(deckId), fetchInventory("", "name")])
        .then(([deck, inventoryRows]) => {
          if (activeDeckRef.current?.id !== deckId) return;
          if (
            statusQueuesRef.current.size > 0
            || statusMutationVersionRef.current !== refreshVersion
          ) {
            scheduleCanonicalRefresh(deckId);
            return;
          }
          const nextOwned = new Map<string, number>();
          for (const row of inventoryRows) {
            if (row.card) {
              nextOwned.set(row.card.oracle_id, (nextOwned.get(row.card.oracle_id) ?? 0) + row.quantity);
            }
          }
          const expanded = expandDeck(deck, nextOwned);
          activeDeckRef.current = deck;
          cardsRef.current = expanded;
          setActiveDeck(deck);
          setInventory(inventoryRows);
          setCards(expanded);
        })
        .catch((reason) => {
          setError(reason instanceof Error ? reason.message : "Could not refresh assembly data");
        });
    }, 900);
  }

  const loadDeckForAssembly = useCallback(async (deckId: number) => {
    setWorking(true);
    setError(null);
    try {
      const deck = await fetchDeck(deckId);
      const expanded = expandDeck(deck, ownedByOracle);
      setActiveDeck(deck);
      setCards(expanded);
      setSetupOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not open deck");
      setSetupOpen(true);
    } finally {
      setWorking(false);
    }
  }, [ownedByOracle]);

  useEffect(() => {
    if (loading || !requestedDeckParam || loadedDeepLinkRef.current === requestedDeckParam) return;
    const requestedDeckId = Number(requestedDeckParam);
    loadedDeepLinkRef.current = requestedDeckParam;
    if (!Number.isInteger(requestedDeckId) || requestedDeckId <= 0) {
      setSetupOpen(true);
      setError("The requested deck link is invalid.");
      return;
    }
    setMode("existing");
    setSelectedDeckId(requestedDeckParam);
    void loadDeckForAssembly(requestedDeckId);
  }, [loading, loadDeckForAssembly, requestedDeckParam]);

  function changeMode(nextMode: SourceMode) {
    setMode(nextMode);
    setActiveDeck(null);
    setCards([]);
    setError(null);
  }

  async function setCardStatus(card: AssemblyCard, status: AssemblyStatus) {
    if (card.status === status) return;
    if (!activeDeck || card.deckCardId === null) {
      const updated = cardsRef.current.map((item) => item.key === card.key ? { ...item, status } : item);
      cardsRef.current = updated;
      setCards(updated);
      return;
    }
    const deckId = activeDeck.id;
    const deckCardId = card.deckCardId;
    const previousStatus = cardsRef.current.find((item) => item.key === card.key)?.status ?? card.status;
    const optimisticCards = cardsRef.current.map((item) => (
      item.key === card.key ? { ...item, status } : item
    ));
    statusMutationVersionRef.current += 1;
    cardsRef.current = optimisticCards;
    setCards(optimisticCards);
    setError(null);

    const entryCards = optimisticCards.filter((item) => item.deckCardId === deckCardId);
    const grabbedQuantity = entryCards.filter((item) => item.status === "grabbed").length;
    const proxyQuantity = entryCards.filter((item) => item.status === "proxy").length;
    const previousRequest = statusQueuesRef.current.get(deckCardId) ?? Promise.resolve();
    const request = previousRequest.then(async () => {
      try {
        const updatedEntry = await updateDeckCardAssembly(deckId, deckCardId, {
          grabbed_quantity: grabbedQuantity,
          proxy_quantity: proxyQuantity,
        });
        if (activeDeckRef.current?.id === deckId) {
          const updatedDeck = {
            ...activeDeckRef.current,
            cards: activeDeckRef.current.cards.map((entry) => (
              entry.id === updatedEntry.id ? updatedEntry : entry
            )),
          };
          activeDeckRef.current = updatedDeck;
          setActiveDeck(updatedDeck);
          scheduleCanonicalRefresh(deckId);
        }
      } catch (reason) {
        const rolledBack = cardsRef.current.map((item) => (
          item.key === card.key && item.status === status
            ? { ...item, status: previousStatus }
            : item
        ));
        cardsRef.current = rolledBack;
        setCards(rolledBack);
        setError(reason instanceof Error ? reason.message : "Could not update assembly status");
        scheduleCanonicalRefresh(deckId);
      }
    });
    statusQueuesRef.current.set(deckCardId, request);
    void request.finally(() => {
      if (statusQueuesRef.current.get(deckCardId) === request) {
        statusQueuesRef.current.delete(deckCardId);
      }
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

      const counts = new Map<string, { grabbed: number; proxy: number }>();
      for (const card of cards) {
        const key = `${card.oracleId}:${card.isCommander}`;
        const value = counts.get(key) ?? { grabbed: 0, proxy: 0 };
        if (card.status === "grabbed") value.grabbed += 1;
        if (card.status === "proxy") value.proxy += 1;
        counts.set(key, value);
      }
      const assemblyUpdates = created.cards.map((entry) => {
        const value = counts.get(`${entry.card?.oracle_id ?? entry.scryfall_id}:${entry.is_commander}`) ?? { grabbed: 0, proxy: 0 };
        return { deck_card_id: entry.id, grabbed_quantity: value.grabbed, proxy_quantity: value.proxy };
      });
      const assembled = assemblyUpdates.some((entry) => entry.grabbed_quantity || entry.proxy_quantity)
        ? await updateDeckAssembly(created.id, assemblyUpdates)
        : created;
      const inventoryRows = await fetchInventory("", "name");
      const nextOwned = new Map<string, number>();
      for (const row of inventoryRows) {
        if (row.card) nextOwned.set(row.card.oracle_id, (nextOwned.get(row.card.oracle_id) ?? 0) + row.quantity);
      }
      const expanded = expandDeck(assembled, nextOwned);
      setDecks((previous) => [...previous, created].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedDeckId(String(created.id));
      setInventory(inventoryRows);
      setActiveDeck(assembled);
      setCards(expanded);
      setMode("existing");
      setPreview(null);
      setSetupOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create deck");
    } finally {
      setWorking(false);
    }
  }

  async function setAllStatuses(status: AssemblyStatus) {
    if (!activeDeck) {
      setCards((previous) => previous.map((card) => ({ ...card, status })));
      return;
    }
    setWorking(true);
    setError(null);
    try {
      const updated = await updateDeckAssembly(activeDeck.id, activeDeck.cards.map((entry) => ({
        deck_card_id: entry.id,
        grabbed_quantity: status === "grabbed" ? entry.quantity : 0,
        proxy_quantity: status === "proxy" ? entry.quantity : 0,
      })));
      const inventoryRows = await fetchInventory("", "name");
      const nextOwned = new Map<string, number>();
      for (const row of inventoryRows) {
        if (row.card) nextOwned.set(row.card.oracle_id, (nextOwned.get(row.card.oracle_id) ?? 0) + row.quantity);
      }
      setInventory(inventoryRows);
      setActiveDeck(updated);
      setCards(expandDeck(updated, nextOwned));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update assembly statuses");
    } finally {
      setWorking(false);
    }
  }

  const remainingCards = sortedCards(cards.filter((card) => card.status === "pending"), sortMode);
  const grabbedCards = sortedCards(cards.filter((card) => card.status === "grabbed"), sortMode);
  const proxyCards = sortedCards(cards.filter((card) => card.status === "proxy"), sortMode);
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
                ? "Open a saved deck or paste a Moxfield list, then mark each copy as needed, physically grabbed, or proxied. Saved deck locations are tracked in your collection."
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
                {grabbedCards.length} grabbed · {proxyCards.length} proxied · {remainingCards.length} still needed
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
              <button type="button" disabled={working} onClick={() => void setAllStatuses("grabbed")} className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs text-stone-300 hover:bg-ink-700 disabled:opacity-40">Mark all grabbed</button>
              <button type="button" disabled={working} onClick={() => void setAllStatuses("pending")} className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs text-stone-300 hover:bg-ink-700 disabled:opacity-40">Mark all needed</button>
            </div>
          </div>

          <CardChecklist title="Still to grab" cards={remainingCards} onSetStatus={(card, status) => void setCardStatus(card, status)} onOpenCard={activeDeck ? (card) => setPrintingEditor({ deckCardId: card.deckCardId!, unitIndex: card.allocationUnitIndex }) : undefined} emptyText="Every card is assigned or proxied." />
          <CardChecklist title="Grabbed already" cards={grabbedCards} onSetStatus={(card, status) => void setCardStatus(card, status)} onOpenCard={activeDeck ? (card) => setPrintingEditor({ deckCardId: card.deckCardId!, unitIndex: card.allocationUnitIndex }) : undefined} emptyText="Physical copies you grab will move here." />
          <CardChecklist title="Proxies" cards={proxyCards} onSetStatus={(card, status) => void setCardStatus(card, status)} onOpenCard={activeDeck ? (card) => setPrintingEditor({ deckCardId: card.deckCardId!, unitIndex: card.allocationUnitIndex }) : undefined} emptyText="Cards marked as proxies will appear here without changing your collection." />
        </div>
      )}
      {activeDeck && printingEditor && (() => {
        const deckCard = activeDeck.cards.find((entry) => entry.id === printingEditor.deckCardId);
        return deckCard ? (
          <DeckPrintingModal
            deckId={activeDeck.id}
            deckCard={deckCard}
            initialUnitIndex={printingEditor.unitIndex}
            onClose={() => setPrintingEditor(null)}
            onSaved={(updated) => {
              setActiveDeck(updated);
              setCards(expandDeck(updated, ownedByOracle));
              setPrintingEditor(null);
            }}
          />
        ) : null;
      })()}
    </div>
  );
}
