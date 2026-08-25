import { useCallback, useEffect, useRef, useState } from "react";
import {
  EnrichmentJob,
  EnrichmentStatus,
  MechanicProfileSample,
  OpenAIUsageSummary,
  QualityEvaluationReport,
  fetchEnrichmentProgress,
  fetchEnrichmentStatus,
  fetchEnrichmentSample,
  fetchOpenAIUsage,
  fetchQualityEvaluation,
  startScryfallBackfill,
  startSemanticIndex,
  startStructuredEnrichment,
} from "../api";

function ProgressBar({ processed, total }: { processed: number; total: number }) {
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;
  return (
    <div className="mt-3 space-y-1">
      <div className="flex justify-between text-xs text-stone-400">
        <span>Processing {processed.toLocaleString()} / {total.toLocaleString()}</span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-ink-800">
        <div
          className="h-full rounded-full bg-gradient-to-r from-ember-500 to-arcane-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function JobStatusBadge({ job }: { job: EnrichmentJob }) {
  if (job.status === "done")
    return <span className="rounded-full bg-emerald-500/20 px-3 py-1 text-xs font-medium text-emerald-300">Done</span>;
  if (job.status === "error")
    return <span className="rounded-full bg-red-500/20 px-3 py-1 text-xs font-medium text-red-300">Error</span>;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-arcane-500/20 px-3 py-1 text-xs font-medium text-arcane-300">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-arcane-400" />
      Running
    </span>
  );
}

function useJobPoller(jobId: string | null, refreshStatus: () => void) {
  const [job, setJob] = useState<EnrichmentJob | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    const activeJobId = jobId;
    async function poll() {
      const j = await fetchEnrichmentProgress(activeJobId);
      if (j) {
        setJob(j);
        // Keep the summary cards in sync while batches are being committed,
        // rather than leaving them stale until the entire job finishes.
        void refreshStatus();
        if (j.status !== "running") {
          clearInterval(intervalRef.current!);
        }
      }
    }

    void poll();
    intervalRef.current = setInterval(() => void poll(), 800);
    return () => clearInterval(intervalRef.current!);
  }, [jobId, refreshStatus]);

  return job;
}

export default function EnrichmentPage() {
  const [status, setStatus] = useState<EnrichmentStatus | null>(null);
  const [usage, setUsage] = useState<OpenAIUsageSummary | null>(null);
  const [statusErr, setStatusErr] = useState<string | null>(null);

  const [sfBatchSize, setSfBatchSize] = useState(200);
  const [sfJobId, setSfJobId] = useState<string | null>(null);
  const [sfErr, setSfErr] = useState<string | null>(null);

  const [tagBatchSize, setTagBatchSize] = useState(12);
  const [tagJobId, setTagJobId] = useState<string | null>(null);
  const [tagErr, setTagErr] = useState<string | null>(null);

  const [embeddingBatchSize, setEmbeddingBatchSize] = useState(100);
  const [embeddingJobId, setEmbeddingJobId] = useState<string | null>(null);
  const [embeddingErr, setEmbeddingErr] = useState<string | null>(null);

  const [sample, setSample] = useState<MechanicProfileSample[]>([]);
  const [sampleLoading, setSampleLoading] = useState(false);
  const [qualityReport, setQualityReport] = useState<QualityEvaluationReport | null>(null);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [qualityErr, setQualityErr] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const [nextStatus, nextUsage] = await Promise.all([
        fetchEnrichmentStatus(),
        fetchOpenAIUsage(),
      ]);
      setStatus(nextStatus);
      setUsage(nextUsage);
      setStatusErr(null);
    } catch (e) {
      setStatusErr(e instanceof Error ? e.message : "Failed to load status");
    }
  }, []);

  useEffect(() => { void loadStatus(); }, [loadStatus]);

  const sfJob = useJobPoller(sfJobId, loadStatus);
  const tagJob = useJobPoller(tagJobId, loadStatus);
  const embeddingJob = useJobPoller(embeddingJobId, loadStatus);

  async function runBackfill() {
    setSfErr(null);
    try {
      const { job_id } = await startScryfallBackfill(sfBatchSize);
      setSfJobId(job_id);
    } catch (e) {
      setSfErr(e instanceof Error ? e.message : "Failed to start backfill");
    }
  }

  async function runTagging() {
    setTagErr(null);
    try {
      const { job_id } = await startStructuredEnrichment(tagBatchSize);
      setTagJobId(job_id);
    } catch (e) {
      setTagErr(e instanceof Error ? e.message : "Failed to start enrichment");
    }
  }

  async function loadSample() {
    setSampleLoading(true);
    try {
      setSample(await fetchEnrichmentSample(20));
    } finally {
      setSampleLoading(false);
    }
  }

  async function runQualityGate() {
    setQualityLoading(true);
    setQualityErr(null);
    try {
      setQualityReport(await fetchQualityEvaluation());
    } catch (e) {
      setQualityErr(e instanceof Error ? e.message : "Failed to run quality evaluation");
    } finally {
      setQualityLoading(false);
    }
  }

  async function runSemanticIndex() {
    setEmbeddingErr(null);
    try {
      const { job_id } = await startSemanticIndex(embeddingBatchSize);
      setEmbeddingJobId(job_id);
    } catch (e) {
      setEmbeddingErr(e instanceof Error ? e.message : "Failed to start semantic indexing");
    }
  }

  const sfBusy  = sfJob?.status  === "running";
  const tagBusy = tagJob?.status === "running";
  const embeddingBusy = embeddingJob?.status === "running";

  const estCostBatch =
    status
      ? (status.estimated_cost_all_unprofiled / (status.unprofiled_cards || 1)) * tagBatchSize
      : null;

  return (
    <div className="space-y-10">
      <div>
        <h1 className="font-display text-4xl font-semibold text-stone-100">Enrich Collection</h1>
        <p className="mt-2 max-w-2xl text-stone-400">
          Step 1: backfill Scryfall metadata (keywords, oracle text) for existing cards — free, no AI.
          Step 2: create versioned mechanic profiles for deterministic evaluation and deckbuilding.
          Step 3: embed those mechanics for meaning-based candidate retrieval.
        </p>
      </div>

      {statusErr && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {statusErr}
        </div>
      )}

      {status && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Cached cards" value={status.total_cards.toLocaleString()} />
          <Stat
            label="Scryfall metadata ready"
            value={`${(status.total_cards - status.keywords_missing).toLocaleString()} / ${status.total_cards.toLocaleString()}`}
          />
          <Stat
            label="Mechanic profiles ready"
            value={`${status.profiled_cards.toLocaleString()} / ${status.total_cards.toLocaleString()}`}
          />
          <Stat
            label="Semantic index ready"
            value={`${status.embedded_cards.toLocaleString()} / ${status.total_cards.toLocaleString()}`}
          />
        </div>
      )}

      {usage && (
        <section className="space-y-4 rounded-2xl border border-white/10 bg-ink-900/60 p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-stone-100">OpenAI Cost Controls</h2>
              <p className="mt-1 max-w-3xl text-sm text-stone-400">
                Every paid request reserves its worst-case local estimate before it is sent, then
                reconciles that reservation with the API token usage. This ledger never contains your API key.
              </p>
            </div>
            <span className={`rounded-full px-3 py-1 text-xs font-medium ${
              usage.requests_enabled
                ? "bg-amber-500/20 text-amber-300"
                : "bg-emerald-500/20 text-emerald-300"
            }`}>
              {usage.requests_enabled ? "Paid requests unlocked" : "Paid requests locked"}
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label={`${usage.month} spent`} value={`$${usage.spent_usd.toFixed(4)}`} />
            <Stat label="Active reservations" value={`$${usage.reserved_usd.toFixed(4)}`} />
            <Stat label="Local budget remaining" value={`$${usage.remaining_usd.toFixed(4)}`} />
            <Stat label="Monthly / request caps" value={`$${usage.monthly_budget_usd.toFixed(2)} / $${usage.single_request_limit_usd.toFixed(2)}`} />
          </div>
          <p className="text-xs text-amber-300/90">
            {usage.notice} Also set a project budget in the OpenAI dashboard. Pricing snapshot: {usage.pricing_version}.
          </p>
          {usage.recent.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-white/5">
              <table className="min-w-full text-left text-xs text-stone-400">
                <thead className="bg-ink-800/80 text-stone-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">Workflow</th>
                    <th className="px-3 py-2 font-medium">Model</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Tokens in / out</th>
                    <th className="px-3 py-2 font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {usage.recent.map((record) => (
                    <tr key={record.id} className="border-t border-white/5">
                      <td className="px-3 py-2 text-stone-300">{record.workflow}</td>
                      <td className="px-3 py-2 font-mono">{record.model}</td>
                      <td className="px-3 py-2">{record.status}</td>
                      <td className="px-3 py-2">
                        {record.input_tokens.toLocaleString()} / {record.output_tokens.toLocaleString()}
                        {record.cached_input_tokens > 0 && ` (${record.cached_input_tokens.toLocaleString()} cached)`}
                      </td>
                      <td className="px-3 py-2">
                        {record.status === "failed"
                          ? "released"
                          : `$${(record.actual_cost_usd ?? record.estimated_max_cost_usd).toFixed(6)}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* ── Step 1: Scryfall Backfill ── */}
      <section className="rounded-2xl border border-white/10 bg-ink-900/60 p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-stone-100">Step 1 — Scryfall Backfill</h2>
            <p className="mt-1 text-sm text-stone-400">
              Fetches missing <span className="font-mono text-stone-300">keywords</span> and refreshes oracle text
              for cards that predate this feature. Uses the batch endpoint — typically finishes in seconds.
              No AI cost.
            </p>
          </div>
          {status && (
            <span className="shrink-0 rounded-full bg-ink-800 px-3 py-1 text-xs text-stone-400">
              {status.keywords_missing} cards need this
            </span>
          )}
        </div>

        <div className="flex items-end gap-3">
          <label className="flex-1 space-y-1">
            <span className="text-xs text-stone-500">Batch size</span>
            <input
              type="number"
              min={1}
              max={5000}
              value={sfBatchSize}
              onChange={(e) => setSfBatchSize(Number(e.target.value))}
              disabled={sfBusy}
              className="w-full rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm text-stone-200 focus:outline-none focus:ring-1 focus:ring-ember-400/50 disabled:opacity-50"
            />
          </label>
          <button
            onClick={runBackfill}
            disabled={sfBusy || status?.keywords_missing === 0}
            className="rounded-lg bg-gradient-to-r from-ember-600 to-ember-500 px-5 py-2 text-sm font-medium text-white shadow transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {sfBusy ? "Running…" : "Run Backfill"}
          </button>
        </div>

        {sfErr && <p className="text-sm text-red-400">{sfErr}</p>}

        {sfJob && (
          <div className="rounded-xl border border-white/5 bg-ink-800/60 p-4">
            <div className="flex items-center gap-3">
              <JobStatusBadge job={sfJob} />
              {sfJob.status === "error" && <span className="text-sm text-red-300">{sfJob.error}</span>}
            </div>
            {sfJob.status === "running" && (
              <ProgressBar processed={sfJob.processed} total={sfJob.total} />
            )}
            {sfJob.status === "done" && (
              <p className="mt-2 text-sm text-stone-400">
                Refreshed Scryfall metadata for {sfJob.processed.toLocaleString()} cards. This step does not add
                mechanic profiles; continue to Step 2 to update the profiled count.
                {sfJob.failed ? ` Scryfall could not resolve ${sfJob.failed.toLocaleString()} cards.` : ""}
              </p>
            )}
          </div>
        )}
      </section>

      {/* ── Step 2: Structured Mechanic Profiles ── */}
      <section className="rounded-2xl border border-white/10 bg-ink-900/60 p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-stone-100">Step 2 — Structured Mechanic Profiles</h2>
            <p className="mt-1 text-sm text-stone-400">
              Uses the configured provider to classify closed roles and evidence-backed mechanic hooks.
              Profiles are schema-versioned, provider-neutral, and keep their provenance.
            </p>
          </div>
          {status && (
            <span className="shrink-0 rounded-full bg-ink-800 px-3 py-1 text-xs text-stone-400">
              {status.unprofiled_cards} unprofiled
            </span>
          )}
        </div>

        {status && (
          <div className="rounded-xl border border-white/5 bg-ink-800/40 px-4 py-3 text-xs text-stone-400 space-y-1">
            <div>
              Provider: <span className="font-mono text-stone-300">{status.enrichment_provider}</span>
              {" "}· Model: <span className="font-mono text-stone-300">{status.enrichment_model}</span>
              {" "}· Schema: <span className="font-mono text-stone-300">{status.profile_schema_version}</span>
              {" "}· Taxonomy: <span className="font-mono text-stone-300">{status.taxonomy_version}</span>
            </div>
            {status.avg_input_tokens_per_card != null ? (
              <div>
                Running avg: {Math.round(status.avg_input_tokens_per_card)} in / {Math.round(status.avg_output_tokens_per_card ?? 0)} out tokens per card
              </div>
            ) : (
              <div>Token averages will appear after your first batch runs.</div>
            )}
            {!status.paid_requests_enabled && status.enrichment_provider === "openai" && (
              <div className="text-amber-300">
                Paid OpenAI requests are locked. Set OPENAI_REQUESTS_ENABLED=true and restart the backend when you intentionally want to create profiles.
              </div>
            )}
          </div>
        )}

        <div className="flex items-end gap-3">
          <label className="flex-1 space-y-1">
            <span className="text-xs text-stone-500">Cards to process</span>
            <input
              type="number"
              min={1}
              max={2000}
              value={tagBatchSize}
              onChange={(e) => setTagBatchSize(Number(e.target.value))}
              disabled={tagBusy}
              className="w-full rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm text-stone-200 focus:outline-none focus:ring-1 focus:ring-ember-400/50 disabled:opacity-50"
            />
          </label>
          <button
            onClick={runTagging}
            disabled={tagBusy || status?.unprofiled_cards === 0 || status?.provider_configured === false}
            className="rounded-lg bg-gradient-to-r from-arcane-600 to-arcane-500 px-5 py-2 text-sm font-medium text-white shadow transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {tagBusy ? "Running…" : "Create Profiles"}
          </button>
        </div>

        {status && estCostBatch != null && (
          <p className="text-xs text-stone-500">
            Estimated cost for {tagBatchSize} cards:{" "}
            <span className="font-medium text-stone-300">
              ~${estCostBatch < 0.01 ? estCostBatch.toFixed(4) : estCostBatch.toFixed(2)}
            </span>
            {status.avg_input_tokens_per_card == null && " (seed estimate — updates after first batch)"}
          </p>
        )}

        {tagErr && <p className="text-sm text-red-400">{tagErr}</p>}

        {tagJob && (
          <div className="rounded-xl border border-white/5 bg-ink-800/60 p-4">
            <div className="flex items-center gap-3">
              <JobStatusBadge job={tagJob} />
              {tagJob.status === "error" && <span className="text-sm text-red-300">{tagJob.error}</span>}
            </div>
            {tagJob.status === "running" && (
              <ProgressBar processed={tagJob.processed} total={tagJob.total} />
            )}
            {tagJob.status === "done" && (
              <p className="mt-2 text-sm text-stone-400">
                Profiled {tagJob.processed.toLocaleString()} cards. Refresh the sample below to review results.
                {tagJob.failed
                  ? ` ${tagJob.failed.toLocaleString()} cards still failed after an isolated retry: ${(tagJob.failed_cards ?? []).join(", ")}.`
                  : ""}
              </p>
            )}
          </div>
        )}
      </section>

      {/* ── Step 3: Semantic Index ── */}
      <section className="rounded-2xl border border-white/10 bg-ink-900/60 p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-stone-100">Step 3 — Semantic Candidate Index</h2>
            <p className="mt-1 text-sm text-stone-400">
              Embeds Oracle text and structured mechanics once, then uses vector similarity to find relevant
              owned cards even when the deck request and card text use different words. Changed cards and
              profiles are detected by content hash and safely re-indexed.
            </p>
          </div>
          {status && (
            <span className="shrink-0 rounded-full bg-ink-800 px-3 py-1 text-xs text-stone-400">
              {status.unembedded_cards.toLocaleString()} need indexing
            </span>
          )}
        </div>

        {status && (
          <div className="rounded-xl border border-white/5 bg-ink-800/40 px-4 py-3 text-xs text-stone-400 space-y-1">
            <div>
              Provider: <span className="font-mono text-stone-300">{status.embedding_provider}</span>
              {" "}· Model: <span className="font-mono text-stone-300">{status.embedding_model}</span>
              {" "}· Dimensions: <span className="font-mono text-stone-300">{status.embedding_dimensions}</span>
              {" "}· Index: <span className="font-mono text-stone-300">{status.embedding_index_version}</span>
            </div>
            <div>
              Identical deck queries are cached. If the paid-request lock is later disabled, retrieval falls
              back to the existing local lexical scorer instead of failing.
            </div>
            {!status.paid_requests_enabled && status.embedding_provider === "openai" && (
              <div className="text-amber-300">
                Paid OpenAI requests are locked. Turn them on only when you are ready to build the index.
              </div>
            )}
          </div>
        )}

        <div className="flex items-end gap-3">
          <label className="flex-1 space-y-1">
            <span className="text-xs text-stone-500">Cards to index</span>
            <input
              type="number"
              min={1}
              max={5000}
              value={embeddingBatchSize}
              onChange={(e) => setEmbeddingBatchSize(Number(e.target.value))}
              disabled={embeddingBusy}
              className="w-full rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm text-stone-200 focus:outline-none focus:ring-1 focus:ring-ember-400/50 disabled:opacity-50"
            />
          </label>
          <button
            onClick={runSemanticIndex}
            disabled={embeddingBusy || status?.unembedded_cards === 0 || status?.embedding_provider_configured === false}
            className="rounded-lg bg-gradient-to-r from-emerald-700 to-emerald-600 px-5 py-2 text-sm font-medium text-white shadow transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {embeddingBusy ? "Indexing…" : "Build Semantic Index"}
          </button>
        </div>

        {status && (
          <p className="text-xs text-stone-500">
            Estimated cost for remaining cards: <span className="font-medium text-stone-300">
              ~${status.estimated_cost_all_unembedded.toFixed(4)}
            </span>
            {status.avg_embedding_tokens_per_card == null && " (seed estimate — updates after the first batch)"}
          </p>
        )}
        {embeddingErr && <p className="text-sm text-red-400">{embeddingErr}</p>}
        {embeddingJob && (
          <div className="rounded-xl border border-white/5 bg-ink-800/60 p-4">
            <div className="flex items-center gap-3">
              <JobStatusBadge job={embeddingJob} />
              {embeddingJob.status === "error" && <span className="text-sm text-red-300">{embeddingJob.error}</span>}
            </div>
            {embeddingJob.status === "running" && (
              <ProgressBar processed={embeddingJob.processed} total={embeddingJob.total} />
            )}
            {embeddingJob.status === "done" && (
              <p className="mt-2 text-sm text-stone-400">
                Indexed {embeddingJob.processed.toLocaleString()} cards using {embeddingJob.input_tokens?.toLocaleString() ?? 0} input tokens
                {embeddingJob.estimated_cost != null ? ` (~$${embeddingJob.estimated_cost.toFixed(4)}).` : "."}
              </p>
            )}
          </div>
        )}
      </section>

      {/* ── Local Quality Gate ── */}
      <section className="rounded-2xl border border-white/10 bg-ink-900/60 p-6 space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-stone-100">Local MTG Quality Gate</h2>
            <p className="mt-1 max-w-3xl text-sm text-stone-400">
              Runs versioned golden cases for indirect synergy, universal utility, anti-synergy,
              known interactions, legality traps, and candidate ranking against your stored profiles.
              This never contacts OpenAI or another provider.
            </p>
          </div>
          <button
            onClick={runQualityGate}
            disabled={qualityLoading}
            className="rounded-lg border border-white/10 bg-ink-800 px-4 py-2 text-sm text-stone-300 transition hover:bg-ink-700 disabled:opacity-50"
          >
            {qualityLoading ? "Evaluating…" : qualityReport ? "Run Again" : "Run Quality Gate"}
          </button>
        </div>

        {qualityErr && <p className="text-sm text-red-400">{qualityErr}</p>}
        {qualityReport && (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-4">
              <Stat label="Passed" value={qualityReport.summary.passed.toLocaleString()} />
              <Stat label="Failed" value={qualityReport.summary.failed.toLocaleString()} />
              <Stat label="Skipped" value={qualityReport.summary.skipped.toLocaleString()} />
              <Stat
                label="Pass rate"
                value={qualityReport.summary.pass_rate == null ? "—" : `${Math.round(qualityReport.summary.pass_rate * 100)}%`}
              />
            </div>
            <p className="text-xs text-stone-500">
              Suite {qualityReport.suite_version} · Retrieval {qualityReport.retrieval_version} · Coverage {Math.round(qualityReport.summary.coverage * 100)}% · Network requests {qualityReport.network_requests}
            </p>
            <div className="space-y-2">
              {qualityReport.cases.map((qualityCase) => (
                <details key={qualityCase.id} className="rounded-lg border border-white/5 bg-ink-800/40 px-4 py-3">
                  <summary className="flex cursor-pointer list-none items-center gap-3 text-sm">
                    <span className={`rounded px-2 py-0.5 text-[10px] font-semibold uppercase ${
                      qualityCase.status === "passed"
                        ? "bg-emerald-500/15 text-emerald-300"
                        : qualityCase.status === "failed"
                          ? "bg-red-500/15 text-red-300"
                          : "bg-stone-500/15 text-stone-400"
                    }`}>
                      {qualityCase.status}
                    </span>
                    <span className="text-stone-200">{qualityCase.subject}</span>
                    <span className="ml-auto text-xs text-stone-600">{qualityCase.group} · {qualityCase.category}</span>
                  </summary>
                  <div className="mt-3 space-y-2 text-xs text-stone-400">
                    <p className="font-mono text-stone-500">{qualityCase.id}</p>
                    {qualityCase.reason && <p>{qualityCase.reason}</p>}
                    {qualityCase.expected && <pre className="overflow-x-auto whitespace-pre-wrap">Expected: {JSON.stringify(qualityCase.expected, null, 2)}</pre>}
                    {qualityCase.actual && <pre className="overflow-x-auto whitespace-pre-wrap">Actual: {JSON.stringify(qualityCase.actual, null, 2)}</pre>}
                  </div>
                </details>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* ── Quality Review Sample ── */}
      <section className="rounded-2xl border border-white/10 bg-ink-900/60 p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-stone-100">Profile Quality Review</h2>
            <p className="mt-1 text-sm text-stone-400">
              The 20 most recent profiles, including roles, hooks, evidence, confidence, and provenance.
            </p>
          </div>
          <button
            onClick={loadSample}
            disabled={sampleLoading}
            className="rounded-lg border border-white/10 bg-ink-800 px-4 py-2 text-sm text-stone-300 transition hover:bg-ink-700 disabled:opacity-50"
          >
            {sampleLoading ? "Loading…" : sample.length > 0 ? "Refresh" : "Load Sample"}
          </button>
        </div>

        {sample.length > 0 && (
          <div className="space-y-3">
            {sample.map((card) => (
              <div key={card.name} className="rounded-xl border border-white/5 bg-ink-800/50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-medium text-stone-200">{card.name}</p>
                    <p className="text-xs text-stone-500">{card.type_line}</p>
                  </div>
                  <p className="text-xs text-stone-600">
                    {card.provider}:{card.model} · {card.created_at.slice(0, 19).replace("T", " ")}
                  </p>
                </div>
                {card.oracle_text && (
                  <p className="mt-2 text-xs leading-relaxed text-stone-400 line-clamp-2">{card.oracle_text}</p>
                )}
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {card.keywords.map((kw) => (
                    <span key={kw} className="rounded-full border border-stone-600/40 bg-stone-700/30 px-2 py-0.5 text-xs text-stone-400">
                      {kw}
                    </span>
                  ))}
                  {card.profile.roles.map((role) => (
                    <span key={role} className="rounded-full bg-arcane-500/20 px-2 py-0.5 text-xs font-medium text-arcane-300 ring-1 ring-arcane-500/30">
                      {role}
                    </span>
                  ))}
                  {card.profile.roles.length === 0 && (
                    <span className="text-xs text-stone-600 italic">no functional roles</span>
                  )}
                </div>
                <div className="mt-3 space-y-1.5">
                  {card.profile.hooks.map((hook, index) => (
                    <div key={`${hook.verb}-${hook.mechanic}-${index}`} className="text-xs text-stone-400">
                      <span className="font-mono text-ember-300">{hook.verb}:{hook.mechanic}</span>
                      <span className="text-stone-500"> · {hook.scope} · {hook.condition}</span>
                      <span className="italic text-stone-500"> — “{hook.evidence}”</span>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-xs text-stone-500">
                  Universal: <span className="text-stone-300">{card.profile.universal_utility.tier}</span>
                  {" "}· Confidence: <span className="text-stone-300">{Math.round(card.profile.confidence * 100)}%</span>
                  {" "}· Taxonomy: <span className="font-mono text-stone-300">{card.profile.taxonomy_version}</span>
                </p>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-ink-900/60 px-5 py-4">
      <p className="text-xs text-stone-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-stone-100">{value}</p>
    </div>
  );
}
