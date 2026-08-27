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

        if 7 not in applied:
            required = {
                "oracle_embeddings": {
                    "id", "oracle_id", "provider", "model", "index_version",
                    "dimensions", "source_hash", "vector", "is_current",
                    "input_tokens", "created_at",
                },
                "semantic_query_embeddings": {
                    "id", "provider", "model", "index_version", "dimensions",
                    "source_hash", "vector", "input_tokens", "created_at",
                },
            }
            for table_name, required_columns in required.items():
                if not _table_exists(conn, table_name):
                    raise RuntimeError(
                        f"Migration 7 requires {table_name} to be created from model metadata"
                    )
                actual_columns = {
                    row[1] for row in conn.exec_driver_sql(
                        f"PRAGMA table_info('{table_name}')"
                    ).fetchall()
                }
                missing_columns = required_columns - actual_columns
                if missing_columns:
                    raise RuntimeError(
                        f"Migration 7 {table_name} is missing columns: "
                        + ", ".join(sorted(missing_columns))
                    )
            conn.execute(text("INSERT INTO schema_versions (version) VALUES (7)"))
            conn.commit()

        if 8 not in applied:
            table_name = "openai_usage_records"
            required_columns = {
                "id", "workflow", "model", "status", "pricing_version",
                "estimated_max_cost_usd", "actual_cost_usd", "input_tokens",
                "cached_input_tokens", "cache_write_tokens", "output_tokens",
                "response_id", "error_type", "created_at", "completed_at",
            }
            if not _table_exists(conn, table_name):
                raise RuntimeError(
                    "Migration 8 requires openai_usage_records to be created from model metadata"
                )
            actual_columns = {
                row[1] for row in conn.exec_driver_sql(
                    "PRAGMA table_info('openai_usage_records')"
                ).fetchall()
            }
            missing_columns = required_columns - actual_columns
            if missing_columns:
                raise RuntimeError(
                    "Migration 8 openai_usage_records is missing columns: "
                    + ", ".join(sorted(missing_columns))
                )
            conn.execute(text("INSERT INTO schema_versions (version) VALUES (8)"))
            conn.commit()

        if 9 not in applied:
            deck_card_columns = {
                row[1] for row in conn.exec_driver_sql(
                    "PRAGMA table_info('deck_cards')"
                ).fetchall()
            }
            for column in ("grabbed_quantity", "proxy_quantity"):
                if column not in deck_card_columns:
                    conn.exec_driver_sql(
                        f"ALTER TABLE deck_cards ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
                    )
            invalid = conn.execute(text("""
                SELECT COUNT(*) FROM deck_cards
                WHERE grabbed_quantity < 0 OR proxy_quantity < 0
                   OR grabbed_quantity + proxy_quantity > quantity
            """)).scalar_one()
            if invalid:
                raise RuntimeError(
                    f"Migration 9 deck allocation validation failed: invalid_rows={invalid}"
                )
            conn.execute(text("INSERT INTO schema_versions (version) VALUES (9)"))
            conn.commit()

        if 10 not in applied:
            table_name = "deck_card_allocations"
            required_columns = {
                "id", "deck_card_id", "scryfall_id", "status", "quantity",
            }
            if not _table_exists(conn, table_name):
                raise RuntimeError(
                    "Migration 10 requires deck_card_allocations to be created from model metadata"
                )
            actual_columns = {
                row[1] for row in conn.exec_driver_sql(
                    "PRAGMA table_info('deck_card_allocations')"
                ).fetchall()
            }
            missing_columns = required_columns - actual_columns
            if missing_columns:
                raise RuntimeError(
                    "Migration 10 deck_card_allocations is missing columns: "
                    + ", ".join(sorted(missing_columns))
                )

            # Existing physical assignments retain their printing. Pending
            # demand becomes Any printing because old data cannot prove which
            # physical copy will eventually be pulled.
            conn.execute(text("""
                INSERT INTO deck_card_allocations (
                    deck_card_id, scryfall_id, status, quantity
                )
                SELECT id, scryfall_id, 'grabbed', grabbed_quantity
                FROM deck_cards d
                WHERE grabbed_quantity > 0
                  AND NOT EXISTS (
                      SELECT 1 FROM deck_card_allocations a
                      WHERE a.deck_card_id = d.id AND a.status = 'grabbed'
                  )
            """))
            conn.execute(text("""
                INSERT INTO deck_card_allocations (
                    deck_card_id, scryfall_id, status, quantity
                )
                SELECT id, scryfall_id, 'proxy', proxy_quantity
                FROM deck_cards d
                WHERE proxy_quantity > 0
                  AND NOT EXISTS (
                      SELECT 1 FROM deck_card_allocations a
                      WHERE a.deck_card_id = d.id AND a.status = 'proxy'
                  )
            """))
            conn.execute(text("""
                INSERT INTO deck_card_allocations (
                    deck_card_id, scryfall_id, status, quantity
                )
                SELECT id, NULL, 'pending',
                       quantity - grabbed_quantity - proxy_quantity
                FROM deck_cards d
                WHERE quantity - grabbed_quantity - proxy_quantity > 0
                  AND NOT EXISTS (
                      SELECT 1 FROM deck_card_allocations a
                      WHERE a.deck_card_id = d.id AND a.status = 'pending'
                  )
            """))

            invalid = conn.execute(text("""
                SELECT COUNT(*)
                FROM deck_cards d
                LEFT JOIN (
                    SELECT deck_card_id, SUM(quantity) AS allocated
                    FROM deck_card_allocations
                    GROUP BY deck_card_id
                ) a ON a.deck_card_id = d.id
                WHERE COALESCE(a.allocated, 0) != d.quantity
            """)).scalar_one()
            invalid_statuses = conn.execute(text("""
                SELECT COUNT(*) FROM deck_card_allocations
                WHERE quantity <= 0 OR status NOT IN ('pending', 'grabbed', 'proxy')
            """)).scalar_one()
            wrong_oracles = conn.execute(text("""
                SELECT COUNT(*)
                FROM deck_card_allocations a
                JOIN deck_cards d ON d.id = a.deck_card_id
                JOIN card_printings p ON p.scryfall_id = a.scryfall_id
                WHERE a.scryfall_id IS NOT NULL AND p.oracle_id != d.oracle_id
            """)).scalar_one()
            if invalid or invalid_statuses or wrong_oracles:
                raise RuntimeError(
                    "Migration 10 allocation validation failed: "
                    f"quantity_mismatches={invalid}, invalid_statuses={invalid_statuses}, "
                    f"wrong_oracles={wrong_oracles}"
                )
            conn.execute(text("INSERT INTO schema_versions (version) VALUES (10)"))
            conn.commit()

        if 11 not in applied:
            allocation_columns = {
                row[1] for row in conn.exec_driver_sql(
                    "PRAGMA table_info('deck_card_allocations')"
                ).fetchall()
            }
            if "foil" not in allocation_columns:
                conn.exec_driver_sql(
                    "ALTER TABLE deck_card_allocations ADD COLUMN foil BOOLEAN"
                )

            # Legacy exact grabbed assignments can safely inherit a treatment
            # only when the owned printing exists in exactly one treatment.
            conn.execute(text("""
                UPDATE deck_card_allocations AS a
                SET foil = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM inventory_lines i
                        WHERE i.scryfall_id = a.scryfall_id AND i.foil = 1
                    ) AND NOT EXISTS (
                        SELECT 1 FROM inventory_lines i
                        WHERE i.scryfall_id = a.scryfall_id AND i.foil = 0
                    ) THEN 1
                    WHEN EXISTS (
                        SELECT 1 FROM inventory_lines i
                        WHERE i.scryfall_id = a.scryfall_id AND i.foil = 0
                    ) AND NOT EXISTS (
                        SELECT 1 FROM inventory_lines i
                        WHERE i.scryfall_id = a.scryfall_id AND i.foil = 1
                    ) THEN 0
                    ELSE NULL
                END
                WHERE a.status = 'grabbed'
                  AND a.scryfall_id IS NOT NULL
                  AND a.foil IS NULL
            """))

            # Early deck records could have a flagged commander without the
            # denormalized deck pointer. Repair the unambiguous case.
            conn.execute(text("""
                UPDATE decks
                SET commander_oracle_id = (
                        SELECT dc.oracle_id FROM deck_cards dc
                        WHERE dc.deck_id = decks.id AND dc.is_commander = 1
                        LIMIT 1
                    ),
                    commander_scryfall_id = (
                        SELECT dc.scryfall_id FROM deck_cards dc
                        WHERE dc.deck_id = decks.id AND dc.is_commander = 1
                        LIMIT 1
                    )
                WHERE (
                    SELECT COUNT(*) FROM deck_cards dc
                    WHERE dc.deck_id = decks.id AND dc.is_commander = 1
                ) = 1
            """))

            invalid_treatments = conn.execute(text("""
                SELECT COUNT(*) FROM deck_card_allocations
                WHERE foil IS NOT NULL AND scryfall_id IS NULL
            """)).scalar_one()
            commander_mismatches = conn.execute(text("""
                SELECT COUNT(*)
                FROM decks d
                JOIN deck_cards dc
                  ON dc.deck_id = d.id AND dc.is_commander = 1
                WHERE (
                    SELECT COUNT(*) FROM deck_cards flagged
                    WHERE flagged.deck_id = d.id AND flagged.is_commander = 1
                ) = 1
                  AND (d.commander_oracle_id != dc.oracle_id
                       OR d.commander_scryfall_id != dc.scryfall_id
                       OR d.commander_oracle_id IS NULL
                       OR d.commander_scryfall_id IS NULL)
            """)).scalar_one()
            if invalid_treatments or commander_mismatches:
                raise RuntimeError(
                    "Migration 11 validation failed: "
                    f"invalid_treatments={invalid_treatments}, "
                    f"commander_mismatches={commander_mismatches}"
                )
            conn.execute(text("INSERT INTO schema_versions (version) VALUES (11)"))
            conn.commit()

        if 12 not in applied:
            if not _table_exists(conn, "deck_inventory_additions"):
                raise RuntimeError(
                    "Migration 12 requires the deck_inventory_additions table"
                )
            columns = {
                row[1] for row in conn.exec_driver_sql(
                    "PRAGMA table_info('deck_inventory_additions')"
                ).fetchall()
            }
            required = {"addition_id", "deck_id", "scryfall_id", "foil", "created_at"}
            missing = required - columns
            if missing:
                raise RuntimeError(
                    "Migration 12 deck inventory addition validation failed: "
                    f"missing_columns={sorted(missing)}"
                )
            conn.execute(text("INSERT INTO schema_versions (version) VALUES (12)"))
            conn.commit()
