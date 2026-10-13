import { useEffect, useMemo, useState } from "react";
import { fetchInventoryBySet, type InventorySetSummary } from "../api";

export default function CardsBySetPage() {
  const [sets, setSets] = useState<InventorySetSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setErr(null);
    void fetchInventoryBySet()
      .then((rows) => {
        if (active) setSets(rows);
      })
      .catch((error: unknown) => {
        if (active) setErr(error instanceof Error ? error.message : "Failed to load sets");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const totalCards = useMemo(
    () => sets.reduce((total, set) => total + set.total_cards, 0),
    [sets],
  );

  return (
    <section className="mx-auto max-w-5xl">
      <div className="mb-8">
        <p className="text-xs font-medium uppercase tracking-[0.24em] text-ember-400">
          Collection overview
        </p>
        <h1 className="mt-2 font-display text-4xl font-semibold text-stone-100 sm:text-5xl">
          Cards by Set
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-stone-400">
          Every set represented in your collection. Unique cards count each card once per set;
          total cards include every owned copy.
        </p>
      </div>

      {err && (
        <div className="mb-6 rounded-xl border border-red-400/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {err}
        </div>
      )}

      {loading ? (
        <div className="rounded-2xl border border-white/10 bg-ink-900/60 px-6 py-12 text-center text-sm text-stone-500">
          Loading your sets…
        </div>
      ) : sets.length === 0 ? (
        <div className="rounded-2xl border border-white/10 bg-ink-900/60 px-6 py-12 text-center">
          <p className="text-stone-300">Your collection is empty.</p>
          <p className="mt-2 text-sm text-stone-500">Import or add cards to see their sets here.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-white/10 bg-ink-900/60 shadow-card">
          <div className="flex items-center justify-between border-b border-white/10 px-5 py-4 text-sm text-stone-400 sm:px-6">
            <span>{sets.length.toLocaleString()} sets</span>
            <span>{totalCards.toLocaleString()} cards total</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-white/10 text-xs uppercase tracking-wider text-stone-500">
                  <th className="px-5 py-3 font-medium sm:px-6">Set</th>
                  <th className="px-5 py-3 text-right font-medium sm:px-6">Unique cards</th>
                  <th className="px-5 py-3 text-right font-medium sm:px-6">Total cards</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {sets.map((set) => (
                  <tr key={set.set_code} className="transition hover:bg-white/[0.025]">
                    <td className="px-5 py-4 sm:px-6">
                      <div className="flex items-baseline gap-3">
                        <span className="font-medium text-stone-100">
                          {set.set_name ?? (set.set_code === "unknown" ? "Unknown set" : set.set_code.toUpperCase())}
                        </span>
                        {set.set_name && (
                          <span className="font-mono text-xs font-semibold uppercase tracking-wider text-stone-500">
                            {set.set_code}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-4 text-right text-sm tabular-nums text-arcane-400 sm:px-6">
                      {set.unique_cards.toLocaleString()}
                    </td>
                    <td className="px-5 py-4 text-right text-sm font-medium tabular-nums text-ember-400 sm:px-6">
                      {set.total_cards.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
