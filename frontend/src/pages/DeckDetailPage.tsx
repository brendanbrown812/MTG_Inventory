import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useBlocker, useParams } from "react-router-dom";
import {
  deleteDeck,
  downloadDeckBackup,
  fetchBulkSetPrintings,
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
import { randomUuid } from "../lib/uuid";

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
type DraftAction = DraftStatus | "added";
type DeckSortMode = "name" | "type" | "color";

const COLOR_ORDER = ["W", "U", "B", "R", "G"];
const TYPE_ORDER = [
  "Legendary Creature", "Creature", "Planeswalker", "Instant", "Sorcery",
  "Artifact", "Enchantment", "Battle", "Land", "Other",
];
const TYPE_SECTION_LABELS: Record<string, string> = {
  "Legendary Creature": "Legendary Creatures",
  Creature: "Creatures",
  Planeswalker: "Planeswalkers",
  Instant: "Instants",
  Sorcery: "Sorceries",
  Artifact: "Artifacts",
  Enchantment: "Enchantments",
  Battle: "Battles",
  Land: "Lands",
  Other: "Other",
};

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
  persistedGrabbed: boolean;
  persistedPrintingScryfallId: string | null;
  persistedFoil: boolean | null;
};

type DraftCopyGroup = {
  key: string;
  copies: DraftCopy[];
  representative: DraftCopy;
};

type QuantityActionPrompt = {
  group: DraftCopyGroup;
  action: DraftAction;
  quantity: string;
};

type DraftCollectionRemoval = {
  card_scryfall_id: string;
  printing_scryfall_id: string | null;
  foil: boolean | null;
};

function normalizedColors(raw: string): string[] {
  const values = raw.trim().startsWith("[")
    ? (() => {
        try { return JSON.parse(raw) as unknown; } catch { return []; }
      })()
    : raw.split(",");
  return Array.isArray(values)
    ? values.map(String).map((value) => value.trim().toUpperCase()).filter((value) => COLOR_ORDER.includes(value))
    : [];
}

function draftColorSortKey(copy: DraftCopy): number {
  const colors = normalizedColors(copy.card.colors);
  if (colors.length === 1) return COLOR_ORDER.indexOf(colors[0] ?? "");
  if (colors.length > 1) return COLOR_ORDER.length;
  return COLOR_ORDER.length + 1;
}

function draftTypeCategory(copy: DraftCopy): string {
  const typeLine = copy.card.type_line ?? "";
  if (typeLine.includes("Legendary") && typeLine.includes("Creature")) return "Legendary Creature";
  if (typeLine.includes("Creature")) return "Creature";
  for (const category of TYPE_ORDER.slice(2, -1)) {
    if (typeLine.includes(category)) return category;
  }
  return "Other";
}

function adjustedManaValue(copy: DraftCopy): number {
  const variableSymbols = copy.card.mana_cost?.match(/\{X\}/gi)?.length ?? 0;
  return copy.card.cmc + variableSymbols;
}

function sortedDraftCopies(copies: DraftCopy[], mode: DeckSortMode): DraftCopy[] {
  return [...copies].sort((left, right) => {
    const primary = mode === "color"
      ? draftColorSortKey(left) - draftColorSortKey(right)
      : mode === "type"
        ? TYPE_ORDER.indexOf(draftTypeCategory(left)) - TYPE_ORDER.indexOf(draftTypeCategory(right))
        : 0;
    const manaValue = mode === "type" ? adjustedManaValue(left) - adjustedManaValue(right) : 0;
    return primary || manaValue || left.card.name.localeCompare(right.card.name) || left.key.localeCompare(right.key);
  });
}

function draftCopyBaseGroupKey(copy: DraftCopy): string {
  return `${copy.card.oracle_id}:${copy.isCommander ? "commander" : copy.isSideboard ? "sideboard" : "main"}`;
}

function draftCopyAction(copy: DraftCopy): DraftAction {
  return copy.addToCollection ? "added" : copy.status;
}

function draftActionLabel(action: DraftAction): string {
  if (action === "pending") return "Need";
  if (action === "proxy") return "Proxied";
  return action[0]?.toUpperCase() + action.slice(1);
}

function draftCopyGroupKey(copy: DraftCopy): string {
  return `${draftCopyBaseGroupKey(copy)}:${draftCopyAction(copy)}`;
}

function groupedDraftCopies(copies: DraftCopy[]): DraftCopyGroup[] {
  const groups = new Map<string, DraftCopyGroup>();
  const baseOrder = new Map<string, number>();
  for (const copy of copies) {
    const baseKey = draftCopyBaseGroupKey(copy);
    if (!baseOrder.has(baseKey)) baseOrder.set(baseKey, baseOrder.size);
    const key = draftCopyGroupKey(copy);
    const existing = groups.get(key);
    if (existing) {
      existing.copies.push(copy);
    } else {
      groups.set(key, { key, copies: [copy], representative: copy });
    }
  }
  const actionOrder: DraftAction[] = ["pending", "grabbed", "proxy", "added"];
  return [...groups.values()].sort((left, right) => {
    const leftBase = baseOrder.get(draftCopyBaseGroupKey(left.representative)) ?? 0;
    const rightBase = baseOrder.get(draftCopyBaseGroupKey(right.representative)) ?? 0;
    return leftBase - rightBase
      || actionOrder.indexOf(draftCopyAction(left.representative))
        - actionOrder.indexOf(draftCopyAction(right.representative));
  });
}

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
      persistedGrabbed: allocation.status === "grabbed",
      persistedPrintingScryfallId: allocation.status === "grabbed" ? allocation.scryfall_id : null,
      persistedFoil: allocation.status === "grabbed" ? allocation.foil : null,
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
  const [exporting, setExporting] = useState(false);
  const [pickList, setPickList] = useState<CardMatch[] | null>(null);
  const [draftCopies, setDraftCopies] = useState<DraftCopy[]>([]);
  const [draftDirty, setDraftDirty] = useState(false);
  const [sortMode, setSortMode] = useState<DeckSortMode>(() => {
    const saved = localStorage.getItem("spellbinder:deck-detail:sort");
    return saved === "type" || saved === "color" ? saved : "name";
  });
  const [collectionRemovals, setCollectionRemovals] = useState<DraftCollectionRemoval[]>([]);
  const [removalPrompt, setRemovalPrompt] = useState<DraftCopyGroup | null>(null);
  const [quantityActionPrompt, setQuantityActionPrompt] = useState<QuantityActionPrompt | null>(null);
  const [printingEditorKey, setPrintingEditorKey] = useState<string | null>(null);
  const [bulkSetCode, setBulkSetCode] = useState("");
  const [bulkSetBusy, setBulkSetBusy] = useState(false);
  const [bulkSetResult, setBulkSetResult] = useState<{
    setCode: string;
    changedCopies: number;
    missingNames: string[];
  } | null>(null);
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
      setCollectionRemovals([]);
      setRemovalPrompt(null);
      setQuantityActionPrompt(null);
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
    localStorage.setItem("spellbinder:deck-detail:sort", sortMode);
  }, [sortMode]);

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
        collection_removals: collectionRemovals,
      });
      setDeck(d);
      setDraftCopies(copiesFromDeck(d));
      setCommanderId(d.commander_scryfall_id ?? "");
      setDraftDirty(false);
      setCollectionRemovals([]);
      setRemovalPrompt(null);
      setQuantityActionPrompt(null);
      void refreshAnalysis(d.format);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  function applyDraftAction(copy: DraftCopy, action: DraftAction): DraftCopy {
    if (action === "added") {
      const printing = copy.printing ?? copy.card;
      const foil = copy.foil ?? false;
      return {
        ...copy,
        printingScryfallId: copy.printingScryfallId ?? copy.cardScryfallId,
        printing,
        status: "grabbed",
        foil,
        addToCollection: true,
        collectionAdditionId: copy.collectionAdditionId ?? randomUuid(),
      };
    }
    return {
      ...copy,
      status: action,
      addToCollection: false,
      collectionAdditionId: null,
    };
  }

  function setAllDraftStatuses(action: DraftAction) {
    if (draftCopies.length === 0) return;
    setDraftCopies((previous) => previous.map((copy) => applyDraftAction(copy, action)));
    setDraftDirty(true);
  }

  function applyActionToGroup(group: DraftCopyGroup, action: DraftAction, quantity: number) {
    const selectedKeys = new Set(
      group.copies.slice(0, Math.max(0, Math.min(quantity, group.copies.length))).map((copy) => copy.key),
    );
    if (selectedKeys.size === 0) return;
    setDraftCopies((previous) => previous.map((copy) => (
      selectedKeys.has(copy.key) ? applyDraftAction(copy, action) : copy
    )));
    setQuantityActionPrompt(null);
    setDraftDirty(true);
  }

  function requestGroupAction(group: DraftCopyGroup, action: DraftAction) {
    if (group.copies.length === 1) {
      applyActionToGroup(group, action, 1);
      return;
    }
    setQuantityActionPrompt({ group, action, quantity: "1" });
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
        persistedGrabbed: false,
        persistedPrintingScryfallId: null,
        persistedFoil: null,
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

  async function applySetPrintings() {
    const setCode = bulkSetCode.trim();
    if (!setCode || draftCopies.length === 0) return;
    if (!window.confirm(
      `Set every available deck card to its ${setCode.toUpperCase()} printing? Cards not printed in that set will stay unchanged.`,
    )) return;
    setBulkSetBusy(true);
    setBulkSetResult(null);
    setErr(null);
    try {
      const oracleIds = [...new Set(draftCopies.map((copy) => copy.card.oracle_id))];
      const result = await fetchBulkSetPrintings(setCode, oracleIds);
      const matches = new Map(result.matches.map((match) => [match.oracle_id, match]));
      const changedCopies = draftCopies.filter((copy) => matches.has(copy.card.oracle_id)).length;
      setDraftCopies((previous) => previous.map((copy) => {
        const match = matches.get(copy.card.oracle_id);
        if (!match) return copy;
        let foil = copy.foil;
        if (foil === true && !match.foil) foil = match.nonfoil ? false : null;
        else if (foil === false && !match.nonfoil) foil = match.foil ? true : null;
        else if (foil === null && match.foil !== match.nonfoil) foil = match.foil;
        return {
          ...copy,
          printingScryfallId: match.printing.scryfall_id,
          printing: match.printing,
          foil,
          addToCollection: false,
          collectionAdditionId: null,
        };
      }));
      const namesByOracle = new Map(
        draftCopies.map((copy) => [copy.card.oracle_id, copy.card.name]),
      );
      const missingNames = result.missing_oracle_ids
        .map((oracleId) => namesByOracle.get(oracleId) ?? oracleId)
        .sort((left, right) => left.localeCompare(right));
      const commanderMatch = draftCopies
        .filter((copy) => copy.isCommander)
        .map((copy) => matches.get(copy.card.oracle_id))
        .find((match) => match !== undefined);
      if (commanderMatch) setCommanderId(commanderMatch.printing.scryfall_id);
      setBulkSetResult({ setCode: result.set_code, changedCopies, missingNames });
      if (changedCopies > 0) setDraftDirty(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not apply set printings");
    } finally {
      setBulkSetBusy(false);
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
        persistedGrabbed: false,
        persistedPrintingScryfallId: null,
        persistedFoil: null,
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

  function removeCopies(group: DraftCopyGroup, removeFromCollection = false) {
    const keys = new Set(group.copies.map((copy) => copy.key));
    if (removeFromCollection) {
      const removals = group.copies
        .filter((copy) => copy.status === "grabbed" && copy.persistedGrabbed && !copy.addToCollection)
        .map((copy) => ({
          card_scryfall_id: copy.cardScryfallId,
          printing_scryfall_id: copy.persistedPrintingScryfallId,
          foil: copy.persistedFoil,
        }));
      setCollectionRemovals((previous) => [...previous, ...removals]);
    }
    setDraftCopies((previous) => previous.filter((copy) => !keys.has(copy.key)));
    if (group.copies.some((copy) => copy.isCommander)) setCommanderId("");
    setRemovalPrompt(null);
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

  async function exportDeck() {
    if (!deck || draftDirty) return;
    setErr(null);
    setExporting(true);
    try {
      await downloadDeckBackup(deck.id, deck.name);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Deck export failed");
    } finally {
      setExporting(false);
    }
  }

  if (!Number.isFinite(deckId)) {
    return <p className="text-stone-500">Invalid deck.</p>;
  }

  if (loading) return <p className="text-stone-500">Loading deck…</p>;
  if (!deck) return <p className="text-stone-500">Deck not found.</p>;

  const cards = sortedDraftCopies(draftCopies, sortMode);
  const groupedCards = groupedDraftCopies(cards);
  const uniqueCardCount = new Set(cards.map(draftCopyBaseGroupKey)).size;
  const cardGroups = sortMode === "type"
    ? TYPE_ORDER.map((category) => ({
        key: category,
        label: TYPE_SECTION_LABELS[category] ?? category,
        cards: groupedCards.filter((group) => draftTypeCategory(group.representative) === category),
      })).filter((group) => group.cards.length > 0)
    : [{ key: "all", label: null, cards: groupedCards }];
  const selectedDraftCopy = draftCopies.find((copy) => copy.key === printingEditorKey) ?? null;
  const selectedDraftGroup = selectedDraftCopy
    ? groupedCards.find((group) => group.key === draftCopyGroupKey(selectedDraftCopy)) ?? null
    : null;
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
            disabled={exporting || draftDirty}
            onClick={() => void exportDeck()}
            title={draftDirty ? "Save deck changes before exporting" : "Export this deck"}
            className="rounded-xl border border-arcane-400/30 bg-arcane-500/10 px-4 py-2 text-sm font-medium text-arcane-200 transition hover:bg-arcane-500/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {exporting ? "Exporting…" : "Export deck"}
          </button>
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
          <div className="mt-4 border-t border-white/10 pt-4">
            <label className="block text-xs text-stone-500">Set every card status</label>
            <p className="mt-1 text-[11px] leading-relaxed text-stone-600">
              Grabbed uses existing collection copies. Added creates new collection copies. Applies when you save.
            </p>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <button
                type="button"
                disabled={draftCopies.length === 0}
                onClick={() => setAllDraftStatuses("pending")}
                className="rounded-lg bg-amber-500/15 px-2 py-2 text-xs font-semibold text-amber-100 ring-1 ring-amber-400/20 disabled:opacity-40"
              >
                Need
              </button>
              <button
                type="button"
                disabled={draftCopies.length === 0}
                onClick={() => setAllDraftStatuses("grabbed")}
                className="rounded-lg bg-emerald-500/15 px-2 py-2 text-xs font-semibold text-emerald-100 ring-1 ring-emerald-400/20 disabled:opacity-40"
              >
                Grabbed
              </button>
              <button
                type="button"
                disabled={draftCopies.length === 0}
                onClick={() => setAllDraftStatuses("proxy")}
                className="rounded-lg bg-violet-500/15 px-2 py-2 text-xs font-semibold text-violet-100 ring-1 ring-violet-400/20 disabled:opacity-40"
              >
                Proxied
              </button>
              <button
                type="button"
                disabled={draftCopies.length === 0}
                onClick={() => setAllDraftStatuses("added")}
                className="rounded-lg bg-sky-500/15 px-2 py-2 text-xs font-semibold text-sky-100 ring-1 ring-sky-400/20 disabled:opacity-40"
              >
                Added
              </button>
            </div>
          </div>
          <div className="mt-4 border-t border-white/10 pt-4">
            <label className="block text-xs text-stone-500">Set every available printing</label>
            <p className="mt-1 text-[11px] leading-relaxed text-stone-600">
              Enter a set code such as SCD. Cards without a printing in that set are left unchanged.
            </p>
            <div className="mt-2 flex gap-2">
              <input
                value={bulkSetCode}
                onChange={(event) => {
                  setBulkSetCode(event.target.value.toUpperCase());
                  setBulkSetResult(null);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void applySetPrintings();
                }}
                maxLength={8}
                placeholder="SCD"
                className="min-w-0 flex-1 rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 font-mono text-sm uppercase"
              />
              <button
                type="button"
                disabled={bulkSetBusy || !bulkSetCode.trim() || draftCopies.length === 0}
                onClick={() => void applySetPrintings()}
                className="rounded-xl bg-arcane-500/15 px-3 py-2 text-xs font-medium text-arcane-100 ring-1 ring-arcane-400/25 disabled:opacity-40"
              >
                {bulkSetBusy ? "Applying…" : "Apply"}
              </button>
            </div>
            {bulkSetResult && (
              <div className="mt-3 rounded-xl border border-white/10 bg-ink-950/40 p-3 text-xs">
                <p className="text-emerald-300">
                  Set {bulkSetResult.changedCopies} {bulkSetResult.changedCopies === 1 ? "copy" : "copies"} to {bulkSetResult.setCode}.
                </p>
                {bulkSetResult.missingNames.length > 0 && (
                  <details className="mt-2 text-amber-300">
                    <summary className="cursor-pointer">
                      {bulkSetResult.missingNames.length} {bulkSetResult.missingNames.length === 1 ? "card has" : "cards have"} no {bulkSetResult.setCode} printing
                    </summary>
                    <ul className="mt-2 max-h-36 space-y-1 overflow-y-auto border-l border-amber-500/20 pl-3 text-stone-400">
                      {bulkSetResult.missingNames.map((name) => <li key={name}>{name}</li>)}
                    </ul>
                  </details>
                )}
              </div>
            )}
          </div>
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
            <div className="flex flex-wrap items-end justify-between gap-3">
              <h3 className="font-display text-2xl text-stone-100">Main list</h3>
              <div className="flex items-center gap-3">
                <span className="text-sm text-stone-500">{cards.length} cards · {uniqueCardCount} unique</span>
                <label className="text-xs font-medium uppercase tracking-wider text-stone-500">
                  Sort
                  <select
                    value={sortMode}
                    onChange={(event) => setSortMode(event.target.value as DeckSortMode)}
                    className="ml-2 rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs normal-case tracking-normal text-stone-300"
                  >
                    <option value="name">Alphabetical</option>
                    <option value="type">Card type</option>
                    <option value="color">Color · WUBRG</option>
                  </select>
                </label>
              </div>
            </div>
            {cards.length === 0 ? (
              <div className="mt-3 rounded-2xl border border-dashed border-white/10 px-6 py-10 text-center text-sm text-stone-500">
                No cards — stage cards from the section above.
              </div>
            ) : (
              <div className="mt-3 space-y-6">
                {cardGroups.map((cardGroup) => (
                  <section key={cardGroup.key}>
                    {cardGroup.label && (
                      <div className="flex items-center gap-3 border-b border-white/10 pb-2">
                        <h4 className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-300">{cardGroup.label}</h4>
                        <span className="text-xs text-stone-600">
                          {cardGroup.cards.reduce((total, group) => total + group.copies.length, 0)} cards · {new Set(cardGroup.cards.map((group) => draftCopyBaseGroupKey(group.representative))).size} unique
                        </span>
                      </div>
                    )}
                    <div className={`${cardGroup.label ? "mt-3 " : ""}grid grid-cols-[repeat(auto-fill,minmax(155px,1fr))] gap-3 sm:grid-cols-[repeat(auto-fill,minmax(175px,1fr))] 2xl:grid-cols-[repeat(auto-fill,minmax(190px,1fr))]`}>
                {cardGroup.cards.map((copyGroup) => {
                  const copy = copyGroup.representative;
                  const displayed = copy.printing ?? copy.card;
                  const printingCount = new Set(copyGroup.copies.map((groupCopy) => (
                    `${groupCopy.printingScryfallId ?? "any"}:${String(groupCopy.foil)}`
                  ))).size;
                  const statusSummary = [
                    ["Need", copyGroup.copies.filter((groupCopy) => groupCopy.status === "pending").length],
                    ["Grabbed", copyGroup.copies.filter((groupCopy) => groupCopy.status === "grabbed" && !groupCopy.addToCollection).length],
                    ["Proxied", copyGroup.copies.filter((groupCopy) => groupCopy.status === "proxy").length],
                    ["Added", copyGroup.copies.filter((groupCopy) => groupCopy.addToCollection).length],
                  ].filter(([, count]) => Number(count) > 0);
                  const allAdded = copyGroup.copies.every((groupCopy) => groupCopy.addToCollection);
                  const allGrabbed = copyGroup.copies.every((groupCopy) => groupCopy.status === "grabbed" && !groupCopy.addToCollection);
                  const allProxied = copyGroup.copies.every((groupCopy) => groupCopy.status === "proxy" && !groupCopy.addToCollection);
                  return (
                    <article key={copyGroup.key} className={`overflow-hidden rounded-xl border bg-ink-900/65 shadow-card ${
                      allAdded ? "border-sky-500/30" : allGrabbed ? "border-emerald-500/25" : allProxied ? "border-violet-500/30" : "border-white/10"
                    }`}>
                      <CardHoverPreview src={displayed.image_uri_normal} name={copy.card.name}>
                        <button type="button" onClick={() => setPrintingEditorKey(copy.key)} className="relative block aspect-[5/7] w-full overflow-hidden bg-ink-800">
                          {displayed.image_uri_normal ? (
                            <img src={displayed.image_uri_normal} alt={copy.card.name} className="h-full w-full object-cover" loading="lazy" />
                          ) : (
                            <span className="flex h-full items-center justify-center p-3 text-xs text-stone-500">{copy.card.name}</span>
                          )}
                          {copy.isCommander && <span className="absolute left-2 top-2 rounded-full bg-black/80 px-2 py-1 text-[10px] font-semibold text-arcane-200">Commander</span>}
                          {copyGroup.copies.length > 1 && (
                            <span className="absolute right-2 top-2 rounded-full bg-black/80 px-2 py-1 text-xs font-bold text-stone-100">×{copyGroup.copies.length}</span>
                          )}
                          {allAdded && <span className="absolute bottom-2 left-2 rounded-full bg-sky-950/90 px-2 py-1 text-[10px] font-semibold text-sky-200">New collection copies</span>}
                        </button>
                      </CardHoverPreview>
                      <div className="space-y-1 p-3">
                        <button type="button" onClick={() => setPrintingEditorKey(copy.key)} className="line-clamp-2 text-left text-sm font-medium leading-tight text-stone-100 hover:text-ember-200">
                          {copy.card.name}
                        </button>
                        <p className="truncate text-[10px] text-stone-500">
                          {printingCount > 1
                            ? "Multiple printings"
                            : [displayed.set_code?.toUpperCase(), displayed.collector_number, copy.foil ? "Foil" : null].filter(Boolean).join(" · ") || copy.card.type_line || "Any printing"}
                        </p>
                        <p className="truncate text-[10px] text-stone-500">
                          {statusSummary.map(([label, count]) => `${label} ${count}`).join(" · ")}
                        </p>
                        <button
                          type="button"
                          onClick={() => setPrintingEditorKey(copy.key)}
                          className="mt-2 w-full rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[9px] font-semibold uppercase tracking-wide text-stone-400 hover:border-emerald-400/30 hover:bg-emerald-500/10 hover:text-emerald-200"
                        >
                          Change printing{copyGroup.copies.length > 1 ? " for all" : ""}
                        </button>
                        <div className="grid grid-cols-5 gap-1 pt-2">
                          {(["pending", "grabbed", "proxy", "added"] as const).map((action) => {
                            const selected = action === "added"
                              ? copyGroup.copies.every((groupCopy) => groupCopy.addToCollection)
                              : copyGroup.copies.every((groupCopy) => !groupCopy.addToCollection && groupCopy.status === action);
                            return (
                            <button
                              key={action}
                              type="button"
                              disabled={selected}
                              onClick={() => requestGroupAction(copyGroup, action)}
                              className={`rounded-md px-1 py-1 text-[9px] font-semibold uppercase tracking-wide ${
                                selected
                                  ? action === "grabbed" ? "bg-emerald-500/25 text-emerald-100" : action === "proxy" ? "bg-violet-500/25 text-violet-100" : action === "added" ? "bg-sky-500/25 text-sky-100" : "bg-amber-500/20 text-amber-100"
                                  : "bg-white/5 text-stone-500 hover:bg-white/10 hover:text-stone-200"
                              }`}
                            >
                              {action === "pending" ? "Need" : action}
                            </button>
                            );
                          })}
                          <button
                            type="button"
                            onClick={() => {
                              if (copyGroup.copies.some((groupCopy) => groupCopy.status === "grabbed" && groupCopy.persistedGrabbed && !groupCopy.addToCollection)) {
                                setRemovalPrompt(copyGroup);
                              } else {
                                removeCopies(copyGroup);
                              }
                            }}
                            className="rounded-md bg-red-500/10 px-1 py-1 text-[9px] font-semibold uppercase tracking-wide text-red-300 hover:bg-red-500/20"
                          >
                            {copyGroup.copies.length > 1 ? `Delete ×${copyGroup.copies.length}` : "Delete"}
                          </button>
                        </div>
                      </div>
                    </article>
                  );
                })}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      {selectedModalCard && selectedDraftCopy && selectedDraftGroup && (
        <DeckPrintingModal
          deckId={deck.id}
          deckCard={selectedModalCard}
          allowCommanderSelection={["commander", "edh"].includes(deck.format.toLowerCase())}
          currentCommanderName={draftCopies.find((copy) => copy.isCommander)?.card.name ?? null}
          onClose={() => setPrintingEditorKey(null)}
          onDraftSaved={(updatedCard) => {
            const allocation = updatedCard.allocations[0];
            const groupKeys = new Set(selectedDraftGroup.copies.map((copy) => copy.key));
            setDraftCopies((previous) => previous.map((copy) => groupKeys.has(copy.key) ? {
                ...copy,
                printingScryfallId: allocation?.scryfall_id ?? null,
                printing: allocation?.printing ?? null,
                foil: allocation?.foil ?? null,
                status: allocation?.status ?? copy.status,
                addToCollection: Boolean(
                  copy.addToCollection
                  && allocation?.scryfall_id === copy.printingScryfallId
                ),
                collectionAdditionId: (
                  copy.addToCollection
                  && allocation?.scryfall_id === copy.printingScryfallId
                ) ? copy.collectionAdditionId : null,
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
          onDraftPrintingAdded={(card, foil) => {
            const groupKeys = new Set(selectedDraftGroup.copies.map((copy) => copy.key));
            setDraftCopies((previous) => previous.map((copy) => (
              groupKeys.has(copy.key)
                ? {
                    ...copy,
                    printingScryfallId: card.scryfall_id,
                    printing: card,
                    status: "grabbed" as const,
                    foil,
                    addToCollection: true,
                    collectionAdditionId: randomUuid(),
                  }
                : copy
            )));
            if (selectedDraftCopy.isCommander) setCommanderId(card.scryfall_id);
            setDraftDirty(true);
            setPrintingEditorKey(null);
          }}
        />
      )}
      {quantityActionPrompt && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/75 p-4" role="dialog" aria-modal="true" aria-labelledby="quantity-action-title">
          <form
            className="w-full max-w-sm rounded-2xl border border-white/10 bg-ink-900 p-6 shadow-2xl"
            onSubmit={(event) => {
              event.preventDefault();
              applyActionToGroup(
                quantityActionPrompt.group,
                quantityActionPrompt.action,
                Number.parseInt(quantityActionPrompt.quantity, 10),
              );
            }}
          >
            <h2 id="quantity-action-title" className="font-display text-2xl text-stone-100">
              Mark as {draftActionLabel(quantityActionPrompt.action)}
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-stone-400">
              How many of the {quantityActionPrompt.group.copies.length} {quantityActionPrompt.group.representative.card.name} copies should move from {draftActionLabel(draftCopyAction(quantityActionPrompt.group.representative))} to {draftActionLabel(quantityActionPrompt.action)}?
            </p>
            <label className="mt-5 block text-xs font-medium uppercase tracking-wider text-stone-500">
              Quantity
              <input
                type="number"
                min={1}
                max={quantityActionPrompt.group.copies.length}
                step={1}
                autoFocus
                value={quantityActionPrompt.quantity}
                onChange={(event) => setQuantityActionPrompt({
                  ...quantityActionPrompt,
                  quantity: event.target.value,
                })}
                className="mt-2 w-full rounded-xl border border-white/10 bg-ink-950/60 px-3 py-2 text-base text-stone-100"
              />
            </label>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setQuantityActionPrompt(null)}
                className="rounded-xl border border-white/10 px-4 py-2 text-sm text-stone-300 hover:bg-white/5"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={
                  !Number.isInteger(Number(quantityActionPrompt.quantity))
                  || Number(quantityActionPrompt.quantity) < 1
                  || Number(quantityActionPrompt.quantity) > quantityActionPrompt.group.copies.length
                }
                className="rounded-xl bg-ember-500/20 px-4 py-2 text-sm font-medium text-ember-100 ring-1 ring-ember-400/30 disabled:opacity-40"
              >
                Apply
              </button>
            </div>
          </form>
        </div>
      )}
      {removalPrompt && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/75 p-4" role="dialog" aria-modal="true" aria-labelledby="remove-deck-copy-title">
          <div className="w-full max-w-md rounded-2xl border border-white/10 bg-ink-900 p-6 shadow-2xl">
            <h2 id="remove-deck-copy-title" className="font-display text-2xl text-stone-100">
              Remove {removalPrompt.copies.length > 1 ? `${removalPrompt.copies.length} copies of ` : ""}{removalPrompt.representative.card.name}?
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-stone-400">
              {removalPrompt.copies.filter((copy) => copy.status === "grabbed" && copy.persistedGrabbed && !copy.addToCollection).length} of these copies {removalPrompt.copies.filter((copy) => copy.status === "grabbed" && copy.persistedGrabbed && !copy.addToCollection).length === 1 ? "is" : "are"} currently grabbed from your collection. Choose whether to return those physical copies to bulk inventory or remove them from your collection entirely.
            </p>
            <div className="mt-6 grid gap-3">
              <button
                type="button"
                onClick={() => removeCopies(removalPrompt)}
                className="rounded-xl bg-emerald-500/15 px-4 py-3 text-left text-sm font-medium text-emerald-100 ring-1 ring-emerald-400/25 hover:bg-emerald-500/20"
              >
                Return to bulk
                <span className="mt-1 block text-xs font-normal text-emerald-200/65">Remove it from this deck but keep it in your collection.</span>
              </button>
              <button
                type="button"
                onClick={() => removeCopies(removalPrompt, true)}
                className="rounded-xl bg-red-500/15 px-4 py-3 text-left text-sm font-medium text-red-100 ring-1 ring-red-400/25 hover:bg-red-500/20"
              >
                Remove from collection
                <span className="mt-1 block text-xs font-normal text-red-200/65">Use this if the card was sold, given away, or entered by mistake.</span>
              </button>
              <button
                type="button"
                onClick={() => setRemovalPrompt(null)}
                className="rounded-xl border border-white/10 px-4 py-2 text-sm text-stone-300 hover:bg-white/5"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
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
