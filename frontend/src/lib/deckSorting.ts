import type { Card } from "../api";

export type DeckSortMode = "name" | "type" | "color";

const COLOR_ORDER = ["W", "U", "B", "R", "G"];
export const TYPE_ORDER = [
  "Legendary Creature", "Creature", "Planeswalker", "Instant", "Sorcery",
  "Artifact", "Enchantment", "Battle", "Land", "Other",
];
export const TYPE_SECTION_LABELS: Record<string, string> = {
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

function cardColorSortKey(card: Card): number {
  const colors = normalizedColors(card.colors);
  if (colors.length === 1) return COLOR_ORDER.indexOf(colors[0] ?? "");
  if (colors.length > 1) return COLOR_ORDER.length;
  return COLOR_ORDER.length + 1;
}

export function cardTypeCategory(card: Card | null): string {
  const typeLine = card?.type_line ?? "";
  if (typeLine.includes("Legendary") && typeLine.includes("Creature")) return "Legendary Creature";
  if (typeLine.includes("Creature")) return "Creature";
  for (const category of TYPE_ORDER.slice(2, -1)) {
    if (typeLine.includes(category)) return category;
  }
  return "Other";
}

function adjustedManaValue(card: Card): number {
  const variableSymbols = card.mana_cost?.match(/\{X\}/gi)?.length ?? 0;
  return card.cmc + variableSymbols;
}

export function compareDeckCards(left: Card | null, right: Card | null, mode: DeckSortMode): number {
  if (!left || !right) return left ? -1 : right ? 1 : 0;
  const primary = mode === "color"
    ? cardColorSortKey(left) - cardColorSortKey(right)
    : mode === "type"
      ? TYPE_ORDER.indexOf(cardTypeCategory(left)) - TYPE_ORDER.indexOf(cardTypeCategory(right))
      : 0;
  const manaValue = mode === "type" ? adjustedManaValue(left) - adjustedManaValue(right) : 0;
  return primary || manaValue || left.name.localeCompare(right.name);
}
