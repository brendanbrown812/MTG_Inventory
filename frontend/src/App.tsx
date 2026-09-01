import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { clearApiKey, fetchAuthStatus, setApiKey } from "./api";
import DeckDetailPage from "./pages/DeckDetailPage";
import DeckAssemblyPage from "./pages/DeckAssemblyPage";
import DeckbuildingPage from "./pages/DeckbuildingPage";
import DecksPage from "./pages/DecksPage";
import EnrichmentPage from "./pages/EnrichmentPage";
import ImportPage from "./pages/ImportPage";
import InventoryPage from "./pages/InventoryPage";

const nav = [
  { to: "/", label: "Collection" },
  { to: "/import", label: "Import" },
  { to: "/decks", label: "Decks" },
  { to: "/assembly", label: "Assembly" },
  { to: "/deckbuilding", label: "Deckbuilding" },
  { to: "/enrichment", label: "Enrich" },
];

function AppShell() {
  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-ink-800 via-ink-950 to-ink-950">
      <header className="sticky top-0 z-40 border-b border-white/5 bg-ink-950/80 backdrop-blur-md">
        <div className="flex w-full items-center justify-between gap-6 px-4 py-4 sm:px-6 lg:px-8 2xl:px-10">
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
      <main className="w-full px-4 py-8 sm:px-6 sm:py-10 lg:px-8 2xl:px-10">
        <Routes>
          <Route path="/" element={<InventoryPage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/decks" element={<DecksPage />} />
          <Route path="/decks/:id" element={<DeckDetailPage />} />
          <Route path="/assembly" element={<DeckAssemblyPage />} />
          <Route path="/deckbuilding" element={<DeckbuildingPage />} />
          <Route path="/enrichment" element={<EnrichmentPage />} />
        </Routes>
      </main>
      <footer className="border-t border-white/5 py-8 text-center text-xs text-stone-600">
        Card data © Wizards of the Coast — fetched via Scryfall. Not affiliated.
      </footer>
    </div>
  );
}

export default function App() {
  const [checking, setChecking] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [apiReachable, setApiReachable] = useState(true);
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function checkAuthentication() {
    setChecking(true);
    try {
      const status = await fetchAuthStatus();
      setApiReachable(true);
      setAuthenticated(status.authenticated);
      setError(status.authenticated ? null : "Enter the API key configured for this Spellbinder server.");
    } catch {
      setApiReachable(false);
      setAuthenticated(false);
      setError("Could not contact the Spellbinder API.");
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    void checkAuthentication();
  }, []);

  async function submitKey(e: React.FormEvent) {
    e.preventDefault();
    setApiKey(key);
    await checkAuthentication();
  }

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink-950 text-sm text-stone-400">
        Connecting to Spellbinder…
      </div>
    );
  }

  if (!authenticated) {
    if (!apiReachable) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-ink-950 px-4">
          <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-ink-900/70 p-6 shadow-card">
            <h1 className="font-display text-3xl font-semibold text-stone-100">Spellbinder</h1>
            <p className="mt-2 text-sm text-stone-400">The frontend is running, but the API is not reachable.</p>
            {error && <p className="mt-3 text-xs text-red-300">{error}</p>}
            <p className="mt-3 text-xs leading-5 text-stone-500">
              Check the Spellbinder API console for its startup error, then retry.
            </p>
            <button
              type="button"
              onClick={() => void checkAuthentication()}
              className="mt-4 w-full rounded-xl bg-ember-500/25 px-4 py-2 font-medium text-ember-100 ring-1 ring-ember-400/30"
            >
              Retry connection
            </button>
          </div>
        </div>
      );
    }

    return (
      <div className="flex min-h-screen items-center justify-center bg-ink-950 px-4">
        <form
          onSubmit={(e) => void submitKey(e)}
          className="w-full max-w-sm rounded-2xl border border-white/10 bg-ink-900/70 p-6 shadow-card"
        >
          <h1 className="font-display text-3xl font-semibold text-stone-100">Spellbinder</h1>
          <p className="mt-2 text-sm text-stone-400">This server requires an API key.</p>
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="current-password"
            autoFocus
            placeholder="API key"
            className="mt-5 w-full rounded-xl border border-white/10 bg-ink-950/70 px-3 py-2 text-stone-100 outline-none focus:ring-2 focus:ring-ember-400/40"
          />
          {error && <p className="mt-2 text-xs text-red-300">{error}</p>}
          <button
            type="submit"
            disabled={!key.trim()}
            className="mt-4 w-full rounded-xl bg-ember-500/25 px-4 py-2 font-medium text-ember-100 ring-1 ring-ember-400/30 disabled:opacity-40"
          >
            Unlock
          </button>
          <button
            type="button"
            onClick={() => {
              clearApiKey();
              setKey("");
              setError(null);
            }}
            className="mt-3 w-full text-xs text-stone-600 hover:text-stone-400"
          >
            Clear saved session key
          </button>
        </form>
      </div>
    );
  }

  return <AppShell />;
}
