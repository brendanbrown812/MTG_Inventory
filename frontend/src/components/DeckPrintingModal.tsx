import { useEffect, useMemo, useState } from "react";
import {
  fetchGroupedInventory,
  replaceDeckCardAllocations,
  resolveCard,
  setDeckCommander,
  type DeckCard,
  type DeckDetail,
  type InventoryPrinting,
} from "../api";
import { AddCardPrintingPicker } from "./AddCardPrintingPicker";
import { PrintingCarousel } from "./PrintingCarousel";

export type DeckAllocationUnit = {
  status: "pending" | "grabbed" | "proxy";
  scryfallId: string | null;
  foil: boolean | null;
};

export function deckAllocationUnits(deckCard: DeckCard): DeckAllocationUnit[] {
  const units = deckCard.allocations.flatMap((allocation) => (
    Array.from({ length: allocation.quantity }, () => ({
      status: allocation.status,
      scryfallId: allocation.scryfall_id,
      foil: allocation.foil,
    }))
  ));
  if (units.length === deckCard.quantity) return units;

  return Array.from({ length: deckCard.quantity }, (_, index) => ({
    status: index < deckCard.grabbed_quantity
      ? "grabbed"
      : index < deckCard.grabbed_quantity + deckCard.proxy_quantity
        ? "proxy"
        : "pending",
    scryfallId: null,
    foil: null,
  }));
}

export function groupDeckAllocationUnits(units: DeckAllocationUnit[]) {
  const quantities = new Map<string, { status: DeckAllocationUnit["status"]; scryfall_id: string | null; foil: boolean | null; quantity: number }>();
  for (const unit of units) {
    const key = `${unit.status}:${unit.scryfallId ?? "any"}:${unit.foil === null ? "unknown" : unit.foil ? "foil" : "nonfoil"}`;
    const current = quantities.get(key);
    if (current) current.quantity += 1;
    else quantities.set(key, { status: unit.status, scryfall_id: unit.scryfallId, foil: unit.foil, quantity: 1 });
  }
  return [...quantities.values()];
}

function fallbackPrinting(deckCard: DeckCard, scryfallId: string): InventoryPrinting | null {
  const printing = deckCard.allocations.find((row) => row.scryfall_id === scryfallId)?.printing
    ?? (deckCard.card?.scryfall_id === scryfallId ? deckCard.card : null);
  if (!printing) return null;
  return {
    scryfall_id: printing.scryfall_id,
    set_code: printing.set_code,
    collector_number: printing.collector_number,
    rarity: printing.rarity,
    language: null,
    image_uri_normal: printing.image_uri_normal,
    total_quantity: 0,
    foil_quantity: 0,
    nonfoil_quantity: 0,
    card: printing,
    lines: [],
  };
}

function readableError(reason: unknown): string {
  if (!(reason instanceof Error)) return "Could not save printing";
  try {
    const parsed = JSON.parse(reason.message) as { detail?: unknown };
    return typeof parsed.detail === "string" ? parsed.detail : reason.message;
  } catch {
    return reason.message;
  }
}

export function DeckPrintingModal({
  deckId,
  deckCard,
  initialUnitIndex = 0,
  onClose,
  onSaved,
  onDraftSaved,
  onDraftCommanderSelected,
  onDraftCardAdded,
  allowCommanderSelection = false,
  currentCommanderName = null,
}: {
  deckId: number;
  deckCard: DeckCard;
  initialUnitIndex?: number;
  onClose: () => void;
  onSaved?: (deck: DeckDetail) => void;
  onDraftSaved?: (deckCard: DeckCard) => void;
  onDraftCommanderSelected?: () => void;
  onDraftCardAdded?: (card: NonNullable<DeckCard["card"]>, quantity: number, foil: boolean) => void;
  allowCommanderSelection?: boolean;
  currentCommanderName?: string | null;
}) {
  const units = useMemo(() => deckAllocationUnits(deckCard), [deckCard]);
  const [unitIndex, setUnitIndex] = useState(Math.min(initialUnitIndex, Math.max(0, units.length - 1)));
  const [printings, setPrintings] = useState<InventoryPrinting[]>([]);
  const [selectedScryfallId, setSelectedScryfallId] = useState<string | null>(
    units[Math.min(initialUnitIndex, Math.max(0, units.length - 1))]?.scryfallId ?? null,
  );
  const [selectedFoil, setSelectedFoil] = useState<boolean | null>(
    units[Math.min(initialUnitIndex, Math.max(0, units.length - 1))]?.foil ?? null,
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [commanderSaving, setCommanderSaving] = useState(false);
  const [addPrintingOpen, setAddPrintingOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchGroupedInventory(deckCard.card?.name ?? "")
      .then((groups) => {
        if (cancelled) return;
        const oracleId = deckCard.card?.oracle_id;
        const group = groups.find((row) => row.oracle_id === oracleId);
        const owned = group?.printings ?? [];
        const extraIds = new Set([
          deckCard.scryfall_id,
          ...deckCard.allocations.flatMap((allocation) => (
            allocation.scryfall_id ? [allocation.scryfall_id] : []
          )),
        ]);
        const extras = [...extraIds]
          .filter((id) => !owned.some((row) => row.scryfall_id === id))
          .map((id) => fallbackPrinting(deckCard, id))
          .filter((row): row is InventoryPrinting => row !== null);
        setPrintings([...owned, ...extras]);
      })
      .catch(() => {
        const selectedId = units[unitIndex]?.scryfallId;
        const fallback = selectedId ? fallbackPrinting(deckCard, selectedId) : null;
        setPrintings(fallback ? [fallback] : []);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [deckCard, unitIndex, units]);

  function chooseUnit(nextIndex: number) {
    setUnitIndex(nextIndex);
    setSelectedScryfallId(units[nextIndex]?.scryfallId ?? null);
    setSelectedFoil(units[nextIndex]?.foil ?? null);
    setError(null);
  }

  function choosePrinting(printing: InventoryPrinting) {
    setSelectedScryfallId(printing.scryfall_id);
    if (printing.foil_quantity > 0 && printing.nonfoil_quantity === 0) {
      setSelectedFoil(true);
    } else if (printing.nonfoil_quantity > 0) {
      setSelectedFoil(false);
    } else {
      setSelectedFoil(null);
    }
  }

  async function save() {
    const nextUnits = units.map((unit, index) => (
      index === unitIndex
        ? { ...unit, scryfallId: selectedScryfallId, foil: selectedScryfallId ? selectedFoil : null }
        : unit
    ));
    setSaving(true);
    setError(null);
    try {
      const grouped = groupDeckAllocationUnits(nextUnits);
      if (onDraftSaved) {
        onDraftSaved({
          ...deckCard,
          grabbed_quantity: grouped
            .filter((allocation) => allocation.status === "grabbed")
            .reduce((sum, allocation) => sum + allocation.quantity, 0),
          proxy_quantity: grouped
            .filter((allocation) => allocation.status === "proxy")
            .reduce((sum, allocation) => sum + allocation.quantity, 0),
          allocations: grouped.map((allocation, index) => ({
            id: -(index + 1),
            ...allocation,
            printing: allocation.scryfall_id
              ? printings.find((printing) => printing.scryfall_id === allocation.scryfall_id)?.card ?? null
              : null,
          })),
        });
        return;
      }
      const updated = await replaceDeckCardAllocations(
        deckId,
        deckCard.id,
        grouped,
      );
      onSaved?.(updated);
    } catch (reason) {
      setError(readableError(reason));
    } finally {
      setSaving(false);
    }
  }

  async function makeCommander() {
    if (
      currentCommanderName
      && !confirm(`Replace ${currentCommanderName} with ${cardName}?`)
    ) return;
    setCommanderSaving(true);
    setError(null);
    try {
      if (onDraftCommanderSelected) {
        onDraftCommanderSelected();
        return;
      }
      onSaved?.(await setDeckCommander(deckId, deckCard.id));
    } catch (reason) {
      setError(readableError(reason));
    } finally {
      setCommanderSaving(false);
    }
  }

  const selectedPrinting = printings.find((row) => row.scryfall_id === selectedScryfallId);
  const selectedUnit = units[unitIndex];
  const cardName = deckCard.card?.name ?? deckCard.scryfall_id;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={`${cardName} printing`}>
      <button type="button" className="absolute inset-0 cursor-default" onClick={onClose} aria-label="Close printing details" />
      <div className="relative flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-ink-900 shadow-2xl sm:flex-row">
        <div className="mx-auto w-48 shrink-0 self-start sm:mx-0 sm:w-64">
          {loading ? (
            <div className="flex aspect-[5/7] items-center justify-center bg-ink-800 text-sm text-stone-500">Loading printings…</div>
          ) : printings.length > 0 ? (
            <PrintingCarousel
              cardName={cardName}
              printings={printings}
              selectedScryfallId={selectedScryfallId}
              onSelect={choosePrinting}
            />
          ) : (
            <div className="flex aspect-[5/7] items-center justify-center bg-ink-800 p-5 text-center text-sm text-stone-500">
              No owned printing is available to select.
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="font-display text-2xl text-stone-100">{cardName}</h2>
              <p className="mt-1 text-xs text-stone-500">{deckCard.card?.type_line}</p>
              {deckCard.is_commander ? (
                <span className="mt-3 inline-flex rounded-lg bg-arcane-500/20 px-2.5 py-1 text-xs font-medium text-arcane-200 ring-1 ring-arcane-400/25">
                  Commander
                </span>
              ) : allowCommanderSelection ? (
                <button
                  type="button"
                  disabled={commanderSaving}
                  onClick={() => void makeCommander()}
                  className="mt-3 rounded-lg border border-arcane-400/25 px-3 py-1.5 text-xs font-medium text-arcane-200 transition hover:bg-arcane-500/15 disabled:opacity-40"
                >
                  {commanderSaving ? "Selecting…" : "Make commander"}
                </button>
              ) : null}
              {onDraftCardAdded && (
                <button
                  type="button"
                  onClick={() => setAddPrintingOpen(true)}
                  className="mt-3 rounded-lg border border-emerald-400/25 px-3 py-1.5 text-xs font-medium text-emerald-200 transition hover:bg-emerald-500/15"
                >
                  Add new card
                </button>
              )}
            </div>
            <button type="button" onClick={onClose} className="rounded-lg px-2 py-1 text-stone-500 hover:bg-white/5 hover:text-stone-200" aria-label="Close">✕</button>
          </div>

          {addPrintingOpen && onDraftCardAdded && (
            <div className="mt-5">
              <AddCardPrintingPicker
                sourceScryfallId={deckCard.scryfall_id}
                title={`Add another ${cardName}`}
                description="Choose the exact new physical copy. It will be added to this deck draft and your collection together when you save the deck."
                onCancel={() => setAddPrintingOpen(false)}
                onAdd={async (printing, quantity, foil) => {
                  const result = await resolveCard(printing.scryfall_id);
                  const card = result.matches[0];
                  if (!card) throw new Error("Could not load the selected printing");
                  onDraftCardAdded(card, quantity, foil);
                }}
              />
            </div>
          )}

          {!addPrintingOpen && <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <label className="text-xs font-medium uppercase tracking-wider text-stone-500">
              Deck copy
              <select value={unitIndex} onChange={(event) => chooseUnit(Number(event.target.value))} className="mt-1 block w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-sm normal-case tracking-normal text-stone-200">
                {units.map((unit, index) => (
                  <option key={index} value={index}>Copy {index + 1} · {unit.status === "pending" ? "Still to grab" : unit.status}</option>
                ))}
              </select>
            </label>
            <div className="rounded-xl border border-white/10 bg-ink-950/50 px-3 py-2">
              <p className="text-[10px] font-medium uppercase tracking-wider text-stone-500">Current location</p>
              <p className="mt-1 capitalize text-sm text-stone-200">
                {selectedUnit?.status === "pending" ? "Still to grab" : selectedUnit?.status}
                {selectedUnit?.foil === true ? " · foil" : selectedUnit?.foil === false ? " · nonfoil" : ""}
              </p>
            </div>
          </div>}

          {!addPrintingOpen && <div className="mt-5 rounded-xl border border-white/10 bg-ink-950/45 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-stone-500">Printing used in this deck</p>
                <p className="mt-1 text-sm text-stone-200">
                  {selectedScryfallId ? "Specific printing" : "Any printing"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelectedScryfallId(null);
                  setSelectedFoil(null);
                }}
                className={`rounded-lg px-3 py-2 text-xs font-medium transition ${selectedScryfallId === null ? "bg-ember-500/20 text-ember-100 ring-1 ring-ember-400/30" : "bg-white/5 text-stone-400 hover:bg-white/10"}`}
              >
                Use any printing
              </button>
            </div>
            {selectedPrinting ? (
              <div className="mt-3">
                <p className="text-xs text-stone-400">
                  You own {selectedPrinting.total_quantity} {selectedPrinting.total_quantity === 1 ? "copy" : "copies"} of this printing
                  {selectedPrinting.foil_quantity > 0 ? ` · ${selectedPrinting.foil_quantity} foil` : ""}.
                </p>
                {selectedPrinting.foil_quantity > 0 && selectedPrinting.nonfoil_quantity > 0 ? (
                  <div className="mt-3">
                    {selectedFoil === null && <p className="mb-2 text-xs text-amber-300">Choose which physical treatment this deck uses.</p>}
                    <div className="flex gap-2" aria-label="Card treatment">
                      <button type="button" onClick={() => setSelectedFoil(false)} className={`rounded-lg px-3 py-2 text-xs ${selectedFoil === false ? "bg-ember-500/20 text-ember-100 ring-1 ring-ember-400/30" : "bg-white/5 text-stone-400 hover:bg-white/10"}`}>
                        Nonfoil · {selectedPrinting.nonfoil_quantity}
                      </button>
                      <button type="button" onClick={() => setSelectedFoil(true)} className={`rounded-lg px-3 py-2 text-xs ${selectedFoil === true ? "bg-violet-500/20 text-violet-100 ring-1 ring-violet-400/30" : "bg-white/5 text-stone-400 hover:bg-white/10"}`}>
                        Foil · {selectedPrinting.foil_quantity}
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-stone-500">
                    {selectedPrinting.foil_quantity > 0 ? "Foil copy" : selectedPrinting.nonfoil_quantity > 0 ? "Nonfoil copy" : "Treatment not recorded"}
                  </p>
                )}
              </div>
            ) : selectedScryfallId ? (
              <p className="mt-3 text-xs text-violet-300">This exact printing is not currently in your physical collection.</p>
            ) : (
              <p className="mt-3 text-xs text-stone-500">Spellbinder may use any owned printing of this card for this deck copy.</p>
            )}
          </div>}

          {error && <div className="mt-4 rounded-xl border border-red-500/30 bg-red-950/40 px-3 py-2 text-xs text-red-200">{error}</div>}

          {!addPrintingOpen && <div className="mt-6 flex justify-end gap-3">
            <button type="button" onClick={onClose} className="rounded-xl border border-white/10 px-4 py-2 text-sm text-stone-400 hover:bg-white/5">Cancel</button>
            <button type="button" disabled={saving || loading || Boolean(selectedPrinting && selectedPrinting.foil_quantity > 0 && selectedPrinting.nonfoil_quantity > 0 && selectedFoil === null)} onClick={() => void save()} className="rounded-xl bg-emerald-500/20 px-4 py-2 text-sm font-medium text-emerald-100 ring-1 ring-emerald-400/30 disabled:opacity-40">
              {saving ? "Saving…" : "Save printing"}
            </button>
          </div>}
        </div>
      </div>
    </div>
  );
}
