import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createDeck, fetchDecks, importDeckCsvNew, importDeckTextNew, type Deck } from "../api";
import { CONSTRUCTED_FORMATS, formatOptionLabel } from "../lib/formats";

type DeckSort = "name" | "commander" | "completed";

export default function DecksPage() {
  const navigate = useNavigate();
  const [decks, setDecks] = useState<Deck[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [format, setFormat] = useState("commander");
  const [status, setStatus] = useState("building");
  const [creating, setCreating] = useState(false);
  const [deckSort, setDeckSort] = useState<DeckSort>("name");

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvDeckName, setCsvDeckName] = useState("");
  const [csvFormat, setCsvFormat] = useState("commander");
  const [csvStatus, setCsvStatus] = useState("building");
  const [csvBusy, setCsvBusy] = useState(false);

  const [plainText, setPlainText] = useState("");
  const [plainBusy, setPlainBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setDecks(await fetchDecks());
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load decks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sortedDecks = useMemo(() => {
    const byName = (left: Deck, right: Deck) => (
      left.name.localeCompare(right.name, undefined, { sensitivity: "base" })
    );
    return [...decks].sort((left, right) => {
      if (deckSort === "commander") {
        const leftCommander = left.commander_name?.trim();
        const rightCommander = right.commander_name?.trim();
        if (!leftCommander && rightCommander) return 1;
        if (leftCommander && !rightCommander) return -1;
        if (leftCommander && rightCommander) {
          const commanderOrder = leftCommander.localeCompare(
            rightCommander,
            undefined,
            { sensitivity: "base" },
          );
          if (commanderOrder) return commanderOrder;
        }
        return byName(left, right);
      }
      if (deckSort === "completed") {
        const statusRank = (deck: Deck) => (
          ["complete", "completed"].includes(deck.status.toLowerCase())
            ? 0
            : deck.status.toLowerCase() === "building"
              ? 1
              : 2
        );
        const statusOrder = statusRank(left) - statusRank(right);
        return statusOrder || byName(left, right);
      }
      return byName(left, right);
    });
  }, [decks, deckSort]);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      const d = await createDeck({ name: name.trim(), format, status });
      setName("");
      setDecks((prev) => [...prev, d].sort((a, b) => a.name.localeCompare(b.name)));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Create failed");
    } finally {
      setCreating(false);
    }
  }

  async function onCsvImport(e: React.FormEvent) {
    e.preventDefault();
    if (!csvFile || !csvDeckName.trim()) return;
    setCsvBusy(true);
    setErr(null);
    try {
      const { deck, row_errors } = await importDeckCsvNew(
        csvFile,
        csvDeckName.trim(),
        csvFormat,
        csvStatus,
      );
      if (row_errors.length > 0) {
        const er = row_errors[0];
        if (er) {
          window.alert(
            `Deck import completed with ${row_errors.length} row issue(s). Example — row ${er.row_index + 1}: ${er.error}`
          );
        }
      }
      setCsvFile(null);
      setCsvDeckName("");
      await load();
      navigate(`/decks/${deck.id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "CSV import failed");
    } finally {
      setCsvBusy(false);
    }
  }

  async function onPlainImport(e: React.FormEvent) {
    e.preventDefault();
    if (!plainText.trim() || !csvDeckName.trim()) return;
    setPlainBusy(true);
    setErr(null);
    try {
      const { deck, row_errors } = await importDeckTextNew(
        plainText,
        csvDeckName.trim(),
        csvFormat,
        csvStatus,
      );
      if (row_errors.length > 0) {
        const er = row_errors[0];
        if (er) {
          window.alert(
            `Deck import completed with ${row_errors.length} row issue(s). Example — line ${er.row_index + 1}: ${er.error}`
          );
        }
      }
      setPlainText("");
      setCsvDeckName("");
      await load();
      navigate(`/decks/${deck.id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Plaintext import failed");
    } finally {
      setPlainBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-4xl font-semibold text-stone-100">Decks</h1>
        <p className="mt-2 max-w-xl text-stone-400">
          Track lists you are building or have finished. Set a commander Scryfall ID on the deck page for stricter
          Commander color checks in the matcher.
        </p>
      </div>

      <details className="group rounded-2xl border border-white/10 bg-ink-900/30 shadow-card">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-6 py-5 text-stone-200 marker:hidden">
          <div>
            <h2 className="font-display text-xl">Create or import a deck</h2>
            <p className="mt-1 text-sm text-stone-500">Start empty, upload a CSV, or paste a plaintext list.</p>
          </div>
          <span className="text-lg text-stone-500 transition-transform group-open:rotate-180" aria-hidden="true">⌄</span>
        </summary>

        <div className="space-y-6 border-t border-white/10 p-4 sm:p-6">
      <form
        onSubmit={(e) => void onCreate(e)}
        className="flex flex-col gap-4 rounded-2xl border border-white/10 bg-ink-900/40 p-6 shadow-card sm:flex-row sm:items-end"
      >
        <div className="flex-1">
          <label className="text-xs uppercase tracking-wider text-stone-500">Deck name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Slogurk Lands…"
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm outline-none ring-ember-400/30 focus:ring-2"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-wider text-stone-500">Format</label>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm outline-none sm:w-44"
          >
            {CONSTRUCTED_FORMATS.map((f) => (
              <option key={f} value={f}>
                {formatOptionLabel(f)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs uppercase tracking-wider text-stone-500">Status</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm outline-none sm:w-36"
          >
            <option value="building">Building</option>
            <option value="complete">Complete</option>
          </select>
        </div>
        <button
          type="submit"
          disabled={creating || !name.trim()}
          className="rounded-xl bg-stone-100 px-6 py-2.5 text-sm font-semibold text-ink-950 disabled:opacity-40"
        >
          {creating ? "…" : "Create"}
        </button>
      </form>

      <div className="rounded-2xl border border-white/10 bg-ink-900/40 p-6 shadow-card">
        <h2 className="font-display text-xl text-stone-100">Create deck from CSV</h2>
        <p className="mt-2 max-w-2xl text-sm text-stone-400">
          Same ManaBox-style columns as collection import: at minimum <span className="font-mono text-stone-300">Scryfall ID</span>{" "}
          and <span className="font-mono text-stone-300">Quantity</span> per row. Or use the plaintext list below.
        </p>
        <form onSubmit={(e) => void onCsvImport(e)} className="mt-6 flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="sm:col-span-2">
              <label className="text-xs uppercase tracking-wider text-stone-500">Deck name</label>
              <input
                value={csvDeckName}
                onChange={(e) => setCsvDeckName(e.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-arcane-400/40"
                placeholder="My new list…"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-wider text-stone-500">Format</label>
              <select
                value={csvFormat}
                onChange={(e) => setCsvFormat(e.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm outline-none"
              >
                {CONSTRUCTED_FORMATS.map((f) => (
                  <option key={f} value={f}>
                    {formatOptionLabel(f)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs uppercase tracking-wider text-stone-500">Status</label>
              <select
                value={csvStatus}
                onChange={(e) => setCsvStatus(e.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm outline-none"
              >
                <option value="building">Building</option>
                <option value="complete">Complete</option>
              </select>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <label className="cursor-pointer rounded-xl border border-dashed border-white/20 bg-ink-950/40 px-4 py-3 text-sm text-stone-300 transition hover:border-ember-400/40">
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
              disabled={csvBusy || !csvFile || !csvDeckName.trim()}
              className="rounded-xl bg-ember-500/20 px-5 py-2.5 text-sm font-medium text-ember-100 ring-1 ring-ember-400/30 disabled:opacity-40"
            >
              {csvBusy ? "Importing…" : "Import deck"}
            </button>
          </div>
        </form>
      </div>

      <div className="rounded-2xl border border-white/10 bg-ink-900/40 p-6 shadow-card">
        <h2 className="font-display text-xl text-stone-100">Create deck from plaintext list</h2>
        <p className="mt-2 max-w-2xl text-sm text-stone-400">
          One line per card: <span className="font-mono text-stone-300">qty name</span> (e.g.{" "}
          <span className="font-mono text-stone-300">1 Sol Ring</span>). Use the <strong className="text-stone-300">Scryfall English name</strong>
          . Cards after the <strong className="text-stone-300">last blank line</strong> in the deck are imported as{" "}
          <strong className="text-stone-300">commander</strong> (first one also sets the deck’s commander field).
        </p>
        <form onSubmit={(e) => void onPlainImport(e)} className="mt-6 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="sm:col-span-2">
              <label className="text-xs uppercase tracking-wider text-stone-500">Deck name</label>
              <input
                value={csvDeckName}
                onChange={(e) => setCsvDeckName(e.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-arcane-400/40"
                placeholder="My new list…"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-wider text-stone-500">Format</label>
              <select
                value={csvFormat}
                onChange={(e) => setCsvFormat(e.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm outline-none"
              >
                {CONSTRUCTED_FORMATS.map((f) => (
                  <option key={f} value={f}>
                    {formatOptionLabel(f)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs uppercase tracking-wider text-stone-500">Status</label>
              <select
                value={csvStatus}
                onChange={(e) => setCsvStatus(e.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm outline-none"
              >
                <option value="building">Building</option>
                <option value="complete">Complete</option>
              </select>
            </div>
          </div>
          <textarea
            value={plainText}
            onChange={(e) => setPlainText(e.target.value)}
            placeholder={"1 Sol Ring\n1 Command Tower\n\n1 Your Commander"}
            rows={14}
            className="w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-3 font-mono text-sm text-stone-200 outline-none focus:ring-2 focus:ring-ember-400/30"
            spellCheck={false}
          />
          <div className="flex flex-wrap items-center gap-4">
            <button
              type="submit"
              disabled={plainBusy || !plainText.trim() || !csvDeckName.trim()}
              className="rounded-xl bg-ember-500/20 px-5 py-2.5 text-sm font-medium text-ember-100 ring-1 ring-ember-400/30 disabled:opacity-40"
            >
              {plainBusy ? "Importing…" : "Import deck from text"}
            </button>
          </div>
        </form>
      </div>
        </div>
      </details>

      {err && (
        <div className="rounded-xl border border-red-500/30 bg-red-950/40 px-4 py-3 text-sm text-red-200">{err}</div>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="font-display text-2xl text-stone-100">Your decks</h2>
          <p className="mt-1 text-sm text-stone-500">{decks.length} {decks.length === 1 ? "deck" : "decks"}</p>
        </div>
        <label className="text-xs font-medium uppercase tracking-wider text-stone-500">
          Sort decks
          <select
            value={deckSort}
            onChange={(event) => setDeckSort(event.target.value as DeckSort)}
            className="mt-1 block w-full rounded-xl border border-white/10 bg-ink-950/60 px-4 py-2.5 text-sm normal-case tracking-normal text-stone-200 outline-none sm:w-64"
          >
            <option value="name">Deck name · A–Z</option>
            <option value="commander">Commander name · A–Z</option>
            <option value="completed">Completed first</option>
          </select>
        </label>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {loading ? (
          <p className="text-stone-500">Loading…</p>
        ) : decks.length === 0 ? (
          <p className="text-stone-500">No decks yet — create one above.</p>
        ) : (
          sortedDecks.map((d) => (
            <Link
              key={d.id}
              to={`/decks/${d.id}`}
              className="group rounded-2xl border border-white/10 bg-ink-900/40 p-6 shadow-card transition hover:border-ember-400/30 hover:shadow-glow"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h2 className="font-display text-2xl text-stone-100 group-hover:text-ember-100">{d.name}</h2>
                  {["commander", "edh"].includes(d.format.toLowerCase()) && (
                    <p className="mt-0.5 truncate text-sm text-stone-400">
                      {d.commander_name ?? "Commander not selected"}
                    </p>
                  )}
                </div>
                <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] uppercase tracking-wide text-stone-400">
                  {formatOptionLabel(d.format)}
                </span>
              </div>
              <p className="mt-2 text-sm text-stone-500">
                Status: <span className="text-stone-300">{d.status}</span>
              </p>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
