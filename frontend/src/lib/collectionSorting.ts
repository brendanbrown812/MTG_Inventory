import type { InventoryOracleGroup, InventoryPrinting } from "../api";

export const COLLECTION_PRINTING_SELECTION_KEY = "spellbinder:collection:selected-printings";
export type CollectionSortMode = "name" | "quantity" | "set";

export function readCollectionPrintingSelections(): Record<string, string> {
  try {
    const value = JSON.parse(localStorage.getItem(COLLECTION_PRINTING_SELECTION_KEY) ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
    );
  } catch {
    return {};
  }
}

export function collectionSelectedPrinting(
  group: InventoryOracleGroup,
  selections: Record<string, string>,
): InventoryPrinting | undefined {
  const savedId = selections[group.oracle_id];
  return group.printings.find((printing) => printing.scryfall_id === savedId) ?? group.printings[0];
}

export function compareCollectionCards(
  left: InventoryOracleGroup,
  right: InventoryOracleGroup,
  sort: CollectionSortMode,
  selections: Record<string, string>,
): number {
  if (sort === "quantity") {
    return right.total_quantity - left.total_quantity || left.card.name.localeCompare(right.card.name);
  }
  if (sort === "set") {
    const leftPrinting = collectionSelectedPrinting(left, selections);
    const rightPrinting = collectionSelectedPrinting(right, selections);
    const leftKey = `${leftPrinting?.set_code ?? ""}:${leftPrinting?.collector_number ?? ""}`;
    const rightKey = `${rightPrinting?.set_code ?? ""}:${rightPrinting?.collector_number ?? ""}`;
    return leftKey.localeCompare(rightKey) || left.card.name.localeCompare(right.card.name);
  }
  return left.card.name.localeCompare(right.card.name);
}
