import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Props = {
  src: string | null | undefined;
  name: string;
  children: React.ReactNode;
  trigger?: "hover" | "click";
};

export function CardHoverPreview({ src, name, children, trigger = "hover" }: Props) {
  const [show, setShow] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const ref = useRef<HTMLSpanElement>(null);

  const onMove = useCallback((e: React.MouseEvent) => {
    setPos({ x: e.clientX, y: e.clientY });
  }, []);

  useEffect(() => {
    if (trigger !== "click" || !show) return;
    function handleOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setShow(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [trigger, show]);

  if (!src) return <>{children}</>;

  const previewW = 280;
  const previewH = 420;
  let left = pos.x + 14;
  let top = pos.y + 14;
  if (typeof window !== "undefined") {
    if (top + previewH + 12 > window.innerHeight) {
      top = pos.y - previewH - 14;
    }
    left = Math.min(left, window.innerWidth - previewW - 12);
    top = Math.max(12, top);
    left = Math.max(12, left);
  }

  const hoverHandlers = {
    onMouseEnter: (e: React.MouseEvent) => {
      setPos({ x: e.clientX, y: e.clientY });
      setShow(true);
    },
    onMouseLeave: () => setShow(false),
    onMouseMove: onMove,
  };

  const clickHandlers = {
    onClick: (e: React.MouseEvent) => {
      e.stopPropagation();
      setPos({ x: e.clientX, y: e.clientY });
      setShow((v) => !v);
    },
  };

  const preview = show
    ? createPortal(
        <div
          className="pointer-events-none fixed z-[100] rounded-lg border border-white/20 bg-ink-900 p-2 shadow-2xl ring-1 ring-black/60"
          style={{ left, top, width: previewW }}
        >
          <img src={src} alt="" className="h-auto w-full rounded-md" />
          <div className="mt-1.5 truncate text-center text-xs text-stone-400" title={name}>
            {name}
          </div>
        </div>,
        document.body,
      )
    : null;

  return (
    <span
      ref={ref}
      className={`inline-flex${trigger === "click" ? " cursor-pointer" : ""}`}
      {...(trigger === "hover" ? hoverHandlers : clickHandlers)}
    >
      {children}
      {preview}
    </span>
  );
}
