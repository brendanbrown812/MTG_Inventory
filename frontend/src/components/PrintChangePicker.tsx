import { useEffect, useMemo, useState } from "react";
import { fetchPrintingOptions, type PrintingOption } from "../api";

function readableError(reason: unknown): string {
  if (!(reason instanceof Error)) return "Could not change printing";
  try {
    const parsed = JSON.parse(reason.message) as { detail?: unknown };
    return typeof parsed.detail === "string" ? parsed.detail : reason.message;
  } catch {
    return reason.message;
  }
}

export function PrintChangePicker({
  sourceScryfallId,
  title,
  description,
  requiresFoil,
  requiresNonfoil,
  languages,
  onCancel,
  onApply,
}: {
  sourceScryfallId: string;
  title: string;
  description: string;
  requiresFoil: boolean;
  requiresNonfoil: boolean;
  languages: string[];
  onCancel: () => void;
  onApply: (targetScryfallId: string) => Promise<void>;
}) {
  const [options, setOptions] = useState<PrintingOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const normalizedLanguages = useMemo(
    () => [...new Set(languages.filter(Boolean).map((value) => value.toLowerCase()))],
    [languages],
  );
  const visibleOptions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((option) => (
      [option.set_name, option.set_code, option.collector_number, option.released_at]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle))
    ));
  }, [options, query]);

  function incompatibility(option: PrintingOption): string | null {
    if (option.scryfall_id === sourceScryfallId) return "Current printing";
    if (requiresFoil && !option.foil) return "No foil version";
    if (requiresNonfoil && !option.nonfoil) return "No nonfoil version";
    if (
      normalizedLanguages.length > 0
      && option.language
      && !normalizedLanguages.includes(option.language.toLowerCase())
    ) {
      return `Language: ${option.language.toUpperCase()}`;
    }
    return null;
  }

  async function apply() {
    if (!selectedId) return;
    setSaving(true);
    setError(null);
    try {
      await onApply(selectedId);
    } catch (reason) {
      setError(readableError(reason));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-2xl border border-ember-400/25 bg-ink-950/75 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-display text-lg text-stone-100">{title}</h3>
          <p className="mt-1 text-xs leading-relaxed text-stone-400">{description}</p>
        </div>
        <button type="button" onClick={onCancel} className="rounded-lg px-2 py-1 text-stone-500 hover:bg-white/5 hover:text-stone-200" aria-label="Cancel print change">✕</button>
      </div>

      {loading ? (
        <p className="py-8 text-center text-sm text-stone-500">Loading every Scryfall printing…</p>
      ) : options.length === 0 && !error ? (
        <p className="py-8 text-center text-sm text-stone-500">No alternate printings were found.</p>
      ) : (
        <>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter by set, code, collector number, or year…"
            className="mt-4 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-xs text-stone-200 outline-none placeholder:text-stone-600 focus:ring-2 focus:ring-arcane-400/35"
          />
          <p className="mt-2 text-[10px] text-stone-500">{visibleOptions.length} of {options.length} printings</p>
          <div className="mt-2 grid max-h-[46vh] grid-cols-2 gap-3 overflow-y-auto pr-1 sm:grid-cols-3">
          {visibleOptions.map((option) => {
            const disabledReason = incompatibility(option);
            const selected = option.scryfall_id === selectedId;
            return (
              <button
                key={option.scryfall_id}
                type="button"
                disabled={Boolean(disabledReason)}
                onClick={() => setSelectedId(option.scryfall_id)}
                className={`overflow-hidden rounded-xl border text-left transition ${
                  selected
                    ? "border-ember-400 bg-ember-500/10 ring-2 ring-ember-400/25"
                    : disabledReason
                      ? "border-white/5 bg-ink-900/30 opacity-45"
                      : "border-white/10 bg-ink-900/65 hover:border-white/25"
                }`}
              >
                <div className="aspect-[5/7] bg-ink-800">
                  {option.image_uri_normal ? (
                    <img src={option.image_uri_normal} alt={option.name} className="h-full w-full object-cover" loading="lazy" />
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
                    {[option.nonfoil ? "Nonfoil" : null, option.foil ? "Foil" : null, option.language?.toUpperCase()].filter(Boolean).join(" · ")}
                  </p>
                  {disabledReason && <p className="mt-1 text-[10px] font-medium text-amber-300">{disabledReason}</p>}
                </div>
              </button>
            );
          })}
          </div>
        </>
      )}

      {error && <div className="mt-3 rounded-xl border border-red-500/30 bg-red-950/40 px-3 py-2 text-xs text-red-200">{error}</div>}

      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded-xl border border-white/10 px-4 py-2 text-xs text-stone-400 hover:bg-white/5">Cancel</button>
        <button type="button" disabled={!selectedId || saving} onClick={() => void apply()} className="rounded-xl bg-emerald-500/20 px-4 py-2 text-xs font-medium text-emerald-100 ring-1 ring-emerald-400/30 disabled:opacity-40">
          {saving ? "Applying…" : "Apply change"}
        </button>
      </div>
    </section>
  );
}
