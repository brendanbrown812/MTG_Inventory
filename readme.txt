================================================================================
  SPELLBINDER — MTG Inventory & Deck Helper
================================================================================

WHAT THIS IS
------------
  A local web app for your Magic: The Gathering collection and Commander
  decks. Import a ManaBox CSV (including bulk adds from drafts and sealed —
  no deck list is required for those; just import). The app caches card
  data from Scryfall and can suggest when new cards fit decks you are
  building or might upgrade decks you mark complete.

  Primary play mode assumed: Commander. Other constructed formats are
  supported in the deck settings for legality checks; draft/sealed pools
  are not modeled as decks (imports only).


TECH STACK
----------
  Backend
    - Python 3.10+ (tested with 3.10)
    - FastAPI — HTTP API
    - Uvicorn — ASGI server
    - SQLAlchemy — SQLite database
    - Pydantic — request/response validation
    - httpx — Scryfall API client

  Frontend
    - React 18 + TypeScript
    - Vite 5 — dev server and build
    - Tailwind CSS — styling
    - React Router — navigation

  External services
    - Scryfall API (https://api.scryfall.com) — card Oracle text, images,
      legalities, color identity, etc. Respect their rate limits on very
      large imports.


PREREQUISITES
-------------
  - Python 3.10 or newer on PATH, with the "py" launcher (Windows) or
    "python" available.
  - Node.js 18 or newer and npm (required for Vite 5 and the dev server).


FIRST-TIME SETUP
----------------
  1) Backend dependencies (from the "backend" folder):

       py -3 -m pip install -r requirements.txt

     If you do not have "py", use:

       python -m pip install -r requirements.txt

  2) Frontend dependencies (from the "frontend" folder):

       npm install


HOW TO RUN (MANUAL)
-------------------
  You need TWO terminal windows.

  Terminal A — API (from the "backend" folder):

       py -3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

  Terminal B — UI (from the "frontend" folder):

       npm run dev

  Then open a browser to:

       http://127.0.0.1:5173/

  The Vite dev server proxies "/api" to the backend, so you normally only
  use the frontend URL in the browser.

  Optional — interactive API docs (Swagger UI):

       http://127.0.0.1:8000/docs


HOW TO RUN (WINDOWS BATCH FILE)
-------------------------------
  From the project root, double-click:

       start-spellbinder.bat

  It starts the backend and frontend in separate console windows, waits a
  few seconds for them to come up, then opens the app in your default
  browser (frontend only — that is the intended way to use the UI).

  Close each console window to stop that server. If ports 8000 or 5173 are
  already in use, stop the other program or change ports in backend
  startup and frontend "vite.config.ts" (and any proxy target).


LOGS
----
  While the API runs, errors and import progress are logged to:

       backend\logs\spellbinder.log

  The same messages (at INFO and above) also appear in the API console
  window. If an import returns 500, open that file or the console for the
  full Python traceback.


DATA & CONFIGURATION
--------------------
  - SQLite database file (created on first API start):

       backend\mtg_inventory.db

  - CORS: by default the API allows http://localhost:5173 and
    http://127.0.0.1:5173. To change origins, set environment variable
    CORS_ORIGINS (comma-separated) or edit backend\app\config.py.

  - Database URL: defaults to sqlite:///./mtg_inventory.db relative to the
    current working directory when you start uvicorn (usually "backend").
    Override with DATABASE_URL in environment if needed.


MANABOX CSV IMPORT
------------------
  Export from ManaBox and upload the CSV on the Import page. Expected
  columns include at least:

       Scryfall ID, Quantity

  Full export headers (typical):

       Name, Set code, Set name, Collector number, Foil, Rarity, Quantity,
       ManaBox ID, Scryfall ID, Purchase price, Misprint, Altered,
       Condition, Language, Purchase price currency

  Rows with the same Scryfall ID + foil + condition + language merge
  quantities.


DECK MATCHING (V1)
------------------
  Heuristic scoring (not ML): format legality, Commander color identity
  when a commander Scryfall ID is set, mana value curve vs your list,
  keyword/theme overlap on Oracle text, and rough "role" hints for possible
  upgrades on completed decks. Tune logic in:

       backend\app\services\matcher.py


PRODUCTION BUILD (OPTIONAL)
---------------------------
  Frontend static build:

       cd frontend
       npm run build

  Serve the "frontend\dist" folder with any static host; you must
  configure that host to forward API requests to your FastAPI instance, or
  set the frontend API base URL to the real API origin (currently the app
  uses same-origin "/api" with Vite proxy in development).


TROUBLESHOOTING
---------------

  "Site can't be reached" (browser) / blank page
    - The UI did not start. Most often: Node.js is too OLD. In the UI
      console, errors like "Unexpected token '??='" mean you need Node 18+.
      Check:  node -v
      Fix: install Node 20 LTS from https://nodejs.org/ , then close all
      Command Prompt windows, open a new one, run npm install again in the
      "frontend" folder if needed, and retry start-spellbinder.bat
    - Port 5173 in use: another Vite/old UI window is still running.
      Close it or see "Port already in use" below.

  "only one usage of each socket address" / port 8000 in use
    - A previous API server is still running (often an old console left
      open from an earlier run of this project or another app on 8000).
    - Fix A: close the "Spellbinder — API" window from the last run.
    - Fix B: find and kill the process (run in cmd):
        netstat -ano | findstr ":8000" | findstr "LISTENING"
      The last number on the line is the PID. Then:
        taskkill /PID <pid> /F

  Port 5173 already in use
    - Same idea as 8000: close the Spellbinder UI console or find the PID
      with LISTENING on 5173 and taskkill it.

  start-spellbinder.bat exits before opening the browser
    - Read the [ERROR] lines it prints — it checks Node 18+, Python, and
      free ports 8000/5173 before starting anything.

  API errors on import
    - Check internet; Scryfall must be reachable.

  "Python was not found"
    - Install Python and ensure "py" or "python" is on PATH.

  Import very large
    - Scryfall may rate-limit; split CSV or wait between runs if you hit
      errors.


LICENSE / ATTRIBUTION
---------------------
  Card information is provided by Scryfall. Magic: The Gathering is a
  trademark of Wizards of the Coast. This project is not affiliated with
  Wizards of the Coast or Scryfall.

================================================================================
