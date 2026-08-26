import type { InventoryPrinting } from "../api";

type PrintingCarouselProps = {
  cardName: string;
  printings: InventoryPrinting[];
  selectedScryfallId: string | null;
  onSelect: (printing: InventoryPrinting) => void;
};

function copySummary(printing: InventoryPrinting): string {
  const copies = `${printing.total_quantity} ${printing.total_quantity === 1 ? "copy" : "copies"}`;
  return printing.foil_quantity > 0
    ? `${copies} · ${printing.foil_quantity} foil`
    : copies;
}

export function PrintingCarousel({
  cardName,
  printings,
  selectedScryfallId,
  onSelect,
}: PrintingCarouselProps) {
  const selectedIndex = Math.max(
    0,
    printings.findIndex((printing) => printing.scryfall_id === selectedScryfallId),
  );
  const printing = printings[selectedIndex] ?? printings[0];
  if (!printing) return null;

  function move(offset: number) {
    const nextIndex = (selectedIndex + offset + printings.length) % printings.length;
    const next = printings[nextIndex];
    if (next) onSelect(next);
  }

  return (
    <div className="w-full" data-testid="printing-carousel">
      <div className="relative aspect-[5/7] overflow-hidden bg-ink-800 sm:rounded-l-2xl">
        {printing.image_uri_normal ? (
          <img
            src={printing.image_uri_normal}
            alt={`${cardName} — ${printing.set_code?.toUpperCase() ?? "unknown set"} ${printing.collector_number ?? ""}`.trim()}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full items-center justify-center p-4 text-center text-xs text-stone-500">
            {cardName}
          </div>
        )}

        {printings.length > 1 && (
          <>
            <button
              type="button"
              onClick={() => move(-1)}
              aria-label="Previous printing"
              className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-black/75 px-3 py-2 text-lg text-white shadow-lg backdrop-blur-sm transition hover:bg-black/90"
            >
              ‹
            </button>
            <button
              type="button"
              onClick={() => move(1)}
              aria-label="Next printing"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-black/75 px-3 py-2 text-lg text-white shadow-lg backdrop-blur-sm transition hover:bg-black/90"
            >
              ›
            </button>
          </>
        )}

        <div className="absolute inset-x-2 bottom-2 rounded-xl bg-black/80 px-3 py-2 text-xs text-stone-200 shadow-lg backdrop-blur-sm" aria-live="polite">
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold">
              {[printing.set_code?.toUpperCase(), printing.collector_number]
                .filter(Boolean)
                .join(" · ") || "Unknown printing"}
            </span>
            <span className="text-stone-400">
              {selectedIndex + 1} / {printings.length}
            </span>
          </div>
          <p className="mt-0.5 text-stone-300">{copySummary(printing)}</p>
        </div>
      </div>
    </div>
  );
}

