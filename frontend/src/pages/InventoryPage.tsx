import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  clearInventory,
  deleteInventoryLine,
  fetchCardDecks,
  fetchCardMatches,
  fetchInventory,
  type CardDeckMembership,
  type DeckMatch,
  type InventoryLine,
} from "../api";

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
  const [rows, setRows] = useState<InventoryLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  // Filter state
  const [filterOpen, setFilterOpen] = useState(false);
  const [cmcFilter, setCmcFilter] = useState<Set<string>>(new Set());
  const [colorFilter, setColorFilter] = useState<Set<string>>(new Set());
  const [colorMode, setColorMode] = useState<"any" | "exact">("any");
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());

  // Card detail modal state
  const [selected, setSelected] = useState<InventoryLine | null>(null);
  const [memberships, setMemberships] = useState<CardDeckMembership[] | null>(null);
  const [membershipLoading, setMembershipLoading] = useState(false);
  const [matches, setMatches] = useState<DeckMatch[] | null>(null);
  const [matchLoading, setMatchLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 320);
    return () => clearTimeout(t);
  }, [q]);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setRows(await fetchInventory(debouncedQ, sort));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [debouncedQ, sort]);

  useEffect(() => {
    void load();
  }, [load]);

  // Client-side filter applied on top of the server-sorted/searched rows
  const filteredRows = rows.filter((row) => {
    const c = row.card;

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

  async function openCard(row: InventoryLine) {
    setSelected(row);
    setMatches(null);
    setMemberships(null);
    setMembershipLoading(true);
    try {
      setMemberships(await fetchCardDecks(row.scryfall_id));
    } catch {
      setMemberships([]);
    } finally {
      setMembershipLoading(false);
    }
  }

  function closeModal() {
    setSelected(null);
    setMatches(null);
    setMemberships(null);
  }

  async function runDeckFit() {
    if (!selected) return;
    setMatchLoading(true);
    try {
      setMatches(await fetchCardMatches(selected.scryfall_id));
    } catch {
      setMatches([]);
    } finally {
      setMatchLoading(false);
    }
  }

  async function removeSelected() {
    if (!selected) return;
    const id = selected.id;
    setDeletingId(id);
    try {
      await deleteInventoryLine(id);
      closeModal();
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeletingId(null);
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-stone-100">Collection</h1>
          <p className="mt-2 text-stone-400">Click any card to view details and deck suggestions.</p>
        </div>
        <div className="flex flex-wrap gap-3">
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

      {!loading && rows.length > 0 && (
        <p className="text-sm text-stone-400">
          <span className="font-medium text-stone-200">{filteredRows.reduce((s, r) => s + r.quantity, 0)}</span> total
          &nbsp;·&nbsp;
          <span className="font-medium text-stone-200">{filteredRows.length}</span> unique
          {activeFilterCount > 0 && (
            <span className="text-stone-500">
              {" "}(filtered from {rows.length})
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
      ) : rows.length === 0 ? (
        <p className="py-20 text-center text-stone-500">
          No cards yet.{" "}
          <Link className="text-ember-400 underline-offset-2 hover:underline" to="/import">
            Import your ManaBox CSV
          </Link>
          .
        </p>
      ) : filteredRows.length === 0 ? (
        <p className="py-20 text-center text-stone-500">
          No cards match your filters.{" "}
          <button type="button" onClick={clearFilters} className="text-ember-400 hover:underline">
            Clear filters
          </button>
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
          {filteredRows.map((row) => {
            const c = row.card;
            return (
              <button
                key={row.id}
                type="button"
                onClick={() => void openCard(row)}
                className="group relative aspect-[5/7] w-full overflow-hidden rounded-xl ring-1 ring-white/10 transition duration-150 hover:scale-[1.03] hover:ring-ember-400/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-ember-400"
              >
                {c?.image_uri_normal ? (
                  <img
                    src={c.image_uri_normal}
                    alt={c.name ?? ""}
                    className="h-full w-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center bg-ink-800 p-2">
                    <span className="text-center text-[11px] leading-tight text-stone-400">
                      {c?.name ?? row.scryfall_id}
                    </span>
                  </div>
                )}
                <div className="absolute bottom-1.5 right-1.5 rounded-full bg-black/75 px-2 py-0.5 font-mono text-xs font-semibold text-stone-200 ring-1 ring-white/10 backdrop-blur-sm">
                  ×{row.quantity}
                </div>
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
          <div className="relative flex max-h-[92vh] w-full max-w-2xl overflow-hidden rounded-2xl border border-white/10 bg-ink-900 shadow-card">
            {/* Left: card image at natural aspect ratio — self-start prevents it stretching as right panel grows */}
            <div className="relative w-56 shrink-0 self-start">
              {selectedCard?.image_uri_normal ? (
                <img
                  src={selectedCard.image_uri_normal}
                  alt={selectedCard.name ?? ""}
                  className="w-full rounded-l-2xl"
                />
              ) : (
                <div className="flex aspect-[5/7] w-full items-center justify-center rounded-l-2xl bg-ink-800 p-4">
                  <span className="text-center text-xs text-stone-500">
                    {selectedCard?.name ?? selected.scryfall_id}
                  </span>
                </div>
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
                {/* Name + qty */}
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="font-display text-xl font-semibold leading-tight text-stone-100">
                      {selectedCard?.name ?? selected.scryfall_id}
                    </h2>
                    {selectedCard?.type_line && (
                      <p className="mt-1 text-xs text-stone-500">{selectedCard.type_line}</p>
                    )}
                  </div>
                  <div className="shrink-0 rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-center">
                    <div className="font-mono text-xl font-bold text-stone-100">×{selected.quantity}</div>
                    <div className="text-[10px] uppercase tracking-wider text-stone-500">owned</div>
                  </div>
                </div>

                {/* Action buttons */}
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void runDeckFit()}
                    disabled={matchLoading}
                    className="flex-1 rounded-xl border border-ember-400/30 bg-ember-500/10 py-2.5 text-sm font-medium text-ember-200 transition hover:bg-ember-500/20 disabled:opacity-50"
                  >
                    {matchLoading ? "Scoring…" : "Deck fit"}
                  </button>
                  <button
                    type="button"
                    disabled={deletingId === selected.id}
                    onClick={() => void removeSelected()}
                    className="rounded-xl border border-red-500/30 px-5 py-2.5 text-sm font-medium text-red-300 transition hover:bg-red-950/40 disabled:opacity-50"
                  >
                    {deletingId === selected.id ? "…" : "Remove"}
                  </button>
                </div>

                {/* In your decks */}
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-stone-500">In your decks</p>
                  <div className="mt-2">
                    {membershipLoading ? (
                      <p className="text-xs text-stone-500">Loading…</p>
                    ) : !memberships || memberships.length === 0 ? (
                      <p className="text-xs text-stone-500">Not in any decks.</p>
                    ) : (
                      <ul className="space-y-0.5">
                        {memberships.map((m) => (
                          <li key={m.deck_id}>
                            <Link
                              to={`/decks/${m.deck_id}`}
                              onClick={closeModal}
                              className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-arcane-300 transition hover:bg-white/5"
                            >
                              {m.deck_name}
                              {m.is_commander && (
                                <span className="rounded bg-arcane-500/20 px-1.5 py-0.5 text-[10px] text-arcane-200">
                                  CMD
                                </span>
                              )}
                            </Link>
                          </li>
                        ))}
                      </ul>
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
