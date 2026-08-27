import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  clearInventory,
  changeInventoryLinePrinting,
  changeInventoryPrinting,
  deleteInventoryLine,
  fetchCardLocations,
  fetchCardMatches,
  fetchGroupedInventory,
  updateInventoryLineQuantity,
  type CardLocationSummary,
  type DeckMatch,
  type InventoryOracleGroup,
  type InventoryLine,
  type InventoryPrinting,
} from "../api";
import { PrintingCarousel } from "../components/PrintingCarousel";
import { PrintChangePicker } from "../components/PrintChangePicker";
import { AddInventoryCardModal } from "../components/AddInventoryCardModal";

const CMC_VALUES = ["0", "1", "2", "3", "4", "5", "6+"] as const;

const COLORS = [
  { value: "W", label: "White" },
  { value: "U", label: "Blue" },
  { value: "B", label: "Black" },
  { value: "R", label: "Red" },
  { value: "G", label: "Green" },
  { value: "C", label: "Colorless" },
] as const;

const TYPES = [
  "Legendary Creature", "Creature", "Instant", "Sorcery", "Artifact",
  "Enchantment", "Planeswalker", "Land", "Battle",
] as const;

const PRINTING_SELECTION_KEY = "spellbinder:collection:selected-printings";

type PrintChangeTarget =
  | { kind: "printing"; sourceScryfallId: string }
  | { kind: "line"; sourceScryfallId: string; line: InventoryLine };

function readPrintingSelections(): Record<string, string> {
  try {
    const value = JSON.parse(localStorage.getItem(PRINTING_SELECTION_KEY) ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
    );
  } catch {
    return {};
  }
}

function FilterChip({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onChange}
      className={[
        "rounded-lg border px-3 py-1.5 text-sm font-medium transition",
        checked
          ? "border-ember-400/50 bg-ember-500/15 text-ember-100"
          : "border-white/10 bg-ink-950/50 text-stone-400 hover:border-white/20 hover:text-stone-200",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

function toggleSet(prev: Set<string>, value: string): Set<string> {
  const next = new Set(prev);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

export default function InventoryPage() {
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [sort, setSort] = useState("name");
  const [groups, setGroups] = useState<InventoryOracleGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const [addCardOpen, setAddCardOpen] = useState(false);

  // Filter state
  const [filterOpen, setFilterOpen] = useState(false);
  const [cmcFilter, setCmcFilter] = useState<Set<string>>(new Set());
  const [colorFilter, setColorFilter] = useState<Set<string>>(new Set());
  const [colorMode, setColorMode] = useState<"any" | "exact">("any");
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());

  // Card detail modal state
  const [selected, setSelected] = useState<InventoryOracleGroup | null>(null);
  const [selectedPrintingByOracle, setSelectedPrintingByOracle] = useState<Record<string, string>>(
    readPrintingSelections,
  );
  const [locations, setLocations] = useState<CardLocationSummary | null>(null);
  const [membershipLoading, setMembershipLoading] = useState(false);
  const [matches, setMatches] = useState<DeckMatch[] | null>(null);
  const [matchLoading, setMatchLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [updatingQuantityId, setUpdatingQuantityId] = useState<number | null>(null);
  const [quantityDrafts, setQuantityDrafts] = useState<Record<number, string>>({});
  const [inventoryEditError, setInventoryEditError] = useState<string | null>(null);
  const [printChangeTarget, setPrintChangeTarget] = useState<PrintChangeTarget | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 320);
    return () => clearTimeout(t);
  }, [q]);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setGroups(await fetchGroupedInventory(debouncedQ));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [debouncedQ]);

  useEffect(() => {
    void load();
  }, [load]);

  // Client-side filter applied on top of the server-sorted/searched rows
  const filteredGroups = groups.filter((group) => {
    const c = group.card;

    if (cmcFilter.size > 0) {
      const bucket = Math.floor(c?.cmc ?? 0) >= 6 ? "6+" : String(Math.floor(c?.cmc ?? 0));
      if (!cmcFilter.has(bucket)) return false;
    }

    if (colorFilter.size > 0) {
      const ci = (c?.color_identity ?? "")
        .split(",")
        .map((x) => x.trim().toUpperCase())
        .filter(Boolean);
      const isColorless = ci.length === 0;
      if (isColorless) {
        if (!colorFilter.has("C")) return false;
      } else if (colorMode === "any") {
        // within: every color on the card must be in the selection (card can have fewer)
        if (!ci.every((color) => colorFilter.has(color))) return false;
      } else {
        // exact: card's colors must match the selection exactly — no more, no fewer
        const selectedColors = new Set([...colorFilter].filter((x) => x !== "C"));
        if (ci.length !== selectedColors.size || !ci.every((color) => selectedColors.has(color))) return false;
      }
    }

    if (typeFilter.size > 0) {
      const tl = (c?.type_line ?? "").toLowerCase();
      if (![...typeFilter].some((t) => tl.includes(t.toLowerCase()))) return false;
    }

    return true;
  });

  const activeFilterCount = cmcFilter.size + colorFilter.size + typeFilter.size;

  function clearFilters() {
    setCmcFilter(new Set());
    setColorFilter(new Set());
    setColorMode("any");
    setTypeFilter(new Set());
  }

  function selectedPrinting(group: InventoryOracleGroup): InventoryPrinting | undefined {
    const savedId = selectedPrintingByOracle[group.oracle_id];
    return group.printings.find((printing) => printing.scryfall_id === savedId) ?? group.printings[0];
  }

  const visibleGroups = [...filteredGroups].sort((left, right) => {
    if (sort === "quantity") {
      return right.total_quantity - left.total_quantity || left.card.name.localeCompare(right.card.name);
    }
    if (sort === "set") {
      const leftPrinting = selectedPrinting(left);
      const rightPrinting = selectedPrinting(right);
      const leftKey = `${leftPrinting?.set_code ?? ""}:${leftPrinting?.collector_number ?? ""}`;
      const rightKey = `${rightPrinting?.set_code ?? ""}:${rightPrinting?.collector_number ?? ""}`;
      return leftKey.localeCompare(rightKey) || left.card.name.localeCompare(right.card.name);
    }
    return left.card.name.localeCompare(right.card.name);
  });

  async function openCard(group: InventoryOracleGroup) {
    setSelected(group);
    setMatches(null);
    setLocations(null);
    setMembershipLoading(true);
    try {
      const printing = selectedPrinting(group);
      setLocations(printing ? await fetchCardLocations(printing.scryfall_id) : null);
    } catch {
      setLocations(null);
    } finally {
      setMembershipLoading(false);
    }
  }

  async function choosePrinting(group: InventoryOracleGroup, printing: InventoryPrinting) {
    setSelectedPrintingByOracle((previous) => {
      const next = { ...previous, [group.oracle_id]: printing.scryfall_id };
      localStorage.setItem(PRINTING_SELECTION_KEY, JSON.stringify(next));
      return next;
    });
    setPrintChangeTarget(null);
    setMembershipLoading(true);
    try {
      setLocations(await fetchCardLocations(printing.scryfall_id));
    } catch {
      setLocations(null);
    } finally {
      setMembershipLoading(false);
    }
  }

  function closeModal() {
    setSelected(null);
    setMatches(null);
    setLocations(null);
    setPrintChangeTarget(null);
    setQuantityDrafts({});
    setInventoryEditError(null);
  }

  async function applyPrintChange(targetScryfallId: string, quantity?: number) {
    if (!selected || !printChangeTarget) return;
    if (printChangeTarget.kind === "line") {
      await changeInventoryLinePrinting(
        printChangeTarget.line.id,
        targetScryfallId,
        quantity,
      );
    } else {
      await changeInventoryPrinting(printChangeTarget.sourceScryfallId, targetScryfallId);
    }

    const [pageGroups, selectedGroups] = await Promise.all([
      fetchGroupedInventory(debouncedQ),
      fetchGroupedInventory(selected.card.name),
    ]);
    const refreshed = selectedGroups.find((group) => group.oracle_id === selected.oracle_id);
    setGroups(pageGroups);
    if (!refreshed) {
      closeModal();
      return;
    }

    const oldStillExists = refreshed.printings.some(
      (printing) => printing.scryfall_id === printChangeTarget.sourceScryfallId,
    );
    const nextSelectedId = oldStillExists
      ? selectedPrintingByOracle[selected.oracle_id] ?? printChangeTarget.sourceScryfallId
      : targetScryfallId;
    setSelectedPrintingByOracle((previous) => {
      const next = { ...previous, [selected.oracle_id]: nextSelectedId };
      localStorage.setItem(PRINTING_SELECTION_KEY, JSON.stringify(next));
      return next;
    });
    setSelected(refreshed);
    setMatches(null);
    setPrintChangeTarget(null);
    setLocations(await fetchCardLocations(nextSelectedId));
  }

  async function runDeckFit() {
    const printing = selected ? selectedPrinting(selected) : undefined;
    if (!printing) return;
    setMatchLoading(true);
    try {
      setMatches(await fetchCardMatches(printing.scryfall_id));
    } catch {
      setMatches([]);
    } finally {
      setMatchLoading(false);
    }
  }

  async function removeInventoryLine(id: number) {
    setDeletingId(id);
    setInventoryEditError(null);
    try {
      await deleteInventoryLine(id);
      closeModal();
      await load();
    } catch (e) {
      setInventoryEditError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  }

  async function saveInventoryQuantity(line: InventoryLine) {
    if (!selected || !currentPrinting) return;
    const rawQuantity = quantityDrafts[line.id] ?? String(line.quantity);
    const quantity = Number(rawQuantity);
    if (!Number.isInteger(quantity) || quantity < 1) {
      setInventoryEditError("Quantity must be a whole number of at least 1.");
      return;
    }
    setUpdatingQuantityId(line.id);
    setInventoryEditError(null);
    try {
      await updateInventoryLineQuantity(line.id, quantity);
      const selectedPrintingId = currentPrinting.scryfall_id;
      const [pageGroups, selectedGroups, nextLocations] = await Promise.all([
        fetchGroupedInventory(debouncedQ),
        fetchGroupedInventory(selected.card.name),
        fetchCardLocations(selectedPrintingId),
      ]);
      const refreshed = selectedGroups.find(
        (group) => group.oracle_id === selected.oracle_id,
      );
      setGroups(pageGroups);
      if (refreshed) setSelected(refreshed);
      setLocations(nextLocations);
      setQuantityDrafts((previous) => {
        const next = { ...previous };
        delete next[line.id];
        return next;
      });
    } catch (e) {
      setInventoryEditError(
        e instanceof Error ? e.message : "Could not update inventory quantity",
      );
    } finally {
      setUpdatingQuantityId(null);
    }
  }

  async function clearAll() {
    if (!confirm("Remove every row from your collection? Deck lists are not changed. This cannot be undone.")) return;
    setErr(null);
    setClearing(true);
    try {
      await clearInventory();
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Clear failed");
    } finally {
      setClearing(false);
    }
  }

  const selectedCard = selected?.card;
  const currentPrinting = selected ? selectedPrinting(selected) : undefined;
  const correctionPrinting = selected && printChangeTarget
    ? selected.printings.find((printing) => printing.scryfall_id === printChangeTarget.sourceScryfallId)
    : undefined;
  const correctionLines = printChangeTarget?.kind === "line"
    ? [printChangeTarget.line]
    : correctionPrinting?.lines ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-stone-100">Collection</h1>
          <p className="mt-2 text-stone-400">Click any card to view details and deck suggestions.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => setAddCardOpen(true)}
            className="rounded-xl border border-emerald-400/30 bg-emerald-500/10 px-4 py-2.5 text-sm font-medium text-emerald-200 transition hover:bg-emerald-500/20"
          >
            Add New Card
          </button>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search card name…"
            className="w-full min-w-[200px] flex-1 rounded-xl border border-white/10 bg-ink-900/80 px-4 py-2.5 text-sm text-stone-100 outline-none ring-ember-400/40 placeholder:text-stone-600 focus:ring-2 sm:max-w-xs"
          />
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="rounded-xl border border-white/10 bg-ink-900/80 px-4 py-2.5 text-sm text-stone-200 outline-none focus:ring-2 focus:ring-arcane-400/40"
          >
            <option value="name">Sort: Name</option>
            <option value="quantity">Sort: Quantity</option>
            <option value="set">Sort: Set / number</option>
          </select>
          <button
            type="button"
            onClick={() => setFilterOpen(true)}
            className="relative rounded-xl border border-white/10 bg-ink-900/80 px-4 py-2.5 text-sm text-stone-200 outline-none transition hover:bg-ink-800 focus:ring-2 focus:ring-arcane-400/40"
          >
            Filters
            {activeFilterCount > 0 && (
              <span className="ml-2 inline-flex h-4 w-4 items-center justify-center rounded-full bg-ember-500 text-[10px] font-bold text-white">
                {activeFilterCount}
              </span>
            )}
          </button>
          <button
            type="button"
            disabled={clearing}
            onClick={() => void clearAll()}
            className="rounded-xl border border-red-500/40 bg-red-950/30 px-4 py-2.5 text-sm font-medium text-red-200 transition hover:bg-red-950/50 disabled:opacity-40"
          >
            {clearing ? "Clearing…" : "Clear collection"}
          </button>
        </div>
      </div>

      {err && (
        <div className="rounded-xl border border-red-500/30 bg-red-950/40 px-4 py-3 text-sm text-red-200">{err}</div>
      )}

      {addCardOpen && (
        <AddInventoryCardModal
          onClose={() => setAddCardOpen(false)}
          onAdded={load}
        />
      )}

      {!loading && groups.length > 0 && (
        <p className="text-sm text-stone-400">
          <span className="font-medium text-stone-200">{visibleGroups.reduce((sum, group) => sum + group.total_quantity, 0)}</span> physical cards
          &nbsp;·&nbsp;
          <span className="font-medium text-stone-200">{visibleGroups.length}</span> unique cards
          &nbsp;·&nbsp;
          <span className="font-medium text-stone-200">{visibleGroups.reduce((sum, group) => sum + group.printing_count, 0)}</span> printings
          {activeFilterCount > 0 && (
            <span className="text-stone-500">
              {" "}(filtered from {groups.length} cards)
              {" · "}
              <button
                type="button"
                onClick={clearFilters}
                className="text-ember-400 hover:underline"
              >
                Clear filters
              </button>
            </span>
          )}
        </p>
      )}

      {/* Card grid */}
      {loading ? (
        <p className="py-20 text-center text-stone-500">Loading collection…</p>
      ) : groups.length === 0 ? (
        <p className="py-20 text-center text-stone-500">
          No cards yet.{" "}
          <Link className="text-ember-400 underline-offset-2 hover:underline" to="/import">
            Import your ManaBox CSV
          </Link>
          .
        </p>
      ) : visibleGroups.length === 0 ? (
        <p className="py-20 text-center text-stone-500">
          No cards match your filters.{" "}
          <button type="button" onClick={clearFilters} className="text-ember-400 hover:underline">
            Clear filters
          </button>
        </p>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(155px,1fr))] gap-3 sm:grid-cols-[repeat(auto-fill,minmax(175px,1fr))] xl:grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
          {visibleGroups.map((group) => {
            const c = group.card;
            const printing = selectedPrinting(group);
            return (
              <button
                key={group.oracle_id}
                type="button"
                onClick={() => void openCard(group)}
                className="group relative aspect-[5/7] w-full overflow-hidden rounded-xl ring-1 ring-white/10 transition duration-150 hover:scale-[1.03] hover:ring-ember-400/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-ember-400"
              >
                {printing?.image_uri_normal ? (
                  <img
                    src={printing.image_uri_normal}
                    alt={c.name}
                    className="h-full w-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center bg-ink-800 p-2">
                    <span className="text-center text-[11px] leading-tight text-stone-400">
                      {c.name}
                    </span>
                  </div>
                )}
                <div className="absolute bottom-1.5 right-1.5 rounded-full bg-black/75 px-2 py-0.5 font-mono text-xs font-semibold text-stone-200 ring-1 ring-white/10 backdrop-blur-sm">
                  ×{group.total_quantity}
                </div>
                {group.printing_count > 1 && (
                  <div className="absolute bottom-1.5 left-1.5 rounded-full bg-black/75 px-2 py-0.5 text-[10px] font-semibold text-stone-300 ring-1 ring-white/10 backdrop-blur-sm">
                    {group.printing_count} prints
                  </div>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* Filter modal */}
      {filterOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <button
            type="button"
            className="absolute inset-0 cursor-default"
            aria-label="Close filters"
            onClick={() => setFilterOpen(false)}
          />
          <div className="relative w-full max-w-md rounded-2xl border border-white/10 bg-ink-900 p-6 shadow-card">
            <div className="flex items-center justify-between">
              <h2 className="font-display text-xl font-semibold text-stone-100">Filters</h2>
              <div className="flex items-center gap-4">
                {activeFilterCount > 0 && (
                  <button
                    type="button"
                    onClick={clearFilters}
                    className="text-xs text-stone-500 transition hover:text-stone-300"
                  >
                    Clear all
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setFilterOpen(false)}
                  className="rounded-lg px-2 py-1 text-stone-400 transition hover:bg-white/5 hover:text-stone-200"
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="mt-6 space-y-6">
              {/* Mana Value */}
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-stone-500">Mana Value</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {CMC_VALUES.map((v) => (
                    <FilterChip
                      key={v}
                      label={v}
                      checked={cmcFilter.has(v)}
                      onChange={() => setCmcFilter((p) => toggleSet(p, v))}
                    />
                  ))}
                </div>
              </div>

              {/* Color */}
              <div>
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium uppercase tracking-wider text-stone-500">Color</p>
                  <div className="flex overflow-hidden rounded-lg border border-white/10 text-xs">
                    {(["any", "exact"] as const).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        onClick={() => setColorMode(mode)}
                        className={[
                          "px-2.5 py-1 transition",
                          colorMode === mode
                            ? "bg-ember-500/20 font-medium text-ember-200"
                            : "text-stone-400 hover:text-stone-200",
                        ].join(" ")}
                      >
                        {mode === "any" ? "Within" : "Exact"}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {COLORS.map(({ value, label }) => (
                    <FilterChip
                      key={value}
                      label={label}
                      checked={colorFilter.has(value)}
                      onChange={() => setColorFilter((p) => toggleSet(p, value))}
                    />
                  ))}
                </div>
              </div>

              {/* Card Type */}
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-stone-500">Card Type</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {TYPES.map((t) => (
                    <FilterChip
                      key={t}
                      label={t === "Legendary Creature" ? "Legendary" : t}
                      checked={typeFilter.has(t)}
                      onChange={() => setTypeFilter((p) => toggleSet(p, t))}
                    />
                  ))}
                </div>
              </div>
            </div>

            <button
              type="button"
              onClick={() => setFilterOpen(false)}
              className="mt-6 w-full rounded-xl bg-stone-100 py-2.5 text-sm font-semibold text-ink-950 transition hover:bg-stone-200"
            >
              Done
            </button>
          </div>
        </div>
      )}

      {/* Card detail modal */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <button
            type="button"
            className="absolute inset-0 cursor-default"
            aria-label="Close"
            onClick={closeModal}
          />
          <div className="relative flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-ink-900 shadow-card sm:flex-row">
            <div className="relative mx-auto w-44 shrink-0 self-start sm:mx-0 sm:w-64">
              <PrintingCarousel
                cardName={selectedCard?.name ?? "Card"}
                printings={selected.printings}
                selectedScryfallId={currentPrinting?.scryfall_id ?? null}
                onSelect={(printing) => void choosePrinting(selected, printing)}
              />
              {currentPrinting && (
                <button
                  type="button"
                  onClick={() => setPrintChangeTarget({
                    kind: "printing",
                    sourceScryfallId: currentPrinting.scryfall_id,
                  })}
                  className="mt-3 w-full rounded-xl border border-arcane-400/30 bg-arcane-500/10 px-3 py-2 text-xs font-medium text-arcane-200 transition hover:bg-arcane-500/20"
                >
                  Change print
                </button>
              )}
            </div>

            {/* Right: scrollable content */}
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
              <button
                type="button"
                onClick={closeModal}
                className="absolute right-3 top-3 z-10 rounded-full bg-black/60 px-2.5 py-1 text-xs font-medium text-stone-300 backdrop-blur-sm transition hover:bg-black/80"
              >
                ✕
              </button>

              <div className="space-y-5 p-5 pt-10">
                {printChangeTarget && correctionLines.length > 0 && (
                  <PrintChangePicker
                    sourceScryfallId={printChangeTarget.sourceScryfallId}
                    title={printChangeTarget.kind === "line" ? "Change this inventory line" : "Change this entire printing"}
                    description={printChangeTarget.kind === "line"
                      ? `Choose how many copies in this ${printChangeTarget.line.foil ? "foil" : "nonfoil"} line to move to another printing.`
                      : `Move all ${correctionPrinting?.total_quantity ?? 0} copies across ${correctionLines.length} inventory ${correctionLines.length === 1 ? "line" : "lines"}. Exact deck assignments will follow the corrected printing.`}
                    requiresFoil={correctionLines.some((line) => line.foil)}
                    requiresNonfoil={correctionLines.some((line) => !line.foil)}
                    languages={correctionLines.flatMap((line) => line.language ? [line.language] : [])}
                    maxQuantity={printChangeTarget.kind === "line" ? printChangeTarget.line.quantity : undefined}
                    onCancel={() => setPrintChangeTarget(null)}
                    onApply={applyPrintChange}
                  />
                )}

                {/* Name + qty */}
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="font-display text-xl font-semibold leading-tight text-stone-100">
                      {selectedCard?.name ?? selected.oracle_id}
                    </h2>
                    {selectedCard?.type_line && (
                      <p className="mt-1 text-xs text-stone-500">{selectedCard.type_line}</p>
                    )}
                  </div>
                  <div className="shrink-0 rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-center">
                    <div className="font-mono text-xl font-bold text-stone-100">×{locations?.owned_total ?? selected.total_quantity}</div>
                    <div className="text-[10px] uppercase tracking-wider text-stone-500">owned</div>
                  </div>
                </div>

                {/* Action buttons */}
                <div>
                  <button
                    type="button"
                    onClick={() => void runDeckFit()}
                    disabled={matchLoading}
                    className="w-full rounded-xl border border-ember-400/30 bg-ember-500/10 py-2.5 text-sm font-medium text-ember-200 transition hover:bg-ember-500/20 disabled:opacity-50"
                  >
                    {matchLoading ? "Scoring…" : "Deck fit"}
                  </button>
                </div>

                {currentPrinting && (
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wider text-stone-500">This printing</p>
                    <div className="mt-2 space-y-2">
                      {currentPrinting.lines.map((line) => (
                        <div key={line.id} className="flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-ink-950/55 px-3 py-2 text-xs">
                          <div className="min-w-0">
                            <p className="font-medium text-stone-200">
                              {line.quantity} {line.quantity === 1 ? "copy" : "copies"}
                              {line.foil ? " · Foil" : " · Nonfoil"}
                            </p>
                            <p className="mt-0.5 truncate text-stone-500">
                              {[line.condition, line.language?.toUpperCase()].filter(Boolean).join(" · ") || "No condition details"}
                            </p>
                            <div className="mt-2 flex items-end gap-2">
                              <label className="text-[10px] font-medium uppercase tracking-wider text-stone-500">
                                Quantity
                                <input
                                  type="number"
                                  min={1}
                                  max={999999}
                                  step={1}
                                  value={quantityDrafts[line.id] ?? String(line.quantity)}
                                  onChange={(event) => setQuantityDrafts((previous) => ({
                                    ...previous,
                                    [line.id]: event.target.value,
                                  }))}
                                  onKeyDown={(event) => {
                                    if (event.key === "Enter") void saveInventoryQuantity(line);
                                  }}
                                  className="mt-1 block w-20 rounded-lg border border-white/10 bg-ink-950 px-2 py-1.5 font-mono text-xs normal-case tracking-normal text-stone-200 outline-none focus:ring-1 focus:ring-ember-400/40"
                                />
                              </label>
                              <button
                                type="button"
                                disabled={
                                  updatingQuantityId === line.id
                                  || (quantityDrafts[line.id] ?? String(line.quantity)) === String(line.quantity)
                                }
                                onClick={() => void saveInventoryQuantity(line)}
                                className="rounded-lg border border-emerald-400/25 px-2.5 py-1.5 text-[10px] font-medium text-emerald-300 transition hover:bg-emerald-950/40 disabled:opacity-40"
                              >
                                {updatingQuantityId === line.id ? "Saving…" : "Save quantity"}
                              </button>
                            </div>
                          </div>
                          <div className="flex shrink-0 gap-1.5">
                            <button
                              type="button"
                              onClick={() => setPrintChangeTarget({
                                kind: "line",
                                sourceScryfallId: currentPrinting.scryfall_id,
                                line,
                              })}
                              className="rounded-lg border border-arcane-400/25 px-2.5 py-1.5 text-[10px] font-medium text-arcane-300 transition hover:bg-arcane-950/40"
                            >
                              Change print
                            </button>
                            <button
                              type="button"
                              disabled={deletingId === line.id}
                              onClick={() => void removeInventoryLine(line.id)}
                              className="rounded-lg border border-red-500/25 px-2.5 py-1.5 text-[10px] font-medium text-red-300 transition hover:bg-red-950/40 disabled:opacity-50"
                            >
                              {deletingId === line.id ? "Removing…" : "Remove line"}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                    {inventoryEditError && (
                      <div className="mt-3 rounded-xl border border-red-500/30 bg-red-950/40 px-3 py-2 text-xs text-red-200">
                        {inventoryEditError}
                      </div>
                    )}
                  </div>
                )}

                {/* Physical locations and deck demand */}
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-stone-500">Copy locations</p>
                  <div className="mt-2">
                    {membershipLoading ? (
                      <p className="text-xs text-stone-500">Loading…</p>
                    ) : !locations ? (
                      <p className="text-xs text-stone-500">Location details unavailable.</p>
                    ) : (
                      <div className="space-y-3">
                        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                          <div className="rounded-lg bg-ink-950/55 p-2"><span className="block text-stone-500">In decks</span><strong className="text-emerald-300">{locations.grabbed_total}</strong></div>
                          <div className="rounded-lg bg-ink-950/55 p-2"><span className="block text-stone-500">In bulk</span><strong className="text-stone-200">{locations.bulk_total}</strong></div>
                          <div className="rounded-lg bg-ink-950/55 p-2"><span className="block text-stone-500">Free</span><strong className="text-arcane-300">{locations.freely_available}</strong></div>
                          <div className="rounded-lg bg-ink-950/55 p-2"><span className="block text-stone-500">Proxies</span><strong className="text-violet-300">{locations.proxy_total}</strong></div>
                        </div>
                        {locations.pending_total > 0 && (
                          <p className="text-xs text-amber-300">
                            {locations.pending_total} bulk {locations.pending_total === 1 ? "copy is" : "copies are"} earmarked to grab
                            {locations.demand_shortfall > 0 ? ` · ${locations.demand_shortfall} still missing` : ""}.
                          </p>
                        )}
                        {locations.decks.length === 0 ? <p className="text-xs text-stone-500">Not used by any decks.</p> : <ul className="space-y-1">
                        {locations.decks.map((m) => (
                          <li key={m.deck_id}>
                            <Link
                              to={`/decks/${m.deck_id}`}
                              onClick={closeModal}
                              className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-arcane-300 transition hover:bg-white/5"
                            >
                              <span className="min-w-0 flex-1 truncate">{m.deck_name}</span>
                              <span className="text-[10px] text-stone-500">
                                {m.grabbed_quantity ? `${m.grabbed_quantity} grabbed` : ""}
                                {m.grabbed_quantity && (m.pending_quantity || m.proxy_quantity) ? " · " : ""}
                                {m.pending_quantity ? `${m.pending_quantity} needed` : ""}
                                {(m.grabbed_quantity || m.pending_quantity) && m.proxy_quantity ? " · " : ""}
                                {m.proxy_quantity ? `${m.proxy_quantity} proxy` : ""}
                              </span>
                              {m.is_commander && (
                                <span className="rounded bg-arcane-500/20 px-1.5 py-0.5 text-[10px] text-arcane-200">
                                  CMD
                                </span>
                              )}
                            </Link>
                          </li>
                        ))}
                        </ul>}
                      </div>
                    )}
                  </div>
                </div>

                {/* Deck fit results */}
                {matches !== null && (
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wider text-stone-500">Deck suggestions</p>
                    {matches.length === 0 ? (
                      <p className="mt-2 text-xs text-stone-500">No strong matches over the threshold.</p>
                    ) : (
                      <ul className="mt-2 space-y-3">
                        {matches.map((m) => (
                          <li key={m.deck_id} className="rounded-xl border border-white/10 bg-ink-950/60 p-3">
                            <div className="flex items-center justify-between gap-2">
                              <Link
                                to={`/decks/${m.deck_id}`}
                                className="font-medium text-arcane-300 hover:underline"
                                onClick={closeModal}
                              >
                                {m.deck_name}
                              </Link>
                              <span className="font-mono text-sm text-ember-300">{m.score}</span>
                            </div>
                            <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] uppercase tracking-wide">
                              <span className="rounded bg-white/5 px-2 py-0.5 text-stone-400">{m.deck_status}</span>
                              <span
                                className={
                                  m.kind === "upgrade"
                                    ? "rounded bg-arcane-500/20 px-2 py-0.5 text-arcane-300"
                                    : "rounded bg-ember-500/10 px-2 py-0.5 text-ember-200"
                                }
                              >
                                {m.kind}
                              </span>
                            </div>
                            <ul className="mt-2 list-inside list-disc space-y-0.5 text-xs text-stone-400">
                              {m.reasons.map((r) => (
                                <li key={r}>{r}</li>
                              ))}
                            </ul>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
