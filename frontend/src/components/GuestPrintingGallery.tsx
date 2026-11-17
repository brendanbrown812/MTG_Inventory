import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { GuestPrinting } from "../lib/guestPrintings";

function printingLabel(printing: GuestPrinting): string {
  return [printing.setCode?.toUpperCase(), printing.collectorNumber ? `#${printing.collectorNumber}` : null].filter(Boolean).join(" · ") || "Printing not recorded";
}

export function GuestPrintingGallery({ name, printings, commander = false, children }: { name: string; printings: GuestPrinting[]; commander?: boolean; children?: ReactNode }) {
  const [index, setIndex] = useState(0);
  const [enlarged, setEnlarged] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const selected = printings[index] ?? printings[0];
  useEffect(() => {
    if (enlarged) dialog.current?.showModal();
  }, [enlarged]);
  if (!selected) return null;
  const label = `${name} — ${printingLabel(selected)}`;
  const image = (large: boolean) => selected.image ? <img
    src={selected.image} alt={label} loading={large ? "eager" : "lazy"}
    className={large ? "mx-auto max-h-[68vh] w-auto max-w-full rounded-lg object-contain" : "h-full w-full object-contain"}
  /> : <span className="flex h-full min-h-40 items-center justify-center p-4 text-center text-sm text-stone-400">{name}<br />Image unavailable for this printing</span>;
  const navigation = printings.length > 1 && <div className="flex items-center justify-between gap-2">
    <button type="button" aria-label={`Previous printing of ${name}`} onClick={() => setIndex((index + printings.length - 1) % printings.length)} className="rounded-lg border border-white/15 px-3 py-2 text-stone-200 hover:bg-white/10">‹</button>
    <span aria-live="polite" className="text-xs text-stone-400">Print {index + 1} of {printings.length}</span>
    <button type="button" aria-label={`Next printing of ${name}`} onClick={() => setIndex((index + 1) % printings.length)} className="rounded-lg border border-white/15 px-3 py-2 text-stone-200 hover:bg-white/10">›</button>
  </div>;
  return <>
    <div className="relative aspect-[5/7] overflow-hidden bg-ink-800">
      <button type="button" onClick={() => setEnlarged(true)} aria-label={`Enlarge ${label}`} className="block h-full w-full cursor-zoom-in focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ember-400">{image(false)}</button>
      <span className="pointer-events-none absolute right-2 top-2 rounded-full bg-black/80 px-2 py-1 text-xs font-semibold text-stone-100">×{selected.quantity}</span>
      {commander && <span className="pointer-events-none absolute left-2 top-2 rounded-full bg-black/85 px-2 py-1 text-xs font-semibold text-arcane-200">Commander</span>}
    </div>
    <div className="space-y-2 p-3">
      <h3 className="text-sm font-medium text-stone-100">{name}</h3>
      <p className="text-xs text-stone-400">{printingLabel(selected)} · {selected.treatment}</p>
      {selected.description && <p className="text-xs text-amber-200">{selected.description}</p>}
      {navigation}
    </div>
    {enlarged && <dialog ref={dialog} onClose={() => setEnlarged(false)} onClick={(event) => { if (event.target === event.currentTarget) dialog.current?.close(); }} aria-label={`${name} printing image`} className="m-auto max-h-[95vh] w-[min(95vw,560px)] overflow-y-auto rounded-2xl border border-white/20 bg-ink-900 p-4 text-stone-200 shadow-2xl backdrop:bg-black/80">
      <div className="mb-3 flex items-center justify-between gap-4"><h2 className="font-display text-xl">{name}</h2><button autoFocus type="button" onClick={() => dialog.current?.close()} className="rounded-lg border border-white/20 px-3 py-2" aria-label="Close image">✕</button></div>
      {image(true)}
      {children && <div className="mt-4">{children}</div>}
      <div className="mt-3 space-y-2 text-center"><p className="text-sm">{printingLabel(selected)} · {selected.treatment} · {selected.quantity} {selected.quantity === 1 ? "copy" : "copies"}</p>{selected.description && <p className="text-xs text-amber-200">{selected.description}</p>}{navigation}</div>
    </dialog>}
  </>;
}
