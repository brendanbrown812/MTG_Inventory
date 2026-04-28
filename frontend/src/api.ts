const base = "";

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

export type Deck = {
  id: number;
  name: string;
  format: string;
  status: string;
  notes: string | null;
  commander_scryfall_id: string | null;
};

export type DeckCard = {
  id: number;
  scryfall_id: string;
  quantity: number;
  is_commander: boolean;
  is_sideboard: boolean;
  card: Card | null;
};

export type DeckDetail = Deck & { cards: DeckCard[] };

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

export async function deleteInventoryLine(id: number): Promise<void> {
  const r = await fetch(`${base}/api/inventory/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
}

export async function clearInventory(): Promise<{ deleted: number }> {
  const r = await fetch(`${base}/api/inventory/clear`, { method: "POST" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type ManaboxProgress = {
  batches_done: number;
  batches_total: number;
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
  if (!r.ok) throw new Error(await r.text());
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

export async function deleteDeck(id: number): Promise<void> {
  const r = await fetch(`${base}/api/decks/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
}

export type CardDeckMembership = {
  deck_id: number;
  deck_name: string;
  is_commander: boolean;
};

export async function fetchCardDecks(scryfallId: string): Promise<CardDeckMembership[]> {
  const r = await fetch(`${base}/api/cards/${encodeURIComponent(scryfallId)}/decks`);
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
  addToCollection: boolean
): Promise<{ deck: DeckDetail; row_errors: DeckCsvRowError[] }> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("deck_name", deckName);
  fd.append("format", format);
  fd.append("status", status);
  fd.append("add_to_collection", addToCollection ? "true" : "false");
  const r = await fetch(`${base}/api/decks/import-csv`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function importDeckCsvAppend(
  deckId: number,
  file: File,
  addToCollection: boolean,
): Promise<{ deck: DeckDetail; row_errors: DeckCsvRowError[] }> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("add_to_collection", addToCollection ? "true" : "false");
  const r = await fetch(`${base}/api/decks/${deckId}/import-csv`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function importDeckTextNew(
  deckListText: string,
  deckName: string,
  format: string,
  status: string,
  addToCollection: boolean
): Promise<{ deck: DeckDetail; row_errors: DeckCsvRowError[] }> {
  const fd = new FormData();
  fd.append("text", deckListText);
  fd.append("deck_name", deckName);
  fd.append("format", format);
  fd.append("status", status);
  fd.append("add_to_collection", addToCollection ? "true" : "false");
  const r = await fetch(`${base}/api/decks/import-text`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function importDeckTextAppend(
  deckId: number,
  deckListText: string,
  addToCollection: boolean,
): Promise<{ deck: DeckDetail; row_errors: DeckCsvRowError[] }> {
  const fd = new FormData();
  fd.append("text", deckListText);
  fd.append("add_to_collection", addToCollection ? "true" : "false");
  const r = await fetch(`${base}/api/decks/${deckId}/import-text`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchTextImportProgress(deckId: number): Promise<TextImportProgress | null> {
  const r = await fetch(`${base}/api/decks/${deckId}/import-progress`);
  if (!r.ok) return null;
  return r.json();
}
