import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useBlocker, useParams } from "react-router-dom";
import {
  deleteDeck,
  fetchDeck,
  fetchDeckAnalysis,
  previewDeckCsv,
  previewDeckText,
  resolveCard,
  saveDeckDraft,
  type Card,
  type CardMatch,
  type DeckCard,
  type DeckAnalysis,
  type DeckDetail,
  type DeckTextPreview,
} from "../api";
import { CardHoverPreview } from "../components/CardHoverPreview";
import { DeckPrintingModal } from "../components/DeckPrintingModal";
import { CONSTRUCTED_FORMATS, formatOptionLabel } from "../lib/formats";

function AnalysisPanel({ analysis, loading }: { analysis: DeckAnalysis | null; loading: boolean }) {
  if (!analysis) {
    return loading ? (
      <div className="rounded-2xl border border-white/10 bg-ink-900/40 p-5 text-sm text-stone-500">
        Running deterministic deck checks…
      </div>
    ) : null;
  }

  const findings = [...analysis.legality.findings, ...analysis.health.findings];
  const missingFindings = findings.filter((finding) => finding.message.startsWith("Missing "));
  const zeroCoverageFindings = findings.filter((finding) => finding.message.startsWith("The deck has 0 "));
  const otherFindings = findings.filter((finding) => (
    !finding.message.startsWith("Missing ")
    && !finding.message.startsWith("The deck has 0 ")
  ));
  const missingCount = analysis.availability.missing.length + missingFindings.length;
  const roleLabel = (value: string) => value.replaceAll("_", " ");

  return (
    <section className="rounded-2xl border border-white/10 bg-ink-900/40 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium uppercase tracking-wider text-stone-500">Deterministic deck analysis</h2>
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
        <details>
          <summary className="cursor-pointer text-xs font-medium uppercase tracking-wider text-stone-500 hover:text-stone-300">Functional roles</summary>
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
        </details>

        <details>
          <summary className="cursor-pointer text-xs font-medium uppercase tracking-wider text-stone-500 hover:text-stone-300">Findings</summary>
          {findings.length === 0 && analysis.availability.missing.length === 0 ? (
            <p className="mt-2 text-xs text-emerald-300">No legality, availability, or health issues detected.</p>
          ) : (
            <div className="mt-2 max-h-56 space-y-2 overflow-y-auto pr-1 text-xs">
              {missingCount > 0 && (
                <details>
                  <summary className="cursor-pointer text-red-300 hover:text-red-200">
                    Missing errors for {missingCount} cards
                  </summary>
                  <ul className="mt-2 space-y-1 border-l border-red-500/20 pl-3">
                    {analysis.availability.missing.map((row) => (
                      <li key={row.oracle_id} className="text-red-300">
                        Missing {row.shortfall}× {row.name} ({row.owned} owned, {row.required} required)
                      </li>
                    ))}
                    {missingFindings.map((finding, index) => (
                      <li key={`${finding.code}-missing-${index}`} className="text-red-300">
                        {finding.message}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {zeroCoverageFindings.length > 0 && (
                <details>
                  <summary className="cursor-pointer text-amber-300 hover:text-amber-200">
                    Missing coverage in {zeroCoverageFindings.length} deck-building {zeroCoverageFindings.length === 1 ? "area" : "areas"}
                  </summary>
                  <ul className="mt-2 space-y-1 border-l border-amber-500/20 pl-3">
                    {zeroCoverageFindings.map((finding, index) => (
                      <li key={`${finding.code}-zero-${index}`} className="text-amber-300">
                        {finding.message}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              <ul className="space-y-1">
              {otherFindings.map((finding, index) => (
                <li key={`${finding.code}-${index}`} className={finding.severity === "error" ? "text-red-300" : "text-amber-300"}>
                  {finding.message}
                </li>
              ))}
              </ul>
            </div>
          )}
        </details>
      </div>
    </section>
  );
}

type DraftStatus = "pending" | "grabbed" | "proxy";

type DraftCopy = {
  key: string;
  card: Card;
  cardScryfallId: string;
  printingScryfallId: string | null;
  printing: Card | null;
  status: DraftStatus;
  foil: boolean | null;
  isCommander: boolean;
  isSideboard: boolean;
  addToCollection: boolean;
  collectionAdditionId: string | null;
};

function copiesFromDeck(deck: DeckDetail): DraftCopy[] {
  return deck.cards.flatMap((entry) => {
    const units = entry.allocations.flatMap((allocation) => (
      Array.from({ length: allocation.quantity }, () => allocation)
    ));
    const completeUnits = units.length === entry.quantity
      ? units
      : Array.from({ length: entry.quantity }, (_, index) => ({
          id: -(index + 1),
          status: index < entry.grabbed_quantity
            ? "grabbed" as const
            : index < entry.grabbed_quantity + entry.proxy_quantity
              ? "proxy" as const
              : "pending" as const,
          quantity: 1,
          scryfall_id: null,
          foil: null,
          printing: null,
        }));
    return completeUnits.map((allocation, index) => ({
      key: `${entry.id}-${index}`,
      card: entry.card!,
      cardScryfallId: entry.scryfall_id,
      printingScryfallId: allocation.scryfall_id,
      printing: allocation.printing,
      status: allocation.status,
      foil: allocation.foil,
      isCommander: entry.is_commander,
      isSideboard: entry.is_sideboard,
      addToCollection: false,
      collectionAdditionId: null,
    }));
  }).filter((copy) => copy.card);
}

function previewCard(entry: DeckTextPreview["cards"][number]): Card {
  return {
    scryfall_id: entry.scryfall_id,
    oracle_id: entry.oracle_id,
    name: entry.name,
    type_line: entry.type_line,
    mana_cost: null,
    cmc: 0,
    colors: entry.colors,
    color_identity: entry.colors,
    rarity: null,
    set_code: entry.set_code,
    collector_number: entry.collector_number,
    image_uri_normal: entry.image_uri_normal,
  };
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
  const [busy, setBusy] = useState(false);
  const [pickList, setPickList] = useState<CardMatch[] | null>(null);
  const [draftCopies, setDraftCopies] = useState<DraftCopy[]>([]);
  const [draftDirty, setDraftDirty] = useState(false);
  const [printingEditorKey, setPrintingEditorKey] = useState<string | null>(null);
  const nextDraftKey = useRef(1);
  const allowHardNavigation = useRef(false);
  const navigationBlocker = useBlocker(({ currentLocation, nextLocation }) => (
    draftDirty
    && `${currentLocation.pathname}${currentLocation.search}`
      !== `${nextLocation.pathname}${nextLocation.search}`
  ));

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvBusy, setCsvBusy] = useState(false);

  const [plainText, setPlainText] = useState("");
  const [plainBusy, setPlainBusy] = useState(false);

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
      setDraftCopies(copiesFromDeck(d));
      setCommanderId(d.commander_scryfall_id ?? "");
      setDraftDirty(false);
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

  useEffect(() => {
    if (!draftDirty) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (allowHardNavigation.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [draftDirty]);

  async function saveChanges() {
    if (!deck) return;
    setBusy(true);
    try {
      const d = await saveDeckDraft(deck.id, {
        name: deck.name.trim(),
        format: deck.format,
        status: deck.status,
        notes: deck.notes,
        cards: draftCopies.map((copy) => ({
          card_scryfall_id: copy.cardScryfallId,
          printing_scryfall_id: copy.printingScryfallId,
          status: copy.status,
          foil: copy.foil,
          is_commander: copy.isCommander,
          is_sideboard: copy.isSideboard,
          add_to_collection: copy.addToCollection,
          collection_addition_id: copy.collectionAdditionId,
        })),
      });
      setDeck(d);
      setDraftCopies(copiesFromDeck(d));
      setCommanderId(d.commander_scryfall_id ?? "");
      setDraftDirty(false);
      void refreshAnalysis(d.format);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  function stageCard(card: CardMatch) {
    const key = `new-${nextDraftKey.current++}`;
    setDraftCopies((previous) => [
      ...previous.map((copy) => addAsCommander ? { ...copy, isCommander: false } : copy),
      {
        key,
        card,
        cardScryfallId: card.scryfall_id,
        printingScryfallId: card.scryfall_id,
        printing: card,
        status: "pending",
        foil: null,
        isCommander: addAsCommander,
        isSideboard: false,
        addToCollection: false,
        collectionAdditionId: null,
      },
    ]);
    setDraftDirty(true);
    setAddQuery("");
    setAddAsCommander(false);
    setPickList(null);
  }

  async function submitAdd() {
    const raw = addQuery.trim();
    if (!deck || !raw) return;
    setPickList(null);
    setErr(null);

    setBusy(true);
    try {
      const res = await resolveCard(raw);
      if (res.matches.length === 0) {
        setErr("No cards matched.");
        return;
      }
      if (res.matches.length === 1) {
        const only = res.matches[0];
        if (only) stageCard(only);
        return;
      }
      setPickList(res.matches);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not resolve card name");
    } finally {
      setBusy(false);
    }
  }

  function stagePreview(preview: DeckTextPreview) {
    const additions = preview.cards.flatMap((entry) => (
      Array.from({ length: entry.quantity }, () => ({
        key: `new-${nextDraftKey.current++}`,
        card: previewCard(entry),
        cardScryfallId: entry.scryfall_id,
        printingScryfallId: entry.scryfall_id,
        printing: previewCard(entry),
        status: "pending" as const,
        foil: entry.foil,
        isCommander: entry.is_commander,
        isSideboard: false,
        addToCollection: false,
        collectionAdditionId: null,
      }))
    ));
    const hasCommander = additions.some((copy) => copy.isCommander);
    setDraftCopies((previous) => [
      ...previous.map((copy) => hasCommander ? { ...copy, isCommander: false } : copy),
      ...additions,
    ]);
    setDraftDirty(true);
    if (preview.row_errors.length > 0) {
      const first = preview.row_errors[0];
      if (first) window.alert(`Staged with ${preview.row_errors.length} row issue(s). Example — row ${first.row_index + 1}: ${first.error}`);
    }
  }

  async function onCsvAppend(e: React.FormEvent) {
    e.preventDefault();
    if (!deck || !csvFile) return;
    setCsvBusy(true);
    setErr(null);
    try {
      stagePreview(await previewDeckCsv(csvFile));
      setCsvFile(null);
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
    setErr(null);

    try {
      stagePreview(await previewDeckText(plainText));
      setPlainText("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Plaintext import failed");
    } finally {
      setPlainBusy(false);
    }
  }

  function removeCopy(key: string) {
    const removed = draftCopies.find((copy) => copy.key === key);
    setDraftCopies((previous) => previous.filter((copy) => copy.key !== key));
    if (removed?.isCommander) setCommanderId("");
    setDraftDirty(true);
  }

  async function onDeleteDeck() {
    if (!deck || !confirm(`Delete deck “${deck.name}”?`)) return;
    setBusy(true);
    try {
      await deleteDeck(deck.id);
      allowHardNavigation.current = true;
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

  const cards = [...draftCopies].sort((a, b) => a.card.name.localeCompare(b.card.name));
  const selectedDraftCopy = draftCopies.find((copy) => copy.key === printingEditorKey) ?? null;
  const selectedModalCard: DeckCard | null = selectedDraftCopy ? {
    id: -1,
    scryfall_id: selectedDraftCopy.cardScryfallId,
    quantity: 1,
    grabbed_quantity: selectedDraftCopy.status === "grabbed" ? 1 : 0,
    proxy_quantity: selectedDraftCopy.status === "proxy" ? 1 : 0,
    is_commander: selectedDraftCopy.isCommander,
    is_sideboard: selectedDraftCopy.isSideboard,
    card: selectedDraftCopy.card,
    allocations: [{
      id: -1,
      status: selectedDraftCopy.status,
      quantity: 1,
      scryfall_id: selectedDraftCopy.printingScryfallId,
      foil: selectedDraftCopy.foil,
      printing: selectedDraftCopy.printing,
    }],
  } : null;

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
            onChange={(e) => {
              setDeck({ ...deck, name: e.target.value });
              setDraftDirty(true);
            }}
            maxLength={200}
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-sm"
          />
          <label className="block text-xs text-stone-500">Format</label>
          <select
            value={deck.format}
            onChange={(e) => {
              setDeck({ ...deck, format: e.target.value });
              setDraftDirty(true);
            }}
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
            onChange={(e) => {
              setDeck({ ...deck, status: e.target.value });
              setDraftDirty(true);
            }}
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-sm"
          >
            <option value="building">Building</option>
            <option value="complete">Complete</option>
          </select>
          <label className="mt-3 block text-xs text-stone-500">Commander Scryfall ID</label>
          <input
            value={commanderId}
            readOnly
            placeholder="Select a commander from a card modal"
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/35 px-3 py-2 font-mono text-xs text-stone-500"
          />
          <label className="mt-3 block text-xs text-stone-500">Notes</label>
          <textarea
            value={deck.notes ?? ""}
            onChange={(e) => {
              setDeck({ ...deck, notes: e.target.value || null });
              setDraftDirty(true);
            }}
            rows={3}
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-sm"
          />
          <button
            type="button"
            disabled={busy || !deck.name.trim() || !draftDirty}
            onClick={() => void saveChanges()}
            className="mt-4 w-full rounded-xl bg-stone-100 py-2.5 text-sm font-semibold text-ink-950"
          >
            {busy ? "Saving…" : draftDirty ? "Save changes" : "Saved"}
          </button>
          </div>
        </aside>

        <div className="min-w-0 space-y-6 rounded-2xl border border-white/10 bg-ink-900/40 p-5 sm:p-6">
          <details open className="group rounded-xl border border-white/10 bg-ink-950/25">
            <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 marker:hidden">
              <div>
                <h2 className="text-sm font-medium uppercase tracking-wider text-stone-400">Add or import cards</h2>
                <p className="mt-1 text-xs text-stone-600">Changes are staged until you save the deck.</p>
              </div>
              <span className="text-stone-500 transition-transform group-open:rotate-180">⌄</span>
            </summary>
            <div className="space-y-6 border-t border-white/10 p-4">
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
                        onClick={() => stageCard(m)}
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
                {csvBusy ? "Reading…" : "Stage CSV"}
              </button>
            </form>
            {csvBusy && (
              <p className="mt-2 text-xs text-stone-400">
                Reading CSV — looking up cards on Scryfall, this may take a moment…
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
                  {plainBusy ? "Reading…" : "Stage text"}
                </button>
              </div>
              {plainBusy && (
                <p className="mt-1 text-xs text-stone-400">
                  Resolving cards for the draft…
                </p>
              )}
            </form>
          </div>
            </div>
          </details>

          <div>
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="font-display text-2xl text-stone-100">Main list</h3>
              <span className="text-sm text-stone-500">{cards.length} cards</span>
            </div>
            {cards.length === 0 ? (
              <div className="mt-3 rounded-2xl border border-dashed border-white/10 px-6 py-10 text-center text-sm text-stone-500">
                No cards — stage cards from the section above.
              </div>
            ) : (
              <div className="mt-3 grid grid-cols-[repeat(auto-fill,minmax(155px,1fr))] gap-3 sm:grid-cols-[repeat(auto-fill,minmax(175px,1fr))] 2xl:grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
                {cards.map((copy) => {
                  const displayed = copy.printing ?? copy.card;
                  return (
                    <article key={copy.key} className={`overflow-hidden rounded-xl border bg-ink-900/65 shadow-card ${
                      copy.status === "grabbed" ? "border-emerald-500/25" : copy.status === "proxy" ? "border-violet-500/30" : "border-white/10"
                    }`}>
                      <CardHoverPreview src={displayed.image_uri_normal} name={copy.card.name}>
                        <button type="button" onClick={() => setPrintingEditorKey(copy.key)} className="relative block aspect-[5/7] w-full overflow-hidden bg-ink-800">
                          {displayed.image_uri_normal ? (
                            <img src={displayed.image_uri_normal} alt={copy.card.name} className="h-full w-full object-cover" loading="lazy" />
                          ) : (
                            <span className="flex h-full items-center justify-center p-3 text-xs text-stone-500">{copy.card.name}</span>
                          )}
                          {copy.isCommander && <span className="absolute left-2 top-2 rounded-full bg-black/80 px-2 py-1 text-[10px] font-semibold text-arcane-200">Commander</span>}
                          {copy.addToCollection && <span className="absolute bottom-2 left-2 rounded-full bg-emerald-950/90 px-2 py-1 text-[10px] font-semibold text-emerald-200">New collection copy</span>}
                        </button>
                      </CardHoverPreview>
                      <div className="space-y-1 p-3">
                        <button type="button" onClick={() => setPrintingEditorKey(copy.key)} className="line-clamp-2 text-left text-sm font-medium leading-tight text-stone-100 hover:text-ember-200">
                          {copy.card.name}
                        </button>
                        <p className="truncate text-[10px] text-stone-500">
                          {[displayed.set_code?.toUpperCase(), displayed.collector_number, copy.foil ? "Foil" : null].filter(Boolean).join(" · ") || copy.card.type_line || "Any printing"}
                        </p>
                        <div className="grid grid-cols-4 gap-1 pt-2">
                          {(["pending", "grabbed", "proxy"] as const).map((status) => (
                            <button
                              key={status}
                              type="button"
                              disabled={copy.status === status}
                              onClick={() => {
                                setDraftCopies((previous) => previous.map((row) => row.key === copy.key ? {
                                  ...row,
                                  status,
                                  addToCollection: row.addToCollection && status === "grabbed",
                                } : row));
                                setDraftDirty(true);
                              }}
                              className={`rounded-md px-1 py-1 text-[9px] font-semibold uppercase tracking-wide ${
                                copy.status === status
                                  ? status === "grabbed" ? "bg-emerald-500/25 text-emerald-100" : status === "proxy" ? "bg-violet-500/25 text-violet-100" : "bg-amber-500/20 text-amber-100"
                                  : "bg-white/5 text-stone-500 hover:bg-white/10 hover:text-stone-200"
                              }`}
                            >
                              {status === "pending" ? "Need" : status}
                            </button>
                          ))}
                          <button type="button" onClick={() => removeCopy(copy.key)} className="rounded-md bg-red-500/10 px-1 py-1 text-[9px] font-semibold uppercase tracking-wide text-red-300 hover:bg-red-500/20">
                            Remove
                          </button>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
      {selectedModalCard && selectedDraftCopy && (
        <DeckPrintingModal
          deckId={deck.id}
          deckCard={selectedModalCard}
          allowCommanderSelection={["commander", "edh"].includes(deck.format.toLowerCase())}
          currentCommanderName={draftCopies.find((copy) => copy.isCommander)?.card.name ?? null}
          onClose={() => setPrintingEditorKey(null)}
          onDraftSaved={(updatedCard) => {
            const allocation = updatedCard.allocations[0];
            setDraftCopies((previous) => previous.map((copy) => copy.key === selectedDraftCopy.key ? {
              ...copy,
              printingScryfallId: allocation?.scryfall_id ?? null,
              printing: allocation?.printing ?? null,
              foil: allocation?.foil ?? null,
              status: allocation?.status ?? copy.status,
            } : copy));
            setDraftDirty(true);
            setPrintingEditorKey(null);
          }}
          onDraftCommanderSelected={() => {
            setDraftCopies((previous) => previous.map((copy) => ({
              ...copy,
              isCommander: copy.key === selectedDraftCopy.key,
            })));
            setCommanderId(selectedDraftCopy.printingScryfallId ?? selectedDraftCopy.cardScryfallId);
            setDraftDirty(true);
            setPrintingEditorKey(null);
          }}
          onDraftCardAdded={(card, quantity, foil) => {
            setDraftCopies((previous) => [
              ...previous,
              ...Array.from({ length: quantity }, () => ({
                key: `new-${nextDraftKey.current++}`,
                card,
                cardScryfallId: card.scryfall_id,
                printingScryfallId: card.scryfall_id,
                printing: card,
                status: "grabbed" as const,
                foil,
                isCommander: false,
                isSideboard: false,
                addToCollection: true,
                collectionAdditionId: crypto.randomUUID(),
              })),
            ]);
            setDraftDirty(true);
            setPrintingEditorKey(null);
          }}
        />
      )}
      {navigationBlocker.state === "blocked" && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-4" role="dialog" aria-modal="true" aria-labelledby="unsaved-deck-title">
          <div className="w-full max-w-md rounded-2xl border border-white/10 bg-ink-900 p-6 shadow-2xl">
            <h2 id="unsaved-deck-title" className="font-display text-2xl text-stone-100">Discard unsaved changes?</h2>
            <p className="mt-2 text-sm text-stone-400">
              This deck has changes that have not been saved. Leaving now will discard them.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => navigationBlocker.reset()}
                className="rounded-xl border border-white/10 px-4 py-2 text-sm text-stone-200 hover:bg-white/5"
              >
                Keep editing
              </button>
              <button
                type="button"
                onClick={() => {
                  setDraftDirty(false);
                  navigationBlocker.proceed();
                }}
                className="rounded-xl bg-red-500/20 px-4 py-2 text-sm font-medium text-red-200 ring-1 ring-red-400/30 hover:bg-red-500/30"
              >
                Discard and leave
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
