import { useEffect, useMemo, useRef, useState } from "react";
import { fetchPrintingOptions, type PrintingOption } from "../api";

function readableError(reason: unknown): string {
  if (!(reason instanceof Error)) return "Could not add this card";
  try {
    const parsed = JSON.parse(reason.message) as { detail?: unknown };
    return typeof parsed.detail === "string" ? parsed.detail : reason.message;
  } catch {
    return reason.message;
  }
}

export function AddCardPrintingPicker({
  sourceScryfallId,
  title = "Choose a printing",
  description = "Select the exact physical printing you are adding.",
  onCancel,
  onAdd,
}: {
  sourceScryfallId: string;
  title?: string;
  description?: string;
  onCancel: () => void;
  onAdd: (printing: PrintingOption, quantity: number, foil: boolean) => Promise<void>;
}) {
  const [options, setOptions] = useState<PrintingOption[]>([]);
  const [selected, setSelected] = useState<PrintingOption | null>(null);
  const [query, setQuery] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [foil, setFoil] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const quantityRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchPrintingOptions(sourceScryfallId)
      .then((rows) => {
        if (!cancelled) setOptions(rows);
      })
      .catch((reason) => {
        if (!cancelled) setError(readableError(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [sourceScryfallId]);

  useEffect(() => {
    if (selected) quantityRef.current?.focus();
  }, [selected]);

  const visibleOptions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((option) => (
      [option.set_name, option.set_code, option.collector_number, option.released_at]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle))
    ));
  }, [options, query]);

  function choose(option: PrintingOption) {
    setSelected(option);
    setQuantity(1);
    setFoil(option.foil && !option.nonfoil);
    setError(null);
  }

  async function add() {
    if (!selected) return;
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 999_999) {
      setError("How many to add must be a whole number of at least 1.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onAdd(selected, quantity, foil);
    } catch (reason) {
      setError(readableError(reason));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-2xl border border-emerald-400/25 bg-ink-950/75 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-display text-lg text-stone-100">{title}</h3>
          <p className="mt-1 text-xs leading-relaxed text-stone-400">{description}</p>
        </div>
        <button type="button" onClick={onCancel} className="rounded-lg px-2 py-1 text-stone-500 hover:bg-white/5 hover:text-stone-200" aria-label="Cancel card addition">✕</button>
      </div>

      {loading ? (
        <p className="py-8 text-center text-sm text-stone-500">Loading every Scryfall printing…</p>
      ) : options.length === 0 && !error ? (
        <p className="py-8 text-center text-sm text-stone-500">No printings were found.</p>
      ) : (
        <>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter by set, code, collector number, or year…"
            className="mt-4 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-xs text-stone-200 outline-none placeholder:text-stone-600 focus:ring-2 focus:ring-arcane-400/35"
          />
          <p className="mt-2 text-[10px] text-stone-500">{visibleOptions.length} of {options.length} printings</p>
          <div className="mt-2 grid max-h-[42vh] grid-cols-2 gap-3 overflow-y-auto pr-1 sm:grid-cols-3">
            {visibleOptions.map((option) => (
              <button
                key={option.scryfall_id}
                type="button"
                onClick={() => choose(option)}
                className={`overflow-hidden rounded-xl border text-left transition ${
                  selected?.scryfall_id === option.scryfall_id
                    ? "border-emerald-400 bg-emerald-500/10 ring-2 ring-emerald-400/25"
                    : "border-white/10 bg-ink-900/65 hover:border-white/25"
                }`}
              >
                <div className="aspect-[5/7] bg-ink-800">
                  {option.image_uri_normal ? (
                    <img src={option.image_uri_normal} alt={`${option.name} — ${option.set_name}`} className="h-full w-full object-cover" loading="lazy" />
                  ) : (
                    <div className="flex h-full items-center justify-center p-2 text-center text-xs text-stone-500">{option.name}</div>
                  )}
                </div>
                <div className="p-2.5">
                  <p className="line-clamp-2 text-xs font-semibold text-stone-200">{option.set_name}</p>
                  <p className="mt-1 text-[10px] text-stone-500">
                    {[option.set_code?.toUpperCase(), option.collector_number, option.released_at].filter(Boolean).join(" · ")}
                  </p>
                  <p className="mt-1 text-[10px] text-stone-500">
                    {[option.nonfoil ? "Nonfoil" : null, option.foil ? "Foil" : null].filter(Boolean).join(" · ")}
                  </p>
                </div>
              </button>
            ))}
          </div>
        </>
      )}

      {selected && (
        <div className="mt-4 rounded-xl border border-white/10 bg-ink-900/60 p-3">
          <label className="block text-xs font-medium text-stone-300">
            How many to add?
            <input
              ref={quantityRef}
              type="number"
              min={1}
              max={999999}
              step={1}
              value={quantity}
              onChange={(event) => setQuantity(Number(event.target.value))}
              onKeyDown={(event) => {
                if (event.key === "Enter") void add();
              }}
              className="mt-1 block w-28 rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 font-mono text-sm text-stone-200 outline-none focus:ring-2 focus:ring-emerald-400/35"
            />
          </label>
          {selected.foil && selected.nonfoil && (
            <div className="mt-3 flex gap-2" aria-label="Card treatment">
              <button type="button" onClick={() => setFoil(false)} className={`rounded-lg px-3 py-2 text-xs ${!foil ? "bg-emerald-500/20 text-emerald-100 ring-1 ring-emerald-400/30" : "bg-white/5 text-stone-400"}`}>Nonfoil</button>
              <button type="button" onClick={() => setFoil(true)} className={`rounded-lg px-3 py-2 text-xs ${foil ? "bg-violet-500/20 text-violet-100 ring-1 ring-violet-400/30" : "bg-white/5 text-stone-400"}`}>Foil</button>
            </div>
          )}
        </div>
      )}

      {error && <div className="mt-3 rounded-xl border border-red-500/30 bg-red-950/40 px-3 py-2 text-xs text-red-200">{error}</div>}

      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded-xl border border-white/10 px-4 py-2 text-xs text-stone-400 hover:bg-white/5">Cancel</button>
        <button type="button" disabled={!selected || saving} onClick={() => void add()} className="rounded-xl bg-emerald-500/20 px-4 py-2 text-xs font-medium text-emerald-100 ring-1 ring-emerald-400/30 disabled:opacity-40">
          {saving ? "Adding…" : selected ? `Add ${quantity} ${quantity === 1 ? "copy" : "copies"}` : "Select a printing"}
        </button>
      </div>
    </section>
  );
}
