const base = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

const API_KEY_STORAGE = "spellbinder_api_key";
const browserFetch = globalThis.fetch.bind(globalThis);

export function setApiKey(value: string): void {
  const key = value.trim();
  if (key) sessionStorage.setItem(API_KEY_STORAGE, key);
  else sessionStorage.removeItem(API_KEY_STORAGE);
}

export function clearApiKey(): void {
  sessionStorage.removeItem(API_KEY_STORAGE);
}

async function fetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const apiKey = sessionStorage.getItem(API_KEY_STORAGE);
  if (apiKey) headers.set("X-Spellbinder-Key", apiKey);
  return browserFetch(input, { ...init, headers });
}

export type AuthStatus = { required: boolean; authenticated: boolean };

export async function fetchAuthStatus(): Promise<AuthStatus> {
  const r = await fetch(`${base}/api/auth/status`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type Card = {
  scryfall_id: string;
  oracle_id: string;
  name: string;
  type_line: string | null;
  mana_cost: string | null;
  cmc: number;
  colors: string;
  color_identity: string;
  rarity: string | null;
  set_code: string | null;
  collector_number: string | null;
  image_uri_normal: string | null;
};

export type InventoryLine = {
  id: number;
  scryfall_id: string;
  quantity: number;
  foil: boolean;
  condition: string | null;
  language: string | null;
  set_code: string | null;
  collector_number: string | null;
  card: Card | null;
};

export type InventoryPrinting = {
  scryfall_id: string;
  set_code: string | null;
  collector_number: string | null;
  rarity: string | null;
  language: string | null;
  image_uri_normal: string | null;
  total_quantity: number;
  foil_quantity: number;
  nonfoil_quantity: number;
  card: Card;
  lines: InventoryLine[];
};

export type InventoryOracleGroup = {
  oracle_id: string;
  total_quantity: number;
  printing_count: number;
  inventory_line_count: number;
  card: Card;
  printings: InventoryPrinting[];
};

export type Deck = {
  id: number;
  name: string;
  format: string;
  status: string;
  notes: string | null;
  commander_scryfall_id: string | null;
  commander_name: string | null;
};

export type DeckCard = {
  id: number;
  scryfall_id: string;
  quantity: number;
  grabbed_quantity: number;
  proxy_quantity: number;
  is_commander: boolean;
  is_sideboard: boolean;
  card: Card | null;
  allocations: DeckCardAllocation[];
};

export type DeckCardAllocation = {
  id: number;
  status: "pending" | "grabbed" | "proxy";
  quantity: number;
  scryfall_id: string | null;
  foil: boolean | null;
  printing: Card | null;
};

export type DeckDetail = Deck & { cards: DeckCard[] };

export type DeckTextPreviewCard = {
  line_index: number;
  quantity: number;
  scryfall_id: string;
  oracle_id: string;
  name: string;
  type_line: string | null;
  colors: string;
  image_uri_normal: string | null;
  set_code: string | null;
  collector_number: string | null;
  foil: boolean;
  is_commander: boolean;
  owned_quantity: number;
};

export type DeckTextPreview = {
  cards: DeckTextPreviewCard[];
  row_errors: DeckCsvRowError[];
  total_quantity: number;
};

export type DeckAnalysisFinding = {
  code: string;
  severity: "error" | "warning";
  message: string;
  details: Record<string, unknown>;
};

export type DeckAnalysis = {
  deck_id: number;
  deterministic: true;
  legal: boolean;
  available: boolean;
  deck_size: { actual: number; required: number; delta: number };
  commander: { count: number; names: string[]; color_identity: string[] };
  legality: { findings: DeckAnalysisFinding[] };
  availability: {
    available: boolean;
    total_shortfall: number;
    missing: { oracle_id: string; name: string; required: number; owned: number; shortfall: number }[];
  };
  health: {
    score: number;
    status: "healthy" | "needs_attention" | "critical";
    lands: { count: number; target_min: number; target_max: number };
    mana_sources: {
      total: number;
      target_min: number;
      by_color: Record<string, number>;
      mana_demand: Record<string, number>;
    };
    curve: {
      average_mana_value: number;
      nonland_cards: number;
      high_mana_value_cards: number;
      buckets: Record<string, number>;
    };
    roles: Record<string, {
      count: number;
      target_min: number;
      target_max: number;
      status: "low" | "ok" | "high";
      cards: string[];
    }>;
    findings: DeckAnalysisFinding[];
  };
};

export type DeckMatch = {
  deck_id: number;
  deck_name: string;
  deck_status: string;
  score: number;
  reasons: string[];
  kind: string;
};

export type ImportRowResult = {
  row_index: number;
  scryfall_id: string | null;
  name: string | null;
  ok: boolean;
  error?: string | null;
  matches: DeckMatch[];
  image_uri_normal?: string | null;
};

export type TextImportProgress = {
  done: number;
  total: number;
  total_qty: number;
  batches_done?: number;
  batches_total?: number;
};

export async function fetchInventory(q: string, sort: string): Promise<InventoryLine[]> {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  if (sort) p.set("sort", sort);
  const r = await fetch(`${base}/api/inventory?${p}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchGroupedInventory(q: string): Promise<InventoryOracleGroup[]> {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  const r = await fetch(`${base}/api/inventory/grouped?${p}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function deleteInventoryLine(id: number): Promise<void> {
  const r = await fetch(`${base}/api/inventory/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
}

export async function clearInventory(): Promise<{ deleted: number }> {
  const r = await fetch(`${base}/api/inventory/clear`, { method: "POST" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type PrintingOption = {
  scryfall_id: string;
  name: string;
  set_name: string;
  set_code: string | null;
  collector_number: string | null;
  released_at: string | null;
  language: string | null;
  image_uri_normal: string | null;
  foil: boolean;
  nonfoil: boolean;
};

export type InventoryPrintingChangeResult = {
  changed_lines: number;
  moved_quantity: number;
  source_scryfall_id: string;
  target_scryfall_id: string;
};

export async function fetchPrintingOptions(scryfallId: string): Promise<PrintingOption[]> {
  const r = await fetch(`${base}/api/cards/${encodeURIComponent(scryfallId)}/print-options`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function changeInventoryLinePrinting(
  lineId: number,
  targetScryfallId: string,
): Promise<InventoryPrintingChangeResult> {
  const r = await fetch(`${base}/api/inventory/lines/${lineId}/printing`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_scryfall_id: targetScryfallId }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function changeInventoryPrinting(
  sourceScryfallId: string,
  targetScryfallId: string,
): Promise<InventoryPrintingChangeResult> {
  const r = await fetch(`${base}/api/inventory/printings/${encodeURIComponent(sourceScryfallId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_scryfall_id: targetScryfallId }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type ManaboxProgress = {
  batches_done: number;
  batches_total: number;
  status?: "running" | "complete" | "failed";
  stage?: "hydrating_cards" | "assembling_inventory" | "matching_decks" | "complete";
  error?: string;
};

export async function importManabox(
  file: File,
  importKey: string,
): Promise<{ added_quantity: number; rows: ImportRowResult[] }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(
    `${base}/api/import/manabox?import_key=${encodeURIComponent(importKey)}`,
    { method: "POST", body: fd },
  );
  if (!r.ok) {
    const payload = await r.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `Import failed (HTTP ${r.status})`);
  }
  return r.json();
}

export async function fetchManaboxImportProgress(
  importKey: string,
): Promise<ManaboxProgress | null> {
  const r = await fetch(
    `${base}/api/import/manabox/progress?import_key=${encodeURIComponent(importKey)}`,
  );
  if (!r.ok) return null;
  const data = await r.json();
  return data ?? null;
}

export async function fetchDecks(): Promise<Deck[]> {
  const r = await fetch(`${base}/api/decks`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchDeck(id: number): Promise<DeckDetail> {
  const r = await fetch(`${base}/api/decks/${id}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function previewDeckText(text: string): Promise<DeckTextPreview> {
  const r = await fetch(`${base}/api/decks/preview-text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchDeckAnalysis(id: number): Promise<DeckAnalysis> {
  const r = await fetch(`${base}/api/decks/${id}/analysis`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function createDeck(body: {
  name: string;
  format?: string;
  status?: string;
  notes?: string | null;
  commander_scryfall_id?: string | null;
  cards?: { scryfall_id: string; quantity?: number; is_commander?: boolean; is_sideboard?: boolean }[];
}): Promise<DeckDetail> {
  const r = await fetch(`${base}/api/decks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function patchDeck(
  id: number,
  body: Partial<{
    name: string;
    format: string;
    status: string;
    notes: string | null;
    commander_scryfall_id: string | null;
  }>
): Promise<DeckDetail> {
  const r = await fetch(`${base}/api/decks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function addDeckCards(
  deckId: number,
  cards: { scryfall_id: string; quantity?: number; is_commander?: boolean; is_sideboard?: boolean }[]
): Promise<DeckDetail> {
  const r = await fetch(`${base}/api/decks/${deckId}/cards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cards),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function removeDeckCard(deckId: number, deckCardId: number): Promise<DeckDetail> {
  const r = await fetch(`${base}/api/decks/${deckId}/cards/${deckCardId}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function setDeckCommander(deckId: number, deckCardId: number): Promise<DeckDetail> {
  const r = await fetch(`${base}/api/decks/${deckId}/cards/${deckCardId}/commander`, {
    method: "PUT",
  });
  if (!r.ok) {
    const payload = await r.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Could not select that commander");
  }
  return r.json();
}

export async function deleteDeck(id: number): Promise<void> {
  const r = await fetch(`${base}/api/decks/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
}

export type CardDeckMembership = {
  deck_id: number;
  deck_name: string;
  is_commander: boolean;
  quantity: number;
  grabbed_quantity: number;
  proxy_quantity: number;
  pending_quantity: number;
};

export type CardLocationSummary = {
  scryfall_id: string;
  oracle_id: string;
  owned_total: number;
  grabbed_total: number;
  bulk_total: number;
  pending_total: number;
  proxy_total: number;
  freely_available: number;
  demand_shortfall: number;
  any_printing?: Record<"grabbed" | "pending" | "proxy", number>;
  printings?: Array<{
    scryfall_id: string;
    set_code: string | null;
    collector_number: string | null;
    image_uri_normal: string | null;
    owned_total: number;
    grabbed_quantity: number;
    pending_quantity: number;
    proxy_quantity: number;
    freely_available: number;
    demand_shortfall: number;
  }>;
  decks: CardDeckMembership[];
};

export async function fetchCardDecks(scryfallId: string): Promise<CardDeckMembership[]> {
  const r = await fetch(`${base}/api/cards/${encodeURIComponent(scryfallId)}/decks`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchCardLocations(
  scryfallId: string,
  includePrintings = false,
): Promise<CardLocationSummary> {
  const suffix = includePrintings ? "?include_printings=true" : "";
  const r = await fetch(
    `${base}/api/cards/${encodeURIComponent(scryfallId)}/locations${suffix}`,
  );
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function updateDeckCardAssembly(
  deckId: number,
  deckCardId: number,
  body: { grabbed_quantity: number; proxy_quantity: number },
): Promise<DeckCard> {
  const r = await fetch(`${base}/api/decks/${deckId}/cards/${deckCardId}/assembly?compact=true`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function replaceDeckCardAllocations(
  deckId: number,
  deckCardId: number,
  allocations: Array<{
    status: "pending" | "grabbed" | "proxy";
    quantity: number;
    scryfall_id: string | null;
    foil: boolean | null;
  }>,
): Promise<DeckDetail> {
  const r = await fetch(`${base}/api/decks/${deckId}/cards/${deckCardId}/allocations`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ allocations }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function updateDeckAssembly(
  deckId: number,
  cards: { deck_card_id: number; grabbed_quantity: number; proxy_quantity: number }[],
): Promise<DeckDetail> {
  const r = await fetch(`${base}/api/decks/${deckId}/assembly`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cards }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchCardMatches(scryfallId: string, minScore = 35): Promise<DeckMatch[]> {
  const r = await fetch(`${base}/api/cards/${encodeURIComponent(scryfallId)}/matches?min_score=${minScore}`);
  if (!r.ok) throw new Error(await r.text());
  const j = await r.json();
  return j.matches as DeckMatch[];
}

export type CardMatch = {
  scryfall_id: string;
  name: string;
  type_line: string | null;
  image_uri_normal: string | null;
};

export async function resolveCard(query: string): Promise<{ matches: CardMatch[] }> {
  const r = await fetch(`${base}/api/cards/resolve?q=${encodeURIComponent(query)}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type DeckCsvRowError = { row_index: number; error: string };

export async function importDeckCsvNew(
  file: File,
  deckName: string,
  format: string,
  status: string,
): Promise<{ deck: DeckDetail; row_errors: DeckCsvRowError[] }> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("deck_name", deckName);
  fd.append("format", format);
  fd.append("status", status);
  const r = await fetch(`${base}/api/decks/import-csv`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function importDeckCsvAppend(
  deckId: number,
  file: File,
): Promise<{ deck: DeckDetail; row_errors: DeckCsvRowError[] }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${base}/api/decks/${deckId}/import-csv`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function importDeckTextNew(
  deckListText: string,
  deckName: string,
  format: string,
  status: string,
): Promise<{ deck: DeckDetail; row_errors: DeckCsvRowError[] }> {
  const fd = new FormData();
  fd.append("text", deckListText);
  fd.append("deck_name", deckName);
  fd.append("format", format);
  fd.append("status", status);
  const r = await fetch(`${base}/api/decks/import-text`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function importDeckTextAppend(
  deckId: number,
  deckListText: string,
): Promise<{ deck: DeckDetail; row_errors: DeckCsvRowError[] }> {
  const fd = new FormData();
  fd.append("text", deckListText);
  const r = await fetch(`${base}/api/decks/${deckId}/import-text`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchTextImportProgress(deckId: number): Promise<TextImportProgress | null> {
  const r = await fetch(`${base}/api/decks/${deckId}/import-progress`);
  if (!r.ok) return null;
  return r.json();
}

// ─── Enrichment ──────────────────────────────────────────────────────────────

export type EnrichmentStatus = {
  total_cards: number;
  profiled_cards: number;
  unprofiled_cards: number;
  keywords_missing: number;
  profile_schema_version: string;
  taxonomy_version: string;
  enrichment_provider: string;
  enrichment_model: string;
  provider_configured: boolean;
  paid_requests_enabled: boolean;
  model_prices: { input: number; output: number } | null;
  avg_input_tokens_per_card: number | null;
  avg_output_tokens_per_card: number | null;
  estimated_cost_all_unprofiled: number;
  embedding_provider: string;
  embedding_model: string;
  embedding_dimensions: number;
  embedding_index_version: string;
  embedding_provider_configured: boolean;
  embedded_cards: number;
  unembedded_cards: number;
  avg_embedding_tokens_per_card: number | null;
  estimated_cost_all_unembedded: number;
};

export type EnrichmentJob = {
  status: "running" | "done" | "error";
  type: string;
  processed: number;
  total: number;
  failed?: number;
  failed_cards?: string[];
  error?: string;
  input_tokens?: number;
  estimated_cost?: number;
};

export type OpenAIUsageRecord = {
  id: string;
  workflow: string;
  model: string;
  status: "reserved" | "completed" | "failed";
  estimated_max_cost_usd: number;
  actual_cost_usd: number | null;
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  output_tokens: number;
  created_at: string;
};

export type OpenAIUsageSummary = {
  requests_enabled: boolean;
  month: string;
  monthly_budget_usd: number;
  single_request_limit_usd: number;
  spent_usd: number;
  reserved_usd: number;
  remaining_usd: number;
  pricing_version: string;
  record_count: number;
  recent: OpenAIUsageRecord[];
  notice: string;
};

export type MechanicHook = {
  verb: string;
  mechanic: string;
  scope: string;
  condition: string;
  evidence: string;
};

export type MechanicProfileSample = {
  name: string;
  type_line: string | null;
  oracle_text: string | null;
  keywords: string[];
  profile: {
    schema_version: string;
    taxonomy_version: string;
    oracle_id: string;
    card_name: string;
    roles: string[];
    hooks: MechanicHook[];
    universal_utility: { tier: string; reasons: string[] };
    confidence: number;
  };
  provider: string;
  model: string;
  created_at: string;
};

export async function fetchEnrichmentStatus(): Promise<EnrichmentStatus> {
  const r = await fetch(`${base}/api/enrichment/status`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchOpenAIUsage(): Promise<OpenAIUsageSummary> {
  const r = await fetch(`${base}/api/openai/usage`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function startScryfallBackfill(batchSize: number): Promise<{ job_id: string }> {
  const r = await fetch(`${base}/api/enrichment/backfill-scryfall`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ batch_size: batchSize }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function startStructuredEnrichment(batchSize: number): Promise<{ job_id: string }> {
  const r = await fetch(`${base}/api/enrichment/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ batch_size: batchSize }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function startSemanticIndex(batchSize: number): Promise<{ job_id: string }> {
  const r = await fetch(`${base}/api/enrichment/index-embeddings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ batch_size: batchSize }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchEnrichmentProgress(jobId: string): Promise<EnrichmentJob | null> {
  const r = await fetch(`${base}/api/enrichment/progress/${encodeURIComponent(jobId)}`);
  if (!r.ok) return null;
  return r.json();
}

export async function fetchEnrichmentSample(n = 20): Promise<MechanicProfileSample[]> {
  const r = await fetch(`${base}/api/enrichment/sample?n=${n}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type QualityEvaluationCase = {
  id: string;
  group: "profile" | "interaction" | "retrieval" | "legality" | "construction";
  category: string;
  status: "passed" | "failed" | "skipped";
  subject: string;
  reason?: string;
  expected?: Record<string, unknown>;
  actual?: Record<string, unknown>;
};

export type QualityEvaluationReport = {
  suite_version: string;
  profile_schema_version: string;
  taxonomy_version: string;
  retrieval_version: string;
  generated_at: string;
  network_requests: number;
  summary: {
    total: number;
    passed: number;
    failed: number;
    skipped: number;
    coverage: number;
    pass_rate: number | null;
  };
  categories: Record<string, {
    passed: number;
    failed: number;
    skipped: number;
    pass_rate: number | null;
  }>;
  cases: QualityEvaluationCase[];
};

export async function fetchQualityEvaluation(): Promise<QualityEvaluationReport> {
  const r = await fetch(`${base}/api/evaluations/mtg-quality`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// ─── Deckbuilding ─────────────────────────────────────────────────────────────

export type DeckbuildingResult = {
  viability?: "strong" | "playable" | "weak" | "insufficient";
  viability_note?: string;
  commander?: string;
  reasoning?: string;
  decklist?: string;
  key_synergies?: string[];
  missing_staples?: string[];
  // suggest mode
  theme_assessment?: string;
  suggestions?: { name: string; reason: string }[];
  cards_to_consider_cutting?: { name: string; reason: string }[];
  // audit mode
  overall_assessment?: string;
  strategy_assessment?: string;
  suggested_cuts?: { name: string; reason: string }[];
  suggested_additions?: { name: string; replaces: string | null; reason: string }[];
  strengths?: string[];
  weaknesses?: string[];
  strategic_packages?: StrategyPackageProposal[];
  reasoning_provenance?: {
    provider: string;
    model: string;
    schema_version: string;
  };
  review_provenance?: {
    provider: string;
    model: string;
    schema_version: string;
  };
  optimizer?: DeckOptimizerResult;
};

export type StrategyPackageProposal = {
  name: string;
  purpose: string;
  card_names: string[];
  priority: number;
  minimum_cards: number;
  maximum_cards: number;
};

export type DeckOptimizerResult = {
  version: string;
  feasible: boolean;
  commander: string | null;
  entries: {
    oracle_id: string;
    scryfall_id: string;
    name: string;
    quantity: number;
    is_commander: boolean;
    selection_score: number;
  }[];
  decklist: string;
  package_report: {
    name: string;
    purpose: string;
    priority: number;
    minimum_cards: number;
    maximum_cards: number;
    included_cards: string[];
    included_count: number;
    minimum_satisfied: boolean;
  }[];
  objective_score: number;
  validation: {
    valid: boolean;
    checks: Record<string, boolean>;
    errors: { code: string; [key: string]: unknown }[];
  };
};

export type DeckbuildingResponse = {
  result: DeckbuildingResult;
  warnings: string[];
  pool_size: number;
  retrieval: CandidateRetrievalSummary;
  recommendation_run_id?: string;
  candidate_options?: RecommendationCandidateOption[];
};

export type RecommendationCandidateOption = {
  scryfall_id: string;
  oracle_id: string;
  name: string;
  mana_cost: string | null;
  cmc: number;
  type_line: string | null;
  color_identity: string;
  owned_quantity: number;
  deterministic_roles: string[];
  structured_roles: string[];
  retrieval: {
    version: string;
    total_score: number;
    components: CandidateScoreComponents;
    semantic?: SemanticScoreProvenance;
    reasons: string[];
  };
};

export type RecommendationDraftEntry = {
  scryfall_id: string;
  oracle_id: string;
  name: string;
  quantity: number;
  is_commander: boolean;
};

export type DraftValidation = {
  valid: boolean;
  checks: Record<string, boolean>;
  errors: { code: string; [key: string]: unknown }[];
};

export async function validateRecommendationDraft(
  runId: string,
  entries: RecommendationDraftEntry[],
): Promise<{ validation: DraftValidation; decklist: string }> {
  const r = await fetch(`${base}/api/deckbuilding/recommendations/${encodeURIComponent(runId)}/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entries }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function saveRecommendationDraft(
  runId: string,
  deckName: string,
  entries: RecommendationDraftEntry[],
  feedback?: { rating?: number; notes?: string },
): Promise<{ deck: DeckDetail; validation: DraftValidation; feedback_id: number }> {
  const r = await fetch(`${base}/api/deckbuilding/recommendations/${encodeURIComponent(runId)}/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ deck_name: deckName, entries, ...feedback }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function submitRecommendationFeedback(
  runId: string,
  body: {
    outcome: "accepted" | "edited" | "rejected";
    rating?: number;
    notes?: string;
    entries: RecommendationDraftEntry[];
  },
): Promise<{
  feedback_id: number;
  outcome: string;
  added_or_increased: Record<string, number>;
  removed_or_decreased: Record<string, number>;
}> {
  const r = await fetch(`${base}/api/deckbuilding/recommendations/${encodeURIComponent(runId)}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type CandidateScoreComponents = {
  role: number;
  mechanic_relationship: number;
  semantic: number;
  known_combo: number;
  universal_utility: number;
  functional_role: number;
  basic_land_floor: number;
  user_feedback: number;
  anti_synergy_penalty: number;
};

export type CandidateScore = {
  name: string;
  owned_quantity: number;
  version: string;
  total_score: number;
  components: CandidateScoreComponents;
  semantic?: SemanticScoreProvenance;
  reasons: string[];
};

export type SemanticScoreProvenance = {
  source: "openai_embedding" | "lexical_fallback";
  similarity: number;
  embedding_similarity: number | null;
  lexical_similarity: number;
};

export type CandidateRetrievalSummary = {
  version: string;
  component_ranges: Record<keyof CandidateScoreComponents, [number, number]>;
  candidates: CandidateScore[];
};

export async function retrieveDeckCandidates(
  query: string,
  options: {
    seedNames?: string[];
    commanderName?: string;
    excludeNames?: string[];
    limit?: number;
  } = {},
): Promise<{ pool_size: number; retrieval: CandidateRetrievalSummary }> {
  const r = await fetch(`${base}/api/deckbuilding/candidates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      seed_names: options.seedNames ?? [],
      commander_name: options.commanderName ?? null,
      exclude_names: options.excludeNames ?? [],
      limit: options.limit ?? 100,
    }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function buildDeckFromTheme(
  theme: string,
  commanderName?: string,
): Promise<DeckbuildingResponse> {
  const r = await fetch(`${base}/api/deckbuilding/build`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ theme, commander_name: commanderName ?? null }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function suggestDeckAdditions(
  currentList: string,
  themeHint?: string,
): Promise<DeckbuildingResponse> {
  const r = await fetch(`${base}/api/deckbuilding/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current_list: currentList, theme_hint: themeHint ?? null }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function auditDeck(decklist: string): Promise<DeckbuildingResponse> {
  const r = await fetch(`${base}/api/deckbuilding/audit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decklist }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
