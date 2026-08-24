from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── Schema migrations ────────────────────────────────────────────────────────
# Forward-only versioned migrations for ALTER TABLE changes on existing tables.
# New tables are created by Base.metadata.create_all() in main.py.
# To extend: append a new (version, sql) tuple. Never edit existing entries.
#
# Fresh DB: create_all creates all columns; migrations catch "duplicate column"
# errors from SQLite and mark them applied, so both paths are safe.

_MIGRATIONS: list[tuple[int, str]] = [
    (1, "ALTER TABLE card_cache ADD COLUMN keywords TEXT"),
    (2, "ALTER TABLE card_cache ADD COLUMN synergy_tags TEXT"),
    (3, "ALTER TABLE card_cache ADD COLUMN tagged_at DATETIME"),
]


def _table_exists(conn, table_name: str) -> bool:
    return conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).first() is not None


def _foreign_key_targets(conn, table_name: str) -> set[str]:
    return {row[2] for row in conn.exec_driver_sql(f'PRAGMA foreign_key_list("{table_name}")')}


def _migrate_oracle_printings(conn) -> None:
    """Normalize legacy card_cache without deleting it.

    Base.metadata.create_all() has already created oracle_cards and
    card_printings. Existing holding/deck tables are rebuilt only when their
    foreign key still targets the legacy table.
    """
    if not _table_exists(conn, "card_cache"):
        return

    conn.execute(text("""
        INSERT OR IGNORE INTO oracle_cards (
            oracle_id, name, type_line, oracle_text, mana_cost, cmc, colors,
            color_identity, legalities_json, keywords, synergy_tags, tagged_at,
            updated_at
        )
        SELECT
            c.oracle_id, c.name, c.type_line, c.oracle_text, c.mana_cost,
            c.cmc, c.colors, c.color_identity, c.legalities_json, c.keywords,
            c.synergy_tags, c.tagged_at, c.updated_at
        FROM card_cache c
        WHERE c.rowid = (
            SELECT c2.rowid
            FROM card_cache c2
            WHERE c2.oracle_id = c.oracle_id
            ORDER BY (c2.tagged_at IS NOT NULL) DESC,
                     c2.tagged_at DESC,
                     c2.updated_at DESC,
                     c2.rowid DESC
            LIMIT 1
        )
    """))

    conn.execute(text("""
        INSERT OR IGNORE INTO card_printings (
            scryfall_id, oracle_id, set_code, collector_number, rarity,
            language, image_uri_normal, scryfall_json, updated_at
        )
        SELECT
            c.scryfall_id,
            c.oracle_id,
            COALESCE(
                CASE WHEN json_valid(c.scryfall_json)
                     THEN json_extract(c.scryfall_json, '$.set') END,
                (SELECT MAX(i.set_code) FROM inventory_lines i
                 WHERE i.scryfall_id = c.scryfall_id)
            ),
            COALESCE(
                CASE WHEN json_valid(c.scryfall_json)
                     THEN json_extract(c.scryfall_json, '$.collector_number') END,
                (SELECT MAX(i.collector_number) FROM inventory_lines i
                 WHERE i.scryfall_id = c.scryfall_id)
            ),
            c.rarity,
            CASE WHEN json_valid(c.scryfall_json)
                 THEN json_extract(c.scryfall_json, '$.lang') END,
            c.image_uri_normal,
            c.scryfall_json,
            c.updated_at
        FROM card_cache c
    """))

    missing_oracles = conn.execute(text("""
        SELECT COUNT(*) FROM card_cache c
        LEFT JOIN oracle_cards o ON o.oracle_id = c.oracle_id
        WHERE o.oracle_id IS NULL
    """)).scalar_one()
    missing_printings = conn.execute(text("""
        SELECT COUNT(*) FROM card_cache c
        LEFT JOIN card_printings p ON p.scryfall_id = c.scryfall_id
        WHERE p.scryfall_id IS NULL
    """)).scalar_one()
    if missing_oracles or missing_printings:
        raise RuntimeError(
            "Migration 4 copy validation failed: "
            f"missing_oracles={missing_oracles}, missing_printings={missing_printings}"
        )

    deck_columns = {
        row[1] for row in conn.exec_driver_sql("PRAGMA table_info('decks')").fetchall()
    }
    if "commander_oracle_id" not in deck_columns:
        conn.exec_driver_sql(
            "ALTER TABLE decks ADD COLUMN commander_oracle_id VARCHAR(36) "
            "REFERENCES oracle_cards (oracle_id)"
        )
    conn.exec_driver_sql("""
        UPDATE decks
        SET commander_oracle_id = (
            SELECT p.oracle_id FROM card_printings p
            WHERE p.scryfall_id = decks.commander_scryfall_id
        )
        WHERE commander_scryfall_id IS NOT NULL
          AND commander_oracle_id IS NULL
    """)
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_decks_commander_oracle_id "
        "ON decks (commander_oracle_id)"
    )

    if "card_cache" in _foreign_key_targets(conn, "inventory_lines"):
        inventory_count = conn.execute(text("SELECT COUNT(*) FROM inventory_lines")).scalar_one()
        conn.exec_driver_sql("DROP TABLE IF EXISTS inventory_lines_v4")
        conn.exec_driver_sql("""
            CREATE TABLE inventory_lines_v4 (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                scryfall_id VARCHAR(36) NOT NULL
                    REFERENCES card_printings (scryfall_id),
                quantity INTEGER NOT NULL DEFAULT 1,
                foil BOOLEAN NOT NULL DEFAULT 0,
                misprint BOOLEAN NOT NULL DEFAULT 0,
                altered BOOLEAN NOT NULL DEFAULT 0,
                condition VARCHAR(20),
                language VARCHAR(20),
                set_code VARCHAR(10),
                collector_number VARCHAR(20),
                purchase_price FLOAT,
                purchase_currency VARCHAR(10),
                manabox_id VARCHAR(64),
                CONSTRAINT uq_inv_line UNIQUE
                    (scryfall_id, foil, condition, language)
            )
        """)
        conn.exec_driver_sql("""
            INSERT INTO inventory_lines_v4
            SELECT id, scryfall_id, quantity, foil, misprint, altered,
                   condition, language, set_code, collector_number,
                   purchase_price, purchase_currency, manabox_id
            FROM inventory_lines
        """)
        migrated_inventory_count = conn.execute(
            text("SELECT COUNT(*) FROM inventory_lines_v4")
        ).scalar_one()
        if migrated_inventory_count != inventory_count:
            raise RuntimeError(
                "Migration 4 inventory validation failed: "
                f"before={inventory_count}, copied={migrated_inventory_count}"
            )
        conn.exec_driver_sql("DROP TABLE inventory_lines")
        conn.exec_driver_sql("ALTER TABLE inventory_lines_v4 RENAME TO inventory_lines")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_inventory_lines_scryfall_id "
            "ON inventory_lines (scryfall_id)"
        )

    if "card_cache" in _foreign_key_targets(conn, "deck_cards"):
        deck_card_count = conn.execute(text("SELECT COUNT(*) FROM deck_cards")).scalar_one()
        conn.exec_driver_sql("DROP TABLE IF EXISTS deck_cards_v4")
        conn.exec_driver_sql("""
            CREATE TABLE deck_cards_v4 (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER NOT NULL REFERENCES decks (id),
                scryfall_id VARCHAR(36) NOT NULL
                    REFERENCES card_printings (scryfall_id),
                oracle_id VARCHAR(36) NOT NULL REFERENCES oracle_cards (oracle_id),
                quantity INTEGER NOT NULL DEFAULT 1,
                is_commander BOOLEAN NOT NULL DEFAULT 0,
                is_sideboard BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        conn.exec_driver_sql("""
            INSERT INTO deck_cards_v4
            SELECT d.id, d.deck_id, d.scryfall_id, p.oracle_id,
                   d.quantity, d.is_commander, d.is_sideboard
            FROM deck_cards d
            JOIN card_printings p ON p.scryfall_id = d.scryfall_id
        """)
        migrated_deck_card_count = conn.execute(
            text("SELECT COUNT(*) FROM deck_cards_v4")
        ).scalar_one()
        if migrated_deck_card_count != deck_card_count:
            raise RuntimeError(
                "Migration 4 deck validation failed: "
                f"before={deck_card_count}, copied={migrated_deck_card_count}"
            )
        conn.exec_driver_sql("DROP TABLE deck_cards")
        conn.exec_driver_sql("ALTER TABLE deck_cards_v4 RENAME TO deck_cards")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_deck_cards_deck_id ON deck_cards (deck_id)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_deck_cards_scryfall_id ON deck_cards (scryfall_id)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_deck_cards_oracle_id ON deck_cards (oracle_id)"
        )


def run_migrations(eng) -> None:
    with eng.connect() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_versions "
            "(version INTEGER PRIMARY KEY, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.commit()

        applied = {
            row[0]
            for row in conn.execute(text("SELECT version FROM schema_versions")).fetchall()
        }

        for version, sql in _MIGRATIONS:
            if version in applied:
                continue
            try:
                conn.execute(text(sql))
            except Exception as exc:
                # SQLite raises "duplicate column name: ..." when column already
                # exists (fresh DB created by create_all with updated model).
                message = str(exc).lower()
                if "duplicate column" not in message and not (
                    version <= 3 and "no such table: card_cache" in message
                ):
                    raise
            conn.execute(
                text("INSERT OR IGNORE INTO schema_versions (version) VALUES (:v)"),
                {"v": version},
            )
            conn.commit()

        if 4 not in applied:
            # SQLite requires this PRAGMA outside an active transaction before
            # rebuilding tables that participate in foreign keys.
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
            try:
                _migrate_oracle_printings(conn)
                violations = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError(f"Foreign key violations after migration 4: {violations[:5]}")
                conn.execute(text("INSERT INTO schema_versions (version) VALUES (4)"))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                conn.commit()

        if 5 not in applied:
            required_columns = {
                "id", "oracle_id", "schema_version", "taxonomy_version",
                "profile_json", "provider", "model", "confidence",
                "is_current", "input_tokens", "output_tokens", "created_at",
            }
            if not _table_exists(conn, "mechanic_profiles"):
                raise RuntimeError(
                    "Migration 5 requires mechanic_profiles to be created from model metadata"
                )
            actual_columns = {
                row[1]
                for row in conn.exec_driver_sql(
                    "PRAGMA table_info('mechanic_profiles')"
                ).fetchall()
            }
            missing_columns = required_columns - actual_columns
            if missing_columns:
                raise RuntimeError(
                    "Migration 5 mechanic_profiles is missing columns: "
                    + ", ".join(sorted(missing_columns))
                )
            conn.execute(text("INSERT INTO schema_versions (version) VALUES (5)"))
            conn.commit()

        if 6 not in applied:
            required_tables = {
                "recommendation_runs",
                "recommendation_feedback",
                "recommendation_card_preferences",
            }
            missing_tables = {
                table_name for table_name in required_tables
                if not _table_exists(conn, table_name)
            }
            if missing_tables:
                raise RuntimeError(
                    "Migration 6 recommendation history is missing tables: "
                    + ", ".join(sorted(missing_tables))
                )
            conn.execute(text("INSERT INTO schema_versions (version) VALUES (6)"))
            conn.commit()
