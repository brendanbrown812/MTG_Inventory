import { Link, NavLink, Route, Routes } from "react-router-dom";
import DeckDetailPage from "./pages/DeckDetailPage";
import DecksPage from "./pages/DecksPage";
import ImportPage from "./pages/ImportPage";
import InventoryPage from "./pages/InventoryPage";

const nav = [
  { to: "/", label: "Collection" },
  { to: "/import", label: "Import" },
  { to: "/decks", label: "Decks" },
];

export default function App() {
  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-ink-800 via-ink-950 to-ink-950">
      <header className="sticky top-0 z-40 border-b border-white/5 bg-ink-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-4 py-4 sm:px-6">
          <Link
            to="/"
            className="group flex items-baseline gap-3 rounded-lg outline-none ring-ember-400/0 transition hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ember-400/50"
          >
            <span className="font-display text-2xl font-semibold tracking-tight text-stone-100 sm:text-3xl">
              Spellbinder
            </span>
            <span className="hidden text-sm text-stone-500 group-hover:text-stone-400 sm:inline">
              inventory & decks
            </span>
          </Link>
          <nav className="flex items-center gap-1 rounded-full border border-white/10 bg-ink-900/60 p-1 shadow-card">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  [
                    "rounded-full px-4 py-2 text-sm font-medium transition",
                    isActive
                      ? "bg-gradient-to-r from-ember-500/20 to-arcane-500/20 text-stone-100 ring-1 ring-ember-400/30"
                      : "text-stone-400 hover:text-stone-200",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
        <Routes>
          <Route path="/" element={<InventoryPage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/decks" element={<DecksPage />} />
          <Route path="/decks/:id" element={<DeckDetailPage />} />
        </Routes>
      </main>
      <footer className="border-t border-white/5 py-8 text-center text-xs text-stone-600">
        Card data © Wizards of the Coast — fetched via Scryfall. Not affiliated.
      </footer>
    </div>
  );
}
