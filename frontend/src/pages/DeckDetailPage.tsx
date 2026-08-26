import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  addDeckCards,
  deleteDeck,
  fetchDeck,
  fetchDeckAnalysis,
  fetchTextImportProgress,
  importDeckCsvAppend,
  importDeckTextAppend,
  patchDeck,
  removeDeckCard,
  resolveCard,
  setDeckCommander,
  type CardMatch,
  type DeckCard,
  type DeckAnalysis,
  type DeckDetail,
  type TextImportProgress,
} from "../api";
import { CardHoverPreview } from "../components/CardHoverPreview";
import { DeckPrintingModal } from "../components/DeckPrintingModal";
import { CONSTRUCTED_FORMATS, formatOptionLabel } from "../lib/formats";

const SCRYFALL_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function AnalysisPanel({ analysis, loading }: { analysis: DeckAnalysis | null; loading: boolean }) {
  if (!analysis) {
    return loading ? (
      <div className="rounded-2xl border border-white/10 bg-ink-900/40 p-5 text-sm text-stone-500">
        Running deterministic deck checks…
      </div>
    ) : null;
  }

  const findings = [...analysis.legality.findings, ...analysis.health.findings];
  const roleLabel = (value: string) => value.replaceAll("_", " ");

  return (
    <section className="rounded-2xl border border-white/10 bg-ink-900/40 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium uppercase tracking-wider text-stone-500">Deterministic deck analysis</h2>
          <p className="mt-1 text-xs text-stone-600">Commander rules, owned quantities, and deck-health heuristics. No AI model.</p>
        </div>
        {loading ? <span className="text-xs text-stone-500">Refreshing…</span> : null}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-2">
        {[
          ["Legality", analysis.legal ? "Legal" : "Illegal", analysis.legal],
          ["Availability", analysis.available ? "Owned" : `${analysis.availability.total_shortfall} short`, analysis.available],
          ["Deck size", `${analysis.deck_size.actual} / 100`, analysis.deck_size.actual === 100],
          ["Lands", `${analysis.health.lands.count}`, analysis.health.lands.count >= analysis.health.lands.target_min],
          ["Mana sources", `${analysis.health.mana_sources.total}`, analysis.health.mana_sources.total >= analysis.health.mana_sources.target_min],
          ["Average MV", `${analysis.health.curve.average_mana_value}`, analysis.health.curve.average_mana_value <= 4],
        ].map(([label, value, good]) => (
          <div key={String(label)} className="rounded-xl border border-white/5 bg-ink-950/45 px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-wider text-stone-600">{label}</div>
            <div className={`mt-1 text-sm font-semibold ${good ? "text-emerald-300" : "text-amber-300"}`}>{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-5 md:grid-cols-2 xl:grid-cols-1">
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wider text-stone-500">Functional roles</h3>
          <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-3 xl:grid-cols-2">
            {Object.entries(analysis.health.roles).map(([role, data]) => (
              <div key={role} className="flex justify-between rounded-lg bg-ink-950/45 px-2.5 py-1.5 text-xs">
                <span className="capitalize text-stone-400">{roleLabel(role)}</span>
                <span className={data.status === "low" ? "text-amber-300" : "text-stone-200"}>
                  {data.count} <span className="text-stone-600">/ {data.target_min}+</span>
                </span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h3 className="text-xs font-medium uppercase tracking-wider text-stone-500">Findings</h3>
          {findings.length === 0 && analysis.availability.missing.length === 0 ? (
            <p className="mt-2 text-xs text-emerald-300">No legality, availability, or health issues detected.</p>
          ) : (
            <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto pr-1 text-xs">
              {analysis.availability.missing.map((row) => (
                <li key={row.oracle_id} className="text-red-300">
                  Missing {row.shortfall}× {row.name} ({row.owned} owned, {row.required} required)
                </li>
              ))}
              {findings.map((finding, index) => (
                <li key={`${finding.code}-${index}`} className={finding.severity === "error" ? "text-red-300" : "text-amber-300"}>
                  {finding.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

function displayedDeckCard(dc: DeckCard) {
  return dc.allocations.find((allocation) => allocation.printing)?.printing ?? dc.card;
}

export default function DeckDetailPage() {
  const { id } = useParams();
  const deckId = Number(id);
  const [deck, setDeck] = useState<DeckDetail | null>(null);
  const [analysis, setAnalysis] = useState<DeckAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [addQuery, setAddQuery] = useState("");
  const [addAsCommander, setAddAsCommander] = useState(false);
  const [commanderId, setCommanderId] = useState("");
  const [commanderDirty, setCommanderDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pickList, setPickList] = useState<CardMatch[] | null>(null);
  const [printingEditorCard, setPrintingEditorCard] = useState<DeckCard | null>(null);

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvBusy, setCsvBusy] = useState(false);

  const [plainText, setPlainText] = useState("");
  const [plainBusy, setPlainBusy] = useState(false);
  const [textProgress, setTextProgress] = useState<TextImportProgress | null>(null);

  const refreshAnalysis = useCallback(async (format: string) => {
    if (!Number.isFinite(deckId) || !["commander", "edh"].includes(format.toLowerCase())) {
      setAnalysis(null);
      return;
    }
    setAnalysisLoading(true);
    try {
      setAnalysis(await fetchDeckAnalysis(deckId));
    } catch {
      setAnalysis(null);
    } finally {
      setAnalysisLoading(false);
    }
  }, [deckId]);

  const load = useCallback(async () => {
    if (!Number.isFinite(deckId)) return;
    setLoading(true);
    setErr(null);
    try {
      const d = await fetchDeck(deckId);
      setDeck(d);
      setCommanderId(d.commander_scryfall_id ?? "");
      setCommanderDirty(false);
      void refreshAnalysis(d.format);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load deck");
      setDeck(null);
    } finally {
      setLoading(false);
    }
  }, [deckId, refreshAnalysis]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveMeta() {
    if (!deck) return;
    setBusy(true);
    try {
      const d = await patchDeck(deck.id, {
        name: deck.name.trim(),
        format: deck.format,
        status: deck.status,
        notes: deck.notes,
        ...(commanderDirty
          ? { commander_scryfall_id: commanderId.trim() || null }
          : {}),
      });
      setDeck(d);
      setCommanderId(d.commander_scryfall_id ?? "");
      setCommanderDirty(false);
      void refreshAnalysis(d.format);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function addCardWithScryfallId(scryfallId: string) {
    if (!deck) return;
    setBusy(true);
    setErr(null);
    try {
      const d = await addDeckCards(deck.id, [
        { scryfall_id: scryfallId, quantity: 1, is_commander: addAsCommander },
      ]);
      setDeck(d);
      void refreshAnalysis(d.format);
      setAddQuery("");
      setAddAsCommander(false);
      setPickList(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Add failed");
    } finally {
      setBusy(false);
    }
  }

  async function submitAdd() {
    const raw = addQuery.trim();
    if (!deck || !raw) return;
    setPickList(null);
    setErr(null);

    if (SCRYFALL_UUID.test(raw)) {
      await addCardWithScryfallId(raw);
      return;
    }

    setBusy(true);
    try {
      const res = await resolveCard(raw);
      if (res.matches.length === 0) {
        setErr("No cards matched.");
        return;
      }
      if (res.matches.length === 1) {
        const only = res.matches[0];
        if (only) await addCardWithScryfallId(only.scryfall_id);
        return;
      }
      setPickList(res.matches);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not resolve card name");
    } finally {
      setBusy(false);
    }
  }

  async function onCsvAppend(e: React.FormEvent) {
    e.preventDefault();
    if (!deck || !csvFile) return;
    setCsvBusy(true);
    setErr(null);
    try {
      const { deck: updated, row_errors } = await importDeckCsvAppend(deck.id, csvFile);
      setDeck(updated);
      void refreshAnalysis(updated.format);
      setCsvFile(null);
      if (row_errors.length > 0) {
        const er = row_errors[0];
        if (er) {
          window.alert(`Import completed with ${row_errors.length} row issue(s). Example — row ${er.row_index + 1}: ${er.error}`);
        }
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "CSV import failed");
    } finally {
      setCsvBusy(false);
    }
  }

  async function onPlainAppend(e: React.FormEvent) {
    e.preventDefault();
    if (!deck || !plainText.trim()) return;
    setPlainBusy(true);
    setTextProgress(null);
    setErr(null);

    const pollId = setInterval(() => {
      void fetchTextImportProgress(deck.id).then((p) => {
        if (p) setTextProgress(p);
      });
    }, 400);

    try {
      const { deck: updated, row_errors } = await importDeckTextAppend(deck.id, plainText);
      setDeck(updated);
      void refreshAnalysis(updated.format);
      setPlainText("");
      if (row_errors.length > 0) {
        const er = row_errors[0];
        if (er) window.alert(`Import completed with ${row_errors.length} row issue(s). Example — line ${er.row_index + 1}: ${er.error}`);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Plaintext import failed");
    } finally {
      clearInterval(pollId);
      setPlainBusy(false);
      setTextProgress(null);
    }
  }

  async function removeCard(dc: DeckCard) {
    if (!deck) return;
    setBusy(true);
    try {
      const d = await removeDeckCard(deck.id, dc.id);
      setDeck(d);
      setCommanderId(d.commander_scryfall_id ?? "");
      setCommanderDirty(false);
      void refreshAnalysis(d.format);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Remove failed");
    } finally {
      setBusy(false);
    }
  }

  async function makeCommander(dc: DeckCard) {
    if (!deck) return;
    const current = deck.cards.find((card) => card.is_commander);
    if (
      current
      && !confirm(
        `Replace ${current.card?.name ?? "the current commander"} with ${dc.card?.name ?? "this card"}?`,
      )
    ) return;

    setBusy(true);
    setErr(null);
    try {
      const d = await setDeckCommander(deck.id, dc.id);
      setDeck(d);
      setCommanderId(d.commander_scryfall_id ?? "");
      setCommanderDirty(false);
      void refreshAnalysis(d.format);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Commander selection failed");
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteDeck() {
    if (!deck || !confirm(`Delete deck “${deck.name}”?`)) return;
    setBusy(true);
    try {
      await deleteDeck(deck.id);
      window.location.href = "/decks";
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  if (!Number.isFinite(deckId)) {
    return <p className="text-stone-500">Invalid deck.</p>;
  }

  if (loading) return <p className="text-stone-500">Loading deck…</p>;
  if (!deck) return <p className="text-stone-500">Deck not found.</p>;

  const cards = [...deck.cards].sort((a, b) => {
    const an = a.card?.name ?? a.scryfall_id;
    const bn = b.card?.name ?? b.scryfall_id;
    return an.localeCompare(bn);
  });

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link to="/decks" className="text-sm text-stone-500 hover:text-ember-300">
            ← Decks
          </Link>
          <h1 className="mt-2 font-display text-4xl font-semibold text-stone-100">{deck.name}</h1>
        </div>
        <div className="flex flex-wrap gap-2 self-start">
          <Link
            to={`/assembly?deck=${deck.id}`}
            className="rounded-xl bg-emerald-500/20 px-4 py-2 text-sm font-medium text-emerald-100 ring-1 ring-emerald-400/30 transition hover:bg-emerald-500/30"
          >
            Assemble deck
          </Link>
          <button
            type="button"
            onClick={() => void onDeleteDeck()}
            disabled={busy}
            className="rounded-xl border border-red-500/30 px-4 py-2 text-sm text-red-300 hover:bg-red-950/40"
          >
            Delete deck
          </button>
        </div>
      </div>

      {err && (
        <div className="rounded-xl border border-red-500/30 bg-red-950/40 px-4 py-3 text-sm text-red-200">{err}</div>
      )}

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(300px,360px)_minmax(0,1fr)]">
        <aside className="space-y-4 xl:sticky xl:top-24 xl:max-h-[calc(100vh-7rem)] xl:overflow-y-auto xl:pr-1">
          <AnalysisPanel analysis={analysis} loading={analysisLoading} />
          <div className="space-y-4 rounded-2xl border border-white/10 bg-ink-900/40 p-5">
          <h2 className="text-sm font-medium uppercase tracking-wider text-stone-500">Settings</h2>
          <label className="block text-xs text-stone-500">Deck name</label>
          <input
            value={deck.name}
            onChange={(e) => setDeck({ ...deck, name: e.target.value })}
            maxLength={200}
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-sm"
          />
          <label className="block text-xs text-stone-500">Format</label>
          <select
            value={deck.format}
            onChange={(e) => setDeck({ ...deck, format: e.target.value })}
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-sm"
          >
            {CONSTRUCTED_FORMATS.map((f) => (
              <option key={f} value={f}>
                {formatOptionLabel(f)}
              </option>
            ))}
          </select>
          <label className="mt-3 block text-xs text-stone-500">Status</label>
          <select
            value={deck.status}
            onChange={(e) => setDeck({ ...deck, status: e.target.value })}
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-sm"
          >
            <option value="building">Building</option>
            <option value="complete">Complete</option>
          </select>
          <label className="mt-3 block text-xs text-stone-500">Commander Scryfall ID (UUID)</label>
          <input
            value={commanderId}
            onChange={(e) => {
              setCommanderId(e.target.value);
              setCommanderDirty(true);
            }}
            placeholder="00000000-0000-0000-0000-000000000000"
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 font-mono text-xs"
          />
          <label className="mt-3 block text-xs text-stone-500">Notes</label>
          <textarea
            value={deck.notes ?? ""}
            onChange={(e) => setDeck({ ...deck, notes: e.target.value || null })}
            rows={3}
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-sm"
          />
          <button
            type="button"
            disabled={busy || !deck.name.trim()}
            onClick={() => void saveMeta()}
            className="mt-4 w-full rounded-xl bg-stone-100 py-2.5 text-sm font-semibold text-ink-950"
          >
            Save settings
          </button>
          </div>
        </aside>

        <div className="min-w-0 space-y-6 rounded-2xl border border-white/10 bg-ink-900/40 p-5 sm:p-6">
          <div>
            <h2 className="text-sm font-medium uppercase tracking-wider text-stone-500">Add card</h2>
            <p className="mt-1 text-xs text-stone-500">
              Type a <strong className="text-stone-400">card name</strong> (Scryfall exact / fuzzy / search) or paste a{" "}
              <strong className="text-stone-400">Scryfall ID</strong> (UUID).
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <input
                value={addQuery}
                onChange={(e) => setAddQuery(e.target.value)}
                placeholder="Lightning Bolt or UUID…"
                className="min-w-[200px] flex-1 rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-sm"
                onKeyDown={(e) => {
                  if (e.key === "Enter") void submitAdd();
                }}
              />
              <label className="flex items-center gap-2 text-xs text-stone-400">
                <input
                  type="checkbox"
                  checked={addAsCommander}
                  onChange={(e) => setAddAsCommander(e.target.checked)}
                  className="rounded border-white/20 bg-ink-950"
                />
                Commander
              </label>
              <button
                type="button"
                disabled={busy || !addQuery.trim()}
                onClick={() => void submitAdd()}
                className="rounded-xl bg-ember-500/20 px-4 py-2 text-sm font-medium text-ember-100 ring-1 ring-ember-400/30"
              >
                Add
              </button>
            </div>
            {pickList && pickList.length > 1 ? (
              <div className="mt-4 rounded-xl border border-white/10 bg-ink-950/50 p-3">
                <p className="text-xs text-stone-500">Multiple matches — pick one:</p>
                <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-sm">
                  {pickList.map((m) => (
                    <li key={m.scryfall_id}>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void addCardWithScryfallId(m.scryfall_id)}
                        className="w-full rounded-lg px-2 py-1.5 text-left text-stone-200 hover:bg-white/10"
                      >
                        <span className="font-medium">{m.name}</span>
                        {m.type_line ? (
                          <span className="ml-2 text-xs text-stone-500">{m.type_line}</span>
                        ) : null}
                      </button>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={() => setPickList(null)}
                  className="mt-2 text-xs text-stone-500 hover:text-stone-300"
                >
                  Cancel
                </button>
              </div>
            ) : null}
          </div>

          <div className="border-t border-white/10 pt-6">
            <h2 className="text-sm font-medium uppercase tracking-wider text-stone-500">Import CSV into this deck</h2>
            <p className="mt-1 text-xs text-stone-500">
              Requires <span className="font-mono">Scryfall ID</span> and <span className="font-mono">Quantity</span>{" "}
              columns (ManaBox export).
            </p>
            <form onSubmit={(e) => void onCsvAppend(e)} className="mt-3 flex flex-wrap items-center gap-3">
              <label className="cursor-pointer rounded-lg border border-dashed border-white/20 bg-ink-950/40 px-3 py-2 text-xs text-stone-300">
                <input
                  type="file"
                  accept=".csv,text/csv"
                  className="hidden"
                  onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
                />
                {csvFile ? csvFile.name : "Choose CSV…"}
              </label>
              <button
                type="submit"
                disabled={csvBusy || !csvFile}
                className="rounded-lg bg-arcane-500/20 px-3 py-2 text-xs font-medium text-arcane-100 ring-1 ring-arcane-400/30 disabled:opacity-40"
              >
                {csvBusy ? "Importing…" : "Import"}
              </button>
            </form>
            {csvBusy && (
              <p className="mt-2 text-xs text-stone-400">
                Importing CSV — looking up cards on Scryfall, this may take a moment…
              </p>
            )}
          </div>

          <div className="border-t border-white/10 pt-6">
            <h2 className="text-sm font-medium uppercase tracking-wider text-stone-500">Import plaintext list</h2>
            <p className="mt-1 text-xs text-stone-500">
              Lines <span className="font-mono">qty name</span>. Cards after the <strong className="text-stone-400">last blank line</strong> are
              added as commander (first commander also updates the commander field).
            </p>
            <form onSubmit={(e) => void onPlainAppend(e)} className="mt-3 space-y-3">
              <textarea
                value={plainText}
                onChange={(e) => setPlainText(e.target.value)}
                placeholder={"1 Sol Ring\n1 Command Tower\n\n1 Your Commander"}
                rows={10}
                className="w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 font-mono text-xs text-stone-200 outline-none focus:ring-2 focus:ring-ember-400/30"
                spellCheck={false}
              />
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="submit"
                  disabled={plainBusy || !plainText.trim()}
                  className="rounded-lg bg-ember-500/15 px-3 py-2 text-xs font-medium text-ember-100 ring-1 ring-ember-400/25 disabled:opacity-40"
                >
                  {plainBusy ? "Importing…" : "Import text"}
                </button>
              </div>
              {plainBusy && (
                <p className="mt-1 text-xs text-stone-400">
                  {textProgress
                    ? (textProgress.batches_total != null && textProgress.batches_total > 0 && textProgress.batches_done !== textProgress.batches_total)
                      ? `Fetching from Scryfall: batch ${textProgress.batches_done ?? 0} / ${textProgress.batches_total}…`
                      : `Processing: ${textProgress.done} / ${textProgress.total} cards`
                    : "Starting…"}
                </p>
              )}
            </form>
          </div>

          <div>
            <h3 className="text-sm font-medium text-stone-300">Main list ({cards.reduce((sum, dc) => sum + dc.quantity, 0)} entries)</h3>
            <div className="mt-2 max-h-[480px] overflow-y-auto rounded-xl border border-white/5">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-ink-950/95 text-xs uppercase text-stone-500">
                  <tr>
                    <th className="px-3 py-2">Card</th>
                    <th className="px-3 py-2">Qty</th>
                    <th className="px-3 py-2 text-right"> </th>
                  </tr>
                </thead>
                <tbody>
                  {cards.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-3 py-8 text-center text-stone-500">
                        No cards — add by name or import CSV / plaintext above.
                      </td>
                    </tr>
                  ) : (
                    cards.map((dc) => {
                      const displayed = displayedDeckCard(dc);
                      return (
                      <tr key={dc.id} className="border-t border-white/5">
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => setPrintingEditorCard(dc)}
                              className="flex items-center gap-2 text-left hover:text-ember-200"
                              aria-label={`Choose printing for ${dc.card?.name ?? dc.scryfall_id}`}
                            >
                              <CardHoverPreview
                                src={displayed?.image_uri_normal}
                                name={displayed?.name ?? dc.scryfall_id}
                              >
                                {displayed?.image_uri_normal ? (
                                  <img
                                    src={displayed.image_uri_normal}
                                    alt=""
                                    className="h-8 rounded ring-1 ring-white/10"
                                  />
                                ) : null}
                              </CardHoverPreview>
                              <span className="text-stone-200 hover:text-ember-200">{dc.card?.name ?? dc.scryfall_id}</span>
                            </button>
                            {dc.is_commander ? (
                              <span className="rounded bg-arcane-500/20 px-1.5 text-[10px] text-arcane-200">CMD</span>
                            ) : null}
                            {["commander", "edh"].includes(deck.format.toLowerCase()) && !dc.is_commander ? (
                              <button
                                type="button"
                                onClick={() => void makeCommander(dc)}
                                disabled={busy}
                                className="rounded-lg border border-arcane-400/25 px-2 py-1 text-[11px] text-arcane-200 transition hover:bg-arcane-500/15 disabled:opacity-40"
                              >
                                Make commander
                              </button>
                            ) : null}
                          </div>
                        </td>
                        <td className="px-3 py-2 font-mono text-stone-400">{dc.quantity}</td>
                        <td className="px-3 py-2 text-right">
                          <button
                            type="button"
                            onClick={() => void removeCard(dc)}
                            disabled={busy}
                            className="text-xs text-red-400 hover:underline"
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      {printingEditorCard && (
        <DeckPrintingModal
          deckId={deck.id}
          deckCard={printingEditorCard}
          onClose={() => setPrintingEditorCard(null)}
          onSaved={(updated) => {
            setDeck(updated);
            setPrintingEditorCard(null);
            void refreshAnalysis(updated.format);
          }}
        />
      )}
    </div>
  );
}
