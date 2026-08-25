import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  DeckbuildingResponse,
  DraftValidation,
  RecommendationDraftEntry,
  auditDeck,
  buildDeckFromTheme,
  saveRecommendationDraft,
  submitRecommendationFeedback,
  suggestDeckAdditions,
  validateRecommendationDraft,
} from "../api";

type Mode = "build" | "suggest" | "audit";

const VIABILITY_STYLES: Record<string, string> = {
  strong:       "bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/30",
  playable:     "bg-blue-500/20 text-blue-300 ring-1 ring-blue-500/30",
  weak:         "bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/30",
  insufficient: "bg-red-500/20 text-red-300 ring-1 ring-red-500/30",
};

function ViabilityBadge({ v }: { v: string }) {
  return (
    <span className={`rounded-full px-3 py-1 text-xs font-semibold capitalize ${VIABILITY_STYLES[v] ?? "bg-stone-700/40 text-stone-300"}`}>
      {v}
    </span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-stone-500">{title}</h3>
      {children}
    </div>
  );
}

function CardList({ items, className = "" }: { items: string[]; className?: string }) {
  return (
    <ul className={`space-y-1 ${className}`}>
      {items.map((item, i) => (
        <li key={i} className="text-sm text-stone-300">{item}</li>
      ))}
    </ul>
  );
}

function draftText(entries: RecommendationDraftEntry[]): string {
  return [...entries]
    .sort((a, b) => Number(b.is_commander) - Number(a.is_commander) || a.name.localeCompare(b.name))
    .map((entry) => `${entry.quantity} ${entry.name}`)
    .join("\n");
}

function validationErrorText(error: DraftValidation["errors"][number]): string {
  const details = Object.entries(error)
    .filter(([key]) => key !== "code")
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join(" · ");
  return details ? `${error.code} · ${details}` : error.code;
}

function DraftWorkspace({ resp }: { resp: DeckbuildingResponse }) {
  const optimizer = resp.result.optimizer;
  const runId = resp.recommendation_run_id;
  const options = resp.candidate_options ?? [];
  const initialEntries = useMemo<RecommendationDraftEntry[]>(() => (
    optimizer?.entries.map(({ scryfall_id, oracle_id, name, quantity, is_commander }) => ({
      scryfall_id, oracle_id, name, quantity, is_commander,
    })) ?? []
  ), [optimizer]);
  const [entries, setEntries] = useState<RecommendationDraftEntry[]>(initialEntries);
  const [validation, setValidation] = useState<DraftValidation | null>(optimizer?.validation ?? null);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [addOracleId, setAddOracleId] = useState("");
  const [deckName, setDeckName] = useState(`Recommended — ${optimizer?.commander ?? "Commander Deck"}`);
  const [savedDeck, setSavedDeck] = useState<{ id: number; name: string } | null>(null);
  const [rating, setRating] = useState(4);
  const [feedbackNotes, setFeedbackNotes] = useState("");
  const [feedbackSent, setFeedbackSent] = useState(false);

  const selectedIds = useMemo(() => new Set(entries.map((entry) => entry.oracle_id)), [entries]);
  const remainingOptions = options.filter((option) => !selectedIds.has(option.oracle_id));
  const optionById = useMemo(() => new Map(options.map((option) => [option.oracle_id, option])), [options]);
  const total = entries.reduce((sum, entry) => sum + entry.quantity, 0);
  const changed = JSON.stringify(entries) !== JSON.stringify(initialEntries);

  function dirty(next: RecommendationDraftEntry[]) {
    setEntries(next);
    setValidation(null);
    setMessage(null);
  }

  function updateEntry(oracleId: string, patch: Partial<RecommendationDraftEntry>) {
    dirty(entries.map((entry) => entry.oracle_id === oracleId ? { ...entry, ...patch } : entry));
  }

  function makeCommander(oracleId: string) {
    dirty(entries.map((entry) => ({ ...entry, is_commander: entry.oracle_id === oracleId })));
  }

  function addCandidate() {
    const option = optionById.get(addOracleId);
    if (!option) return;
    dirty([...entries, {
      scryfall_id: option.scryfall_id,
      oracle_id: option.oracle_id,
      name: option.name,
      quantity: 1,
      is_commander: false,
    }]);
    setAddOracleId("");
  }

  async function validateDraft() {
    if (!runId) return;
    setWorking(true);
    setMessage(null);
    try {
      const result = await validateRecommendationDraft(runId, entries);
      setValidation(result.validation);
      setMessage(result.validation.valid ? "Draft passes every hard constraint." : "Fix the failed constraints before saving.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Validation failed");
    } finally {
      setWorking(false);
    }
  }

  async function saveDraft() {
    if (!runId || !validation?.valid || !deckName.trim()) return;
    setWorking(true);
    setMessage(null);
    try {
      const saved = await saveRecommendationDraft(runId, deckName.trim(), entries, {
        rating,
        notes: feedbackNotes.trim() || undefined,
      });
      setSavedDeck({ id: saved.deck.id, name: saved.deck.name });
      setFeedbackSent(true);
      setMessage("Saved to your Spellbinder decks. This also recorded the selected cards as positive feedback.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save deck");
    } finally {
      setWorking(false);
    }
  }

  async function sendFeedback(outcome: "accepted" | "edited" | "rejected") {
    if (!runId) return;
    setWorking(true);
    setMessage(null);
    try {
      await submitRecommendationFeedback(runId, {
        outcome,
        rating,
        notes: feedbackNotes.trim() || undefined,
        entries,
      });
      setFeedbackSent(true);
      setMessage("Feedback saved. Future candidate scores will show this preference signal.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save feedback");
    } finally {
      setWorking(false);
    }
  }

  if (!optimizer || !runId) return null;

  return (
    <Section title="Editable deck workspace">
      <div className="space-y-4 rounded-xl border border-white/10 bg-ink-950/35 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-stone-200">{total} / 100 cards · {entries.length} distinct entries</p>
            <p className="text-xs text-stone-500">Edits are checked against the original bounded pool and your current collection.</p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void navigator.clipboard.writeText(draftText(entries))}
              className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs text-stone-300 hover:bg-ink-700"
            >
              Copy draft
            </button>
            <button
              type="button"
              onClick={() => dirty(initialEntries)}
              disabled={!changed || working}
              className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs text-stone-300 disabled:opacity-40"
            >
              Reset
            </button>
          </div>
        </div>

        <div className="max-h-[32rem] overflow-y-auto rounded-lg border border-white/5">
          {entries.map((entry) => {
            const option = optionById.get(entry.oracle_id);
            return (
              <div key={entry.oracle_id} className="border-b border-white/5 bg-ink-900/50 px-3 py-2 last:border-0">
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min={1}
                    max={option?.owned_quantity ?? 999}
                    value={entry.quantity}
                    onChange={(event) => updateEntry(entry.oracle_id, { quantity: Math.max(1, Number(event.target.value) || 1) })}
                    className="w-16 rounded border border-white/10 bg-ink-800 px-2 py-1 text-xs text-stone-200"
                  />
                  <button
                    type="button"
                    onClick={() => makeCommander(entry.oracle_id)}
                    className={`rounded px-2 py-1 text-[10px] ${
                      entry.is_commander ? "bg-ember-500/20 text-ember-300" : "bg-ink-800 text-stone-600 hover:text-stone-300"
                    }`}
                  >
                    {entry.is_commander ? "Commander" : "Make commander"}
                  </button>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-stone-200">{entry.name}</p>
                    <p className="truncate text-[10px] text-stone-600">
                      {option?.type_line} · owned {option?.owned_quantity ?? "?"} · score {option?.retrieval.total_score.toFixed(2) ?? "?"}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => dirty(entries.filter((item) => item.oracle_id !== entry.oracle_id))}
                    className="rounded px-2 py-1 text-xs text-stone-600 hover:bg-red-500/10 hover:text-red-300"
                  >
                    Remove
                  </button>
                </div>
                {option && (option.deterministic_roles.length > 0 || option.structured_roles.length > 0) && (
                  <p className="mt-1 pl-20 text-[10px] text-stone-500">
                    {[...new Set([...option.deterministic_roles, ...option.structured_roles])].join(" · ")}
                  </p>
                )}
                {option && (
                  <details className="mt-1 pl-20 text-[10px] text-stone-500">
                    <summary className="cursor-pointer hover:text-stone-300">Inspect score and reasons</summary>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {Object.entries(option.retrieval.components)
                        .filter(([, value]) => value !== 0)
                        .map(([component, value]) => (
                          <span key={component} className="rounded bg-ink-700/70 px-1.5 py-0.5 font-mono">
                            {component} {value > 0 ? "+" : ""}{value.toFixed(2)}
                          </span>
                        ))}
                    </div>
                    {option.retrieval.reasons.map((reason, index) => (
                      <p key={index} className="mt-1">{reason}</p>
                    ))}
                  </details>
                )}
              </div>
            );
          })}
        </div>

        <div className="flex gap-2">
          <select
            value={addOracleId}
            onChange={(event) => setAddOracleId(event.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs text-stone-300"
          >
            <option value="">Add another card from the bounded candidate pool…</option>
            {remainingOptions.map((option) => (
              <option key={option.oracle_id} value={option.oracle_id}>
                {option.name} · owned {option.owned_quantity} · score {option.retrieval.total_score.toFixed(2)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={addCandidate}
            disabled={!addOracleId}
            className="rounded-lg bg-arcane-500/20 px-4 py-2 text-xs text-arcane-300 ring-1 ring-arcane-500/30 disabled:opacity-40"
          >
            Add card
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={validateDraft}
            disabled={working || entries.length === 0}
            className="rounded-lg bg-ember-500/20 px-4 py-2 text-xs font-medium text-ember-300 ring-1 ring-ember-500/30 disabled:opacity-40"
          >
            {working ? "Working…" : "Validate edited draft"}
          </button>
          {validation && (
            <span className={`text-xs ${validation.valid ? "text-emerald-300" : "text-red-300"}`}>
              {validation.valid ? "All hard constraints pass" : `${validation.errors.length} hard-constraint error(s)`}
            </span>
          )}
        </div>
        {validation && !validation.valid && (
          <div className="flex flex-wrap gap-1">
            {validation.errors.map((error, index) => (
              <span key={`${error.code}-${index}`} className="rounded bg-red-500/10 px-2 py-1 font-mono text-[10px] text-red-300">
                {validationErrorText(error)}
              </span>
            ))}
          </div>
        )}

        <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
          <input
            value={deckName}
            onChange={(event) => setDeckName(event.target.value)}
            maxLength={200}
            className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm text-stone-200"
            placeholder="Deck name"
          />
          <button
            type="button"
            onClick={saveDraft}
            disabled={working || !validation?.valid || !deckName.trim() || Boolean(savedDeck)}
            className="rounded-lg bg-emerald-500/20 px-5 py-2 text-sm font-medium text-emerald-300 ring-1 ring-emerald-500/30 disabled:opacity-40"
          >
            {savedDeck ? "Saved" : "Save to my decks"}
          </button>
        </div>
        {savedDeck && (
          <Link to={`/decks/${savedDeck.id}`} className="inline-block text-sm text-emerald-300 hover:underline">
            Open {savedDeck.name} →
          </Link>
        )}

        <div className="border-t border-white/5 pt-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-stone-500">Improve future recommendations</p>
          <p className="mt-1 text-xs text-stone-500">
            Explicit feedback changes a visible per-card preference score; it does not rewrite card mechanics.
          </p>
          <div className="mt-3 grid gap-2 sm:grid-cols-[auto_1fr]">
            <select
              value={rating}
              onChange={(event) => setRating(Number(event.target.value))}
              className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs text-stone-300"
            >
              {[5, 4, 3, 2, 1].map((value) => <option key={value} value={value}>{value} / 5</option>)}
            </select>
            <input
              value={feedbackNotes}
              onChange={(event) => setFeedbackNotes(event.target.value)}
              placeholder="What worked, what did not, or what you changed…"
              maxLength={10_000}
              className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-xs text-stone-300"
            />
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" onClick={() => sendFeedback(changed ? "edited" : "accepted")} disabled={working || feedbackSent} className="rounded bg-emerald-500/15 px-3 py-1.5 text-xs text-emerald-300 disabled:opacity-40">
              {changed ? "Submit edited draft" : "Accept recommendation"}
            </button>
            <button type="button" onClick={() => sendFeedback("rejected")} disabled={working || feedbackSent} className="rounded bg-red-500/10 px-3 py-1.5 text-xs text-red-300 disabled:opacity-40">
              Reject recommendation
            </button>
          </div>
        </div>

        {message && <p className="text-xs text-stone-400">{message}</p>}
      </div>
    </Section>
  );
}

function ResultPanel({ resp }: { resp: DeckbuildingResponse }) {
  const { result, warnings, pool_size, retrieval } = resp;
  const [copied, setCopied] = useState(false);

  function copyDecklist() {
    if (result.decklist) {
      void navigator.clipboard.writeText(result.decklist);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }

  return (
    <div className="space-y-6 rounded-2xl border border-white/10 bg-ink-900/60 p-6">
      {/* Header row */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {result.viability && <ViabilityBadge v={result.viability} />}
          {result.overall_assessment && (
            <span className="text-sm font-medium text-stone-200">{result.overall_assessment}</span>
          )}
          {result.commander && (
            <span className="rounded-full bg-ember-500/15 px-3 py-1 text-xs font-medium text-ember-300 ring-1 ring-ember-500/25">
              Commander: {result.commander}
            </span>
          )}
        </div>
        <span className="text-xs text-stone-600">{pool_size} cards in candidate pool</span>
      </div>

      {/* Viability note */}
      {result.viability_note && (
        <div className="rounded-xl border border-white/5 bg-ink-800/50 px-4 py-3 text-sm text-stone-300">
          {result.viability_note}
        </div>
      )}

      {/* Validation warnings */}
      {warnings.length > 0 && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 space-y-1">
          <p className="text-xs font-semibold uppercase tracking-wider text-amber-400">Validation warnings</p>
          {warnings.map((w, i) => (
            <p key={i} className="text-sm text-amber-300">{w}</p>
          ))}
        </div>
      )}

      {result.optimizer && (
        <div className={`rounded-xl border px-4 py-3 ${
          result.optimizer.validation.valid
            ? "border-emerald-500/25 bg-emerald-500/10"
            : "border-red-500/30 bg-red-500/10"
        }`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className={`text-xs font-semibold uppercase tracking-wider ${
              result.optimizer.validation.valid ? "text-emerald-300" : "text-red-300"
            }`}>
              Deterministic optimizer {result.optimizer.version} · {result.optimizer.validation.valid ? "hard constraints passed" : "infeasible"}
            </p>
            <span className="font-mono text-xs text-stone-400">
              objective {result.optimizer.objective_score.toFixed(2)}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {Object.entries(result.optimizer.validation.checks).map(([check, passed]) => (
              <span
                key={check}
                className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                  passed ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300"
                }`}
              >
                {passed ? "✓" : "✗"} {check}
              </span>
            ))}
          </div>
          {result.reasoning_provenance && (
            <p className="mt-2 text-xs text-stone-500">
              Strategy proposed by {result.reasoning_provenance.provider}:{result.reasoning_provenance.model}; final card selection performed by code.
            </p>
          )}
        </div>
      )}

      {result.review_provenance && (
        <div className="rounded-xl border border-white/5 bg-ink-800/50 px-4 py-3 text-xs text-stone-400">
          Review produced by <span className="font-mono text-stone-300">
            {result.review_provenance.provider}:{result.review_provenance.model}
          </span>
          {result.review_provenance.provider === "deterministic" && (
            <span> · paid model calls are disabled or unavailable</span>
          )}
        </div>
      )}

      {result.optimizer && result.optimizer.package_report.length > 0 && (
        <Section title="Strategic packages">
          <div className="grid gap-2 sm:grid-cols-2">
            {result.optimizer.package_report.map((pkg) => (
              <div key={pkg.name} className="rounded-lg border border-white/5 bg-ink-800/50 px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium text-stone-200">{pkg.name}</p>
                  <span className={`text-xs ${pkg.minimum_satisfied ? "text-emerald-300" : "text-amber-300"}`}>
                    {pkg.included_count}/{pkg.minimum_cards} minimum
                  </span>
                </div>
                <p className="mt-1 text-xs text-stone-400">{pkg.purpose}</p>
                <p className="mt-1 text-xs text-stone-600">{pkg.included_cards.join(", ")}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {result.optimizer && resp.recommendation_run_id && (
        <DraftWorkspace key={resp.recommendation_run_id} resp={resp} />
      )}

      {retrieval.candidates.length > 0 && (
        <details className="rounded-xl border border-white/5 bg-ink-800/40 px-4 py-3">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-stone-400">
            Why these candidates ranked highest · scorer {retrieval.version}
          </summary>
          <div className="mt-3 space-y-3">
            {retrieval.candidates.slice(0, 10).map((candidate) => (
              <div key={candidate.name} className="border-t border-white/5 pt-3 first:border-0 first:pt-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium text-stone-200">
                    {candidate.name} <span className="text-xs font-normal text-stone-600">×{candidate.owned_quantity}</span>
                  </p>
                  <span className="font-mono text-xs text-ember-300">{candidate.total_score.toFixed(2)}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {Object.entries(candidate.components)
                    .filter(([, value]) => value !== 0)
                    .map(([component, value]) => (
                      <span key={component} className="rounded bg-ink-700/70 px-1.5 py-0.5 font-mono text-[10px] text-stone-400">
                        {component} {value > 0 ? "+" : ""}{value.toFixed(2)}
                      </span>
                    ))}
                </div>
                {candidate.reasons.slice(0, 2).map((reason, index) => (
                  <p key={index} className="mt-1 text-xs text-stone-500">{reason}</p>
                ))}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Reasoning / strategy */}
      {(result.reasoning || result.strategy_assessment || result.theme_assessment) && (
        <Section title="Analysis">
          <p className="whitespace-pre-line text-sm leading-relaxed text-stone-300">
            {result.reasoning ?? result.strategy_assessment ?? result.theme_assessment}
          </p>
        </Section>
      )}

      {/* Key synergies */}
      {result.key_synergies && result.key_synergies.length > 0 && (
        <Section title="Key synergies">
          <CardList items={result.key_synergies} />
        </Section>
      )}

      {/* Strengths + Weaknesses */}
      {(result.strengths || result.weaknesses) && (
        <div className="grid gap-4 sm:grid-cols-2">
          {result.strengths && result.strengths.length > 0 && (
            <Section title="Strengths">
              <CardList items={result.strengths} className="text-emerald-300/80" />
            </Section>
          )}
          {result.weaknesses && result.weaknesses.length > 0 && (
            <Section title="Weaknesses">
              <CardList items={result.weaknesses} className="text-amber-300/80" />
            </Section>
          )}
        </div>
      )}

      {/* Suggest mode: suggestions + cuts */}
      {result.suggestions && result.suggestions.length > 0 && (
        <Section title="Suggested additions">
          <div className="space-y-2">
            {result.suggestions.map((s, i) => (
              <div key={i} className="rounded-lg bg-ink-800/50 px-4 py-3">
                <p className="text-sm font-medium text-stone-200">{s.name}</p>
                <p className="mt-0.5 text-xs text-stone-400">{s.reason}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {result.cards_to_consider_cutting && result.cards_to_consider_cutting.length > 0 && (
        <Section title="Consider cutting">
          <div className="space-y-2">
            {result.cards_to_consider_cutting.map((s, i) => (
              <div key={i} className="rounded-lg bg-ink-800/50 px-4 py-3">
                <p className="text-sm font-medium text-stone-200">{s.name}</p>
                <p className="mt-0.5 text-xs text-stone-400">{s.reason}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Audit mode: cuts + additions */}
      {result.suggested_cuts && result.suggested_cuts.length > 0 && (
        <Section title="Suggested cuts">
          <div className="space-y-2">
            {result.suggested_cuts.map((s, i) => (
              <div key={i} className="rounded-lg bg-ink-800/50 px-4 py-3">
                <p className="text-sm font-medium text-stone-200">{s.name}</p>
                <p className="mt-0.5 text-xs text-stone-400">{s.reason}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {result.suggested_additions && result.suggested_additions.length > 0 && (
        <Section title="Suggested additions">
          <div className="space-y-2">
            {result.suggested_additions.map((s, i) => (
              <div key={i} className="rounded-lg bg-ink-800/50 px-4 py-3">
                <p className="text-sm font-medium text-stone-200">
                  {s.name}
                  {s.replaces && (
                    <span className="ml-2 text-xs text-stone-500">← replaces {s.replaces}</span>
                  )}
                </p>
                <p className="mt-0.5 text-xs text-stone-400">{s.reason}</p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Missing staples */}
      {result.missing_staples && result.missing_staples.length > 0 && (
        <Section title="Missing staples (not in your collection)">
          <div className="flex flex-wrap gap-2">
            {result.missing_staples.map((s, i) => (
              <span key={i} className="rounded-full bg-stone-700/40 px-3 py-1 text-xs text-stone-400">
                {s}
              </span>
            ))}
          </div>
        </Section>
      )}

      {/* Decklist */}
      {result.decklist && (!result.optimizer || !resp.recommendation_run_id) && (
        <Section title="Decklist">
          <div className="relative">
            <pre className="max-h-80 overflow-y-auto rounded-xl border border-white/5 bg-ink-800/60 p-4 text-xs leading-relaxed text-stone-300 font-mono">
              {result.decklist}
            </pre>
            <button
              onClick={copyDecklist}
              className="absolute right-3 top-3 rounded-lg border border-white/10 bg-ink-700 px-3 py-1.5 text-xs text-stone-300 transition hover:bg-ink-600"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
        </Section>
      )}
    </div>
  );
}

export default function DeckbuildingPage() {
  const [mode, setMode] = useState<Mode>("build");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [resp, setResp] = useState<DeckbuildingResponse | null>(null);

  // Build mode inputs
  const [theme, setTheme]       = useState("");
  const [commander, setCommander] = useState("");

  // Suggest / Audit inputs
  const [decklist, setDecklist]   = useState("");
  const [themeHint, setThemeHint] = useState("");

  function switchMode(m: Mode) {
    setMode(m);
    setResp(null);
    setErr(null);
  }

  async function submit() {
    setBusy(true);
    setErr(null);
    setResp(null);
    try {
      if (mode === "build") {
        if (!theme.trim()) { setErr("Enter a theme first."); return; }
        setResp(await buildDeckFromTheme(theme.trim(), commander.trim() || undefined));
      } else if (mode === "suggest") {
        if (!decklist.trim()) { setErr("Paste your in-progress decklist first."); return; }
        setResp(await suggestDeckAdditions(decklist.trim(), themeHint.trim() || undefined));
      } else {
        if (!decklist.trim()) { setErr("Paste your complete decklist first."); return; }
        setResp(await auditDeck(decklist.trim()));
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  const tabs: { id: Mode; label: string; desc: string }[] = [
    { id: "build",   label: "Build",   desc: "Build a full deck from a theme using your collection" },
    { id: "suggest", label: "Suggest", desc: "Get addition suggestions for an in-progress deck" },
    { id: "audit",   label: "Audit",   desc: "Get cuts and improvements for a complete deck" },
  ];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-4xl font-semibold text-stone-100">Deckbuilding</h1>
        <p className="mt-2 max-w-2xl text-stone-400">
          Collection-aware Commander deckbuilding. Every suggestion draws only from cards you own.
          Run the <span className="font-medium text-stone-300">Enrich</span> step first for best results.
        </p>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-2 rounded-2xl border border-white/10 bg-ink-900/60 p-1.5">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => switchMode(tab.id)}
            className={[
              "flex-1 rounded-xl px-4 py-3 text-sm font-medium transition",
              mode === tab.id
                ? "bg-gradient-to-r from-ember-500/20 to-arcane-500/20 text-stone-100 ring-1 ring-ember-400/30"
                : "text-stone-400 hover:text-stone-200",
            ].join(" ")}
          >
            <span className="block">{tab.label}</span>
            <span className="block text-xs font-normal opacity-70 mt-0.5">{tab.desc}</span>
          </button>
        ))}
      </div>

      {/* Input panel */}
      <div className="rounded-2xl border border-white/10 bg-ink-900/60 p-6 space-y-4">
        {mode === "build" && (
          <>
            <label className="block space-y-1">
              <span className="text-sm font-medium text-stone-300">Theme / synergy focus</span>
              <input
                type="text"
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
                placeholder="e.g. graveyard recursion, disguise and morph, tokens and aristocrats…"
                disabled={busy}
                className="w-full rounded-lg border border-white/10 bg-ink-800 px-4 py-2.5 text-sm text-stone-200 placeholder:text-stone-600 focus:outline-none focus:ring-1 focus:ring-ember-400/50 disabled:opacity-50"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-sm font-medium text-stone-300">
                Commander <span className="font-normal text-stone-500">(optional — the reasoning layer may propose one, but code validates it)</span>
              </span>
              <input
                type="text"
                value={commander}
                onChange={(e) => setCommander(e.target.value)}
                placeholder="e.g. Atraxa, Praetors' Voice"
                disabled={busy}
                className="w-full rounded-lg border border-white/10 bg-ink-800 px-4 py-2.5 text-sm text-stone-200 placeholder:text-stone-600 focus:outline-none focus:ring-1 focus:ring-ember-400/50 disabled:opacity-50"
              />
            </label>
          </>
        )}

        {mode === "suggest" && (
          <>
            <label className="block space-y-1">
              <span className="text-sm font-medium text-stone-300">In-progress decklist</span>
              <span className="block text-xs text-stone-500">Paste your current list — one card per line, optionally prefixed with quantity</span>
              <textarea
                value={decklist}
                onChange={(e) => setDecklist(e.target.value)}
                rows={10}
                placeholder={"1 Sol Ring\n1 Command Tower\n…"}
                disabled={busy}
                className="w-full rounded-lg border border-white/10 bg-ink-800 px-4 py-3 font-mono text-xs text-stone-200 placeholder:text-stone-600 focus:outline-none focus:ring-1 focus:ring-ember-400/50 disabled:opacity-50"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-sm font-medium text-stone-300">
                Theme hint <span className="font-normal text-stone-500">(optional)</span>
              </span>
              <input
                type="text"
                value={themeHint}
                onChange={(e) => setThemeHint(e.target.value)}
                placeholder="e.g. sacrifice synergies"
                disabled={busy}
                className="w-full rounded-lg border border-white/10 bg-ink-800 px-4 py-2.5 text-sm text-stone-200 placeholder:text-stone-600 focus:outline-none focus:ring-1 focus:ring-ember-400/50 disabled:opacity-50"
              />
            </label>
          </>
        )}

        {mode === "audit" && (
          <label className="block space-y-1">
            <span className="text-sm font-medium text-stone-300">Complete decklist</span>
            <span className="block text-xs text-stone-500">Paste your 100-card list — quantity + card name per line</span>
            <textarea
              value={decklist}
              onChange={(e) => setDecklist(e.target.value)}
              rows={14}
              placeholder={"1 Sol Ring\n1 Command Tower\n…"}
              disabled={busy}
              className="w-full rounded-lg border border-white/10 bg-ink-800 px-4 py-3 font-mono text-xs text-stone-200 placeholder:text-stone-600 focus:outline-none focus:ring-1 focus:ring-ember-400/50 disabled:opacity-50"
            />
          </label>
        )}

        {err && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            {err}
          </div>
        )}

        <button
          onClick={submit}
          disabled={busy}
          className="w-full rounded-xl bg-gradient-to-r from-ember-600 to-arcane-600 py-3 text-sm font-semibold text-white shadow-lg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? (
            <span className="flex items-center justify-center gap-2">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              {mode === "build" ? "Reasoning, optimizing, and validating…" : "Analyzing…"}
            </span>
          ) : mode === "build" ? "Build My Deck" : mode === "suggest" ? "Suggest Additions" : "Audit Deck"}
        </button>
      </div>

      {/* Results */}
      {resp && <ResultPanel resp={resp} />}
    </div>
  );
}
