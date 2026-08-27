import { useState } from "react";
import { addInventoryCard, resolveCard, type CardMatch } from "../api";
import { AddCardPrintingPicker } from "./AddCardPrintingPicker";

export function AddInventoryCardModal({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: () => Promise<void> | void;
}) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<CardMatch[]>([]);
  const [source, setSource] = useState<CardMatch | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search() {
    const value = query.trim();
    if (!value) return;
    setSearching(true);
    setError(null);
    setSource(null);
    try {
      const result = await resolveCard(value);
      if (result.matches.length === 1 && result.matches[0]) {
        setSource(result.matches[0]);
        setMatches([]);
      } else {
        setMatches(result.matches);
        if (result.matches.length === 0) setError("No cards matched that search.");
      }
    } catch (reason) {
      setMatches([]);
      setError(reason instanceof Error ? reason.message : "Could not find that card");
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Add new card to collection">
      <button type="button" className="absolute inset-0 cursor-default" onClick={onClose} aria-label="Close" />
      <div className="relative max-h-[94vh] w-full max-w-4xl overflow-y-auto rounded-2xl border border-white/10 bg-ink-900 p-5 shadow-2xl sm:p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-2xl text-stone-100">Add New Card</h2>
            <p className="mt-1 text-sm text-stone-400">Find a card, then choose its exact physical printing.</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg px-2 py-1 text-stone-500 hover:bg-white/5 hover:text-stone-200">✕</button>
        </div>

        {!source && (
          <>
            <div className="mt-5 flex gap-2">
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void search();
                }}
                placeholder="Card name…"
                className="min-w-0 flex-1 rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm text-stone-100 outline-none placeholder:text-stone-600 focus:ring-2 focus:ring-ember-400/35"
              />
              <button type="button" disabled={searching || !query.trim()} onClick={() => void search()} className="rounded-xl bg-ember-500/20 px-4 py-2.5 text-sm font-medium text-ember-100 ring-1 ring-ember-400/30 disabled:opacity-40">
                {searching ? "Searching…" : "Find prints"}
              </button>
            </div>

            {matches.length > 1 && (
              <div className="mt-4 rounded-xl border border-white/10 bg-ink-950/40 p-3">
                <p className="text-xs text-stone-500">Choose the card you meant:</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {matches.map((match) => (
                    <button key={match.scryfall_id} type="button" onClick={() => setSource(match)} className="flex items-center gap-3 rounded-xl border border-white/5 bg-ink-900/60 p-2 text-left hover:border-white/20">
                      {match.image_uri_normal && <img src={match.image_uri_normal} alt="" className="h-14 rounded" />}
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-stone-200">{match.name}</span>
                        <span className="block truncate text-xs text-stone-500">{match.type_line}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {source && (
          <div className="mt-5">
            <button type="button" onClick={() => setSource(null)} className="mb-3 text-xs text-stone-500 hover:text-stone-300">← Search for a different card</button>
            <AddCardPrintingPicker
              sourceScryfallId={source.scryfall_id}
              title={`Choose a ${source.name} printing`}
              onCancel={() => setSource(null)}
              onAdd={async (printing, quantity, foil) => {
                await addInventoryCard(printing.scryfall_id, quantity, foil, printing.language ?? "en");
                await onAdded();
                onClose();
              }}
            />
          </div>
        )}

        {error && <div className="mt-4 rounded-xl border border-red-500/30 bg-red-950/40 px-3 py-2 text-xs text-red-200">{error}</div>}
      </div>
    </div>
  );
}
