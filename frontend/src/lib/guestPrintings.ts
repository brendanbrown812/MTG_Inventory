import type { Card, DeckCard, InventoryOracleGroup } from "../api";

export type GuestPrinting = {
  key: string;
  card: Card | null;
  image: string | null;
  setCode: string | null;
  collectorNumber: string | null;
  quantity: number;
  treatment: string;
  description?: string;
};

export function collectionGuestPrintings(group: InventoryOracleGroup): GuestPrinting[] {
  return group.printings.map((printing) => ({
    key: printing.scryfall_id,
    card: printing.card,
    image: printing.image_uri_normal ?? printing.card.image_uri_normal,
    setCode: printing.set_code,
    collectorNumber: printing.collector_number,
    quantity: printing.total_quantity,
    treatment: printing.foil_quantity > 0 ? `${printing.foil_quantity} foil · ${printing.nonfoil_quantity} nonfoil` : "Nonfoil",
  }));
}

export function deckGuestPrintings(row: DeckCard): GuestPrinting[] {
  const printings = new Map<string, GuestPrinting>();
  for (const allocation of row.allocations) {
    const key = `${allocation.scryfall_id ?? "any"}:${allocation.foil}`;
    const existing = printings.get(key);
    if (existing) {
      existing.quantity += allocation.quantity;
      continue;
    }
    // An assigned printing must never silently display a different print's art.
    const card = allocation.scryfall_id
      ? allocation.printing ?? (row.card?.scryfall_id === allocation.scryfall_id ? row.card : null)
      : row.card;
    printings.set(key, {
      key, card, image: card?.image_uri_normal ?? null,
      setCode: card?.set_code ?? null, collectorNumber: card?.collector_number ?? null,
      quantity: allocation.quantity,
      treatment: allocation.foil === true ? "Foil" : allocation.foil === false ? "Nonfoil" : "Treatment not recorded",
      description: allocation.scryfall_id
        ? card ? undefined : "Assigned printing unavailable"
        : "Any printing · example artwork",
    });
  }
  if (!printings.size) {
    return [{
      key: row.scryfall_id, card: row.card, image: row.card?.image_uri_normal ?? null,
      setCode: row.card?.set_code ?? null, collectorNumber: row.card?.collector_number ?? null,
      quantity: row.quantity, treatment: "Treatment not recorded", description: "Any printing · example artwork",
    }];
  }
  return [...printings.values()];
}

