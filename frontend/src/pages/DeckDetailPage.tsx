import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  addDeckCards,
  deleteDeck,
  fetchDeck,
  fetchTextImportProgress,
  importDeckCsvAppend,
  importDeckTextAppend,
  patchDeck,
  removeDeckCard,
  resolveCard,
  type CardMatch,
  type DeckCard,
  type DeckDetail,
  type TextImportProgress,
} from "../api";
import { CardHoverPreview } from "../components/CardHoverPreview";
import { CONSTRUCTED_FORMATS, formatOptionLabel } from "../lib/formats";

const SCRYFALL_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default function DeckDetailPage() {
  const { id } = useParams();
  const deckId = Number(id);
  const [deck, setDeck] = useState<DeckDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [addQuery, setAddQuery] = useState("");
  const [addAsCommander, setAddAsCommander] = useState(false);
  const [commanderId, setCommanderId] = useState("");
  const [busy, setBusy] = useState(false);
  const [pickList, setPickList] = useState<CardMatch[] | null>(null);

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvAddCollection, setCsvAddCollection] = useState(false);
  const [csvBusy, setCsvBusy] = useState(false);

  const [plainText, setPlainText] = useState("");
  const [plainBusy, setPlainBusy] = useState(false);
  const [textProgress, setTextProgress] = useState<TextImportProgress | null>(null);

  const load = useCallback(async () => {
    if (!Number.isFinite(deckId)) return;
    setLoading(true);
    setErr(null);
    try {
      const d = await fetchDeck(deckId);
      setDeck(d);
      setCommanderId(d.commander_scryfall_id ?? "");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load deck");
      setDeck(null);
    } finally {
      setLoading(false);
    }
  }, [deckId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveMeta() {
    if (!deck) return;
    setBusy(true);
    try {
      const d = await patchDeck(deck.id, {
        format: deck.format,
        status: deck.status,
        notes: deck.notes,
        commander_scryfall_id: commanderId.trim() || null,
      });
      setDeck(d);
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
      const { deck: updated, row_errors } = await importDeckCsvAppend(deck.id, csvFile, csvAddCollection);
      setDeck(updated);
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
      const { deck: updated, row_errors } = await importDeckTextAppend(deck.id, plainText, csvAddCollection);
      setDeck(updated);
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
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Remove failed");
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
        <button
          type="button"
          onClick={() => void onDeleteDeck()}
          disabled={busy}
          className="self-start rounded-lg border border-red-500/30 px-3 py-1.5 text-xs text-red-300 hover:bg-red-950/40"
        >
          Delete deck
        </button>
      </div>

      {err && (
        <div className="rounded-xl border border-red-500/30 bg-red-950/40 px-4 py-3 text-sm text-red-200">{err}</div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 rounded-2xl border border-white/10 bg-ink-900/40 p-6 lg:col-span-1">
          <h2 className="text-sm font-medium uppercase tracking-wider text-stone-500">Settings</h2>
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
            onChange={(e) => setCommanderId(e.target.value)}
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
            disabled={busy}
            onClick={() => void saveMeta()}
            className="mt-4 w-full rounded-xl bg-stone-100 py-2.5 text-sm font-semibold text-ink-950"
          >
            Save settings
          </button>
        </div>

        <div className="space-y-6 rounded-2xl border border-white/10 bg-ink-900/40 p-6 lg:col-span-2">
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
              <label className="flex items-center gap-2 text-xs text-stone-400">
                <input
                  type="checkbox"
                  checked={csvAddCollection}
                  onChange={(e) => setCsvAddCollection(e.target.checked)}
                  className="rounded border-white/20 bg-ink-950"
                />
                Also add to collection
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
                <label className="flex items-center gap-2 text-xs text-stone-400">
                  <input
                    type="checkbox"
                    checked={csvAddCollection}
                    onChange={(e) => setCsvAddCollection(e.target.checked)}
                    className="rounded border-white/20 bg-ink-950"
                  />
                  Also add to collection
                </label>
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
                    ? `Resolving cards: ${textProgress.done} / ${textProgress.total} unique (${textProgress.total_qty} total)`
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
                    cards.map((dc) => (
                      <tr key={dc.id} className="border-t border-white/5">
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-2">
                            <CardHoverPreview
                              src={dc.card?.image_uri_normal}
                              name={dc.card?.name ?? dc.scryfall_id}
                            >
                              {dc.card?.image_uri_normal ? (
                                <img
                                  src={dc.card.image_uri_normal}
                                  alt=""
                                  className="h-8 cursor-default rounded ring-1 ring-white/10"
                                />
                              ) : null}
                            </CardHoverPreview>
                            <span className="text-stone-200">{dc.card?.name ?? dc.scryfall_id}</span>
                            {dc.is_commander ? (
                              <span className="rounded bg-arcane-500/20 px-1.5 text-[10px] text-arcane-200">CMD</span>
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
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
