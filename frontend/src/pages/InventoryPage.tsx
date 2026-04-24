import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  clearInventory,
  deleteInventoryLine,
  fetchCardMatches,
  fetchInventory,
  type Card,
  type DeckMatch,
  type InventoryLine,
} from "../api";
import { CardHoverPreview } from "../components/CardHoverPreview";

/** WUBRG order for consistent display */
const COLOR_CODES = ["W", "U", "B", "R", "G"] as const;

const COLOR_LABEL: Record<string, string> = {
  W: "White",
  U: "Blue",
  B: "Black",
  R: "Red",
  G: "Green",
};

const COLOR_STYLE: Record<string, string> = {
  W: "bg-mana-w text-ink-950",
  U: "bg-mana-u text-white",
  B: "bg-mana-b text-stone-100",
  R: "bg-mana-r text-white",
  G: "bg-mana-g text-white",
};

/** Prefer color identity (Commander / lands); fall back to colors in mana cost. */
function colorCodesForCard(card: Card | null | undefined): string[] {
  if (!card) return [];
  const pick = (s: string | undefined) =>
    (s ?? "")
      .split(",")
      .map((x) => x.trim().toUpperCase())
      .filter(Boolean);
  const id = pick(card.color_identity);
  const cost = pick(card.colors);
  const raw = id.length > 0 ? id : cost;
  return COLOR_CODES.filter((c) => raw.includes(c));
}

function CardColors({ card }: { card: Card | null | undefined }) {
  const codes = colorCodesForCard(card);
  if (!card) return <span className="text-stone-600">—</span>;
  if (codes.length === 0) {
    return <span className="text-stone-500">Colorless</span>;
  }
  return (
    <span className="flex flex-wrap gap-1">
      {codes.map((c) => (
        <span
          key={c}
          title={COLOR_LABEL[c] ?? c}
          className={`inline-flex rounded px-2 py-0.5 text-[11px] font-medium ${COLOR_STYLE[c] ?? "bg-stone-600 text-stone-100"}`}
        >
          {COLOR_LABEL[c] ?? c}
        </span>
      ))}
    </span>
  );
}

export default function InventoryPage() {
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [sort, setSort] = useState("name");
  const [rows, setRows] = useState<InventoryLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [matchCard, setMatchCard] = useState<string | null>(null);
  const [matches, setMatches] = useState<DeckMatch[]>([]);
  const [matchLoading, setMatchLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [clearing, setClearing] = useState(false);

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

  async function openMatches(scryfallId: string) {
    setMatchCard(scryfallId);
    setMatchLoading(true);
    try {
      setMatches(await fetchCardMatches(scryfallId));
    } catch {
      setMatches([]);
    } finally {
      setMatchLoading(false);
    }
  }

  async function removeLine(id: number) {
    setErr(null);
    setDeletingId(id);
    try {
      await deleteInventoryLine(id);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  }

  async function clearAll() {
    if (
      !confirm(
        "Remove every row from your collection? Deck lists are not changed. This cannot be undone.",
      )
    ) {
      return;
    }
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

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-4xl font-semibold text-stone-100">Collection</h1>
          <p className="mt-2 max-w-xl text-balance text-stone-400">
            Search and sort your ManaBox import. Use “Deck fit” to run the v1 matcher against your saved decks.
          </p>
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
          <span className="font-medium text-stone-200">{rows.reduce((s, r) => s + r.quantity, 0)}</span> total cards
          &nbsp;·&nbsp;
          <span className="font-medium text-stone-200">{rows.length}</span> unique
        </p>
      )}

      <div className="overflow-hidden rounded-2xl border border-white/10 bg-ink-900/40 shadow-card shadow-glow backdrop-blur-sm">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="border-b border-white/10 text-xs uppercase tracking-wider text-stone-500">
                <th className="px-4 py-3 font-medium">Card</th>
                <th className="px-4 py-3 font-medium">Qty</th>
                <th className="px-4 py-3 font-medium">MV</th>
                <th className="px-4 py-3 font-medium">Color</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-4 py-16 text-center text-stone-500">
                    Loading collection…
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-16 text-center text-stone-500">
                    No cards yet.{" "}
                    <Link className="text-ember-400 underline-offset-2 hover:underline" to="/import">
                      Import your ManaBox CSV
                    </Link>
                    .
                  </td>
                </tr>
              ) : (
                rows.map((row) => {
                  const c = row.card;
                  return (
                    <tr
                      key={row.id}
                      className="border-b border-white/5 transition hover:bg-white/[0.03]"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          {c?.image_uri_normal ? (
                            <img
                              src={c.image_uri_normal}
                              alt=""
                              className="h-10 w-auto rounded shadow-md ring-1 ring-white/10"
                            />
                          ) : (
                            <div className="h-10 w-7 rounded bg-ink-700" />
                          )}
                          <div>
                            <CardHoverPreview src={c?.image_uri_normal} name={c?.name ?? row.scryfall_id} trigger="click">
                              <span className="font-medium text-stone-100">{c?.name ?? row.scryfall_id}</span>
                            </CardHoverPreview>
                            <div className="line-clamp-1 text-xs text-stone-500">{c?.type_line}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono text-stone-200">{row.quantity}</td>
                      <td className="px-4 py-3 font-mono text-stone-400">{c?.cmc ?? "—"}</td>
                      <td className="px-4 py-3">
                        <CardColors card={c} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex flex-wrap items-center justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => void openMatches(row.scryfall_id)}
                            className="rounded-lg border border-ember-400/30 bg-ember-500/10 px-3 py-1.5 text-xs font-medium text-ember-200 transition hover:bg-ember-500/20"
                          >
                            Deck fit
                          </button>
                          <button
                            type="button"
                            disabled={deletingId === row.id}
                            onClick={() => void removeLine(row.id)}
                            className="rounded-lg border border-red-500/30 px-3 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-950/40 disabled:opacity-50"
                          >
                            {deletingId === row.id ? "…" : "Remove"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {matchCard && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-4 sm:items-center">
          <button
            type="button"
            className="absolute inset-0 cursor-default"
            aria-label="Close"
            onClick={() => setMatchCard(null)}
          />
          <div className="relative max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-white/10 bg-ink-900 p-6 shadow-card">
            <div className="flex items-start justify-between gap-4">
              <h2 className="font-display text-xl text-stone-100">Deck suggestions</h2>
              <button
                type="button"
                onClick={() => setMatchCard(null)}
                className="rounded-lg px-2 py-1 text-stone-500 hover:bg-white/5 hover:text-stone-200"
              >
                ✕
              </button>
            </div>
            <p className="mt-1 text-xs text-stone-500">v1 matcher — legality, colors, curve, themes, rough roles.</p>
            {matchLoading ? (
              <p className="mt-6 text-stone-500">Scoring…</p>
            ) : matches.length === 0 ? (
              <p className="mt-6 text-stone-500">No strong matches over the threshold.</p>
            ) : (
              <ul className="mt-6 space-y-4">
                {matches.map((m) => (
                  <li
                    key={m.deck_id}
                    className="rounded-xl border border-white/10 bg-ink-950/60 p-4"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <Link
                        to={`/decks/${m.deck_id}`}
                        className="font-medium text-arcane-300 hover:underline"
                        onClick={() => setMatchCard(null)}
                      >
                        {m.deck_name}
                      </Link>
                      <span className="font-mono text-sm text-ember-300">{m.score}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-2 text-[10px] uppercase tracking-wide">
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
                    <ul className="mt-3 list-inside list-disc space-y-1 text-xs text-stone-400">
                      {m.reasons.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
