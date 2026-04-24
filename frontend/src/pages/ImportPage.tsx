import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { fetchManaboxImportProgress, importManabox, type ImportRowResult, type ManaboxProgress } from "../api";

export default function ImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<{ added_quantity: number; rows: ImportRowResult[] } | null>(null);
  const [progress, setProgress] = useState<ManaboxProgress | null>(null);
  const [selected, setSelected] = useState<ImportRowResult | null>(null);

  useEffect(() => {
    if (!selected) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setSelected(null);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [selected]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  }, []);

  const onPick = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  }, []);

  async function runImport() {
    if (!file) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    setProgress(null);

    const importKey = crypto.randomUUID();
    const pollId = setInterval(() => {
      void fetchManaboxImportProgress(importKey).then((p) => {
        if (p) setProgress(p);
      });
    }, 500);

    try {
      setResult(await importManabox(file, importKey));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Import failed");
    } finally {
      clearInterval(pollId);
      setProgress(null);
      setBusy(false);
    }
  }

  const okRows = result?.rows.filter((r) => r.ok) ?? [];
  const badRows = result?.rows.filter((r) => !r.ok) ?? [];
  const withMatches = okRows.filter((r) => r.matches.length > 0);

  return (
    <>
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-4xl font-semibold text-stone-100">Import</h1>
        <p className="mt-2 max-w-2xl text-balance text-stone-400">
          Drop your ManaBox export CSV. We read <span className="font-mono text-stone-300">Scryfall ID</span> and{" "}
          <span className="font-mono text-stone-300">Quantity</span>, merge duplicates that share foil / condition /
          language, hydrate from Scryfall, then score new lines against your decks.
        </p>
      </div>

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="rounded-2xl border border-dashed border-white/20 bg-ink-900/50 p-10 text-center shadow-glow transition hover:border-ember-400/40 hover:bg-ink-900/70"
      >
        <p className="text-stone-300">{file ? file.name : "Drag CSV here or choose a file"}</p>
        <label className="mt-4 inline-block cursor-pointer rounded-full bg-gradient-to-r from-ember-500/30 to-arcane-500/30 px-6 py-2.5 text-sm font-medium text-stone-100 ring-1 ring-white/10 transition hover:from-ember-500/40 hover:to-arcane-500/40">
          Browse
          <input type="file" accept=".csv,text/csv" className="hidden" onChange={onPick} />
        </label>
        <button
          type="button"
          disabled={!file || busy}
          onClick={() => void runImport()}
          className="ml-3 rounded-full bg-stone-100 px-6 py-2.5 text-sm font-semibold text-ink-950 transition enabled:hover:bg-white disabled:opacity-40"
        >
          {busy ? "Importing…" : "Run import"}
        </button>
      </div>
      {busy && (
        <p className="mt-4 text-sm text-stone-400">
          {progress === null
            ? "Starting…"
            : progress.batches_total === 0
            ? "All cards already cached — processing rows…"
            : progress.batches_done >= progress.batches_total
            ? "Card data fetched — processing rows…"
            : `Fetching card data from Scryfall: ${progress.batches_done} / ${progress.batches_total} batch${progress.batches_total === 1 ? "" : "es"} (up to ${progress.batches_total * 75} cards)`}
        </p>
      )}

      {err && (
        <div className="rounded-xl border border-red-500/30 bg-red-950/40 px-4 py-3 text-sm text-red-200">{err}</div>
      )}

      {result && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-ink-900/40 p-6 shadow-card">
            <h2 className="font-display text-xl text-stone-100">Summary</h2>
            <p className="mt-2 text-sm text-stone-400">
              Total quantity added (summed across rows):{" "}
              <span className="font-mono text-ember-200">{result.added_quantity}</span>
            </p>
            <p className="mt-1 text-sm text-stone-400">
              Rows OK: <span className="font-mono text-stone-200">{okRows.length}</span> · Failed:{" "}
              <span className="font-mono text-stone-200">{badRows.length}</span>
            </p>
            <Link
              to="/"
              className="mt-4 inline-flex rounded-lg border border-white/15 px-4 py-2 text-sm text-stone-200 hover:bg-white/5"
            >
              View collection →
            </Link>
          </div>

          <div className="rounded-2xl border border-ember-400/20 bg-ember-500/5 p-6 shadow-card">
            <h2 className="font-display text-xl text-stone-100">Deck highlights</h2>
            <p className="mt-2 text-xs text-stone-500">
              Cards with at least one deck over score 35 after import.
            </p>
            {withMatches.length === 0 ? (
              <p className="mt-4 text-sm text-stone-500">No deck matches this run — add decks or lower threshold later.</p>
            ) : (
              <ul className="mt-4 max-h-64 space-y-2 overflow-y-auto text-sm">
                {withMatches.map((r) => (
                  <li
                    key={r.row_index}
                    onClick={() => setSelected(r)}
                    className="cursor-pointer rounded-lg border border-white/10 bg-ink-950/50 px-3 py-2 transition hover:border-ember-400/30 hover:bg-ink-900/60"
                  >
                    <span className="font-medium text-stone-200">{r.name}</span>
                    <span className="ml-2 text-xs text-stone-500">
                      {r.matches.map((m) => m.deck_name).join(", ")}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {badRows.length > 0 && (
            <div className="lg:col-span-2 rounded-2xl border border-red-500/20 bg-red-950/20 p-6">
              <h3 className="text-sm font-medium text-red-200">Failed rows</h3>
              <ul className="mt-3 space-y-1 font-mono text-xs text-red-100/80">
                {badRows.map((r) => (
                  <li key={r.row_index}>
                    Row {r.row_index + 1}: {r.error}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>

    {selected && createPortal(
      <div
        className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-sm"
        onClick={() => setSelected(null)}
      >
        <div
          className="relative mx-4 flex max-h-[90vh] w-full max-w-xl flex-col gap-5 overflow-y-auto rounded-2xl border border-white/15 bg-ink-900 p-6 shadow-2xl sm:flex-row"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => setSelected(null)}
            className="absolute right-3 top-3 rounded-full p-1 text-stone-400 hover:bg-white/10 hover:text-stone-100"
            aria-label="Close"
          >
            ✕
          </button>

          {selected.image_uri_normal && (
            <img
              src={selected.image_uri_normal}
              alt={selected.name ?? ""}
              className="w-full flex-shrink-0 rounded-xl shadow-xl sm:w-44"
            />
          )}

          <div className="flex min-w-0 flex-col gap-3">
            <h3 className="pr-6 font-display text-lg font-semibold text-stone-100">{selected.name}</h3>
            {selected.matches.map((m) => (
              <div key={m.deck_id} className="rounded-xl border border-white/10 bg-ink-950/60 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-stone-200">{m.deck_name}</span>
                  <span className="rounded-full bg-ember-500/20 px-2 py-0.5 font-mono text-xs text-ember-200">
                    {m.score} pts
                  </span>
                  {m.kind === "upgrade" && (
                    <span className="rounded-full bg-arcane-500/20 px-2 py-0.5 text-xs text-arcane-200">
                      upgrade
                    </span>
                  )}
                </div>
                {m.reasons.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {m.reasons.map((reason, i) => (
                      <li key={i} className="text-xs text-stone-400">
                        · {reason}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>,
      document.body,
    )}
    </>
  );
}
