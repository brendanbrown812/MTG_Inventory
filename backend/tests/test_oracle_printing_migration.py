from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, text

from app.database import Base, run_migrations


ORACLE_ID = "10000000-0000-4000-8000-000000000001"
PRINTING_A = "20000000-0000-4000-8000-000000000001"
PRINTING_B = "20000000-0000-4000-8000-000000000002"


def _create_legacy_database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE card_cache (
                scryfall_id VARCHAR(36) PRIMARY KEY,
                oracle_id VARCHAR(36) NOT NULL,
                name VARCHAR(500) NOT NULL,
                type_line VARCHAR(500), oracle_text TEXT, mana_cost VARCHAR(50),
                cmc FLOAT NOT NULL, colors VARCHAR(20) NOT NULL,
                color_identity VARCHAR(20) NOT NULL, rarity VARCHAR(20),
                image_uri_normal VARCHAR(2000), legalities_json TEXT,
                scryfall_json TEXT, updated_at DATETIME NOT NULL,
                keywords TEXT, synergy_tags TEXT, tagged_at DATETIME
            );
            CREATE TABLE inventory_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scryfall_id VARCHAR(36) NOT NULL REFERENCES card_cache(scryfall_id),
                quantity INTEGER NOT NULL, foil BOOLEAN NOT NULL,
                misprint BOOLEAN NOT NULL, altered BOOLEAN NOT NULL,
                condition VARCHAR(20), language VARCHAR(20), set_code VARCHAR(10),
                collector_number VARCHAR(20), purchase_price FLOAT,
                purchase_currency VARCHAR(10), manabox_id VARCHAR(64),
                CONSTRAINT uq_inv_line UNIQUE (scryfall_id, foil, condition, language)
            );
            CREATE TABLE decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(200) NOT NULL,
                format VARCHAR(40) NOT NULL, status VARCHAR(20) NOT NULL,
                notes TEXT, commander_scryfall_id VARCHAR(36), created_at DATETIME NOT NULL
            );
            CREATE TABLE deck_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_id INTEGER NOT NULL REFERENCES decks(id),
                scryfall_id VARCHAR(36) NOT NULL REFERENCES card_cache(scryfall_id),
                quantity INTEGER NOT NULL, is_commander BOOLEAN NOT NULL,
                is_sideboard BOOLEAN NOT NULL
            );
            CREATE TABLE schema_versions (
                version INTEGER PRIMARY KEY,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO schema_versions(version) VALUES (1), (2), (3);
        """)
        card_sql = """
            INSERT INTO card_cache VALUES (
                ?, ?, 'Shared Mechanic', 'Artifact', '{T}: Add {C}.', '{1}',
                1, '', '', ?, ?, '{"commander":"legal"}', ?,
                '2026-01-01 00:00:00', '["Ward"]', ?, ?
            )
        """
        db.execute(card_sql, (
            PRINTING_A, ORACLE_ID, "rare", "https://example/a.jpg",
            '{"set":"aaa","collector_number":"1","lang":"en"}', None, None,
        ))
        db.execute(card_sql, (
            PRINTING_B, ORACLE_ID, "mythic", "https://example/b.jpg",
            '{"set":"bbb","collector_number":"2","lang":"ja"}',
            '["mana_acceleration"]', "2026-02-01 00:00:00",
        ))
        db.execute(
            "INSERT INTO inventory_lines VALUES "
            "(1, ?, 2, 0, 0, 0, 'near_mint', 'en', 'aaa', '1', NULL, NULL, NULL), "
            "(2, ?, 1, 1, 0, 0, 'good', 'ja', 'bbb', '2', NULL, NULL, NULL)",
            (PRINTING_A, PRINTING_B),
        )
        db.execute(
            "INSERT INTO decks VALUES "
            "(1, 'Preserved Deck', 'commander', 'building', NULL, ?, '2026-01-01')",
            (PRINTING_A,),
        )
        db.execute(
            "INSERT INTO deck_cards VALUES (1, 1, ?, 1, 1, 0)",
            (PRINTING_A,),
        )
        db.commit()


def test_legacy_migration_separates_oracle_printings_and_preserves_data(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    _create_legacy_database(path)
    engine = create_engine(f"sqlite:///{path.as_posix()}")

    Base.metadata.create_all(engine)
    run_migrations(engine)
    # A second startup must be a no-op.
    run_migrations(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM oracle_cards")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM card_printings")).scalar_one() == 2
        assert conn.execute(text("SELECT COUNT(*) FROM inventory_lines")).scalar_one() == 2
        assert conn.execute(text("SELECT SUM(quantity) FROM inventory_lines")).scalar_one() == 3
        assert conn.execute(text("SELECT COUNT(*) FROM decks")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM deck_cards")).scalar_one() == 1
        assert conn.execute(text(
            "SELECT oracle_id FROM deck_cards WHERE id=1"
        )).scalar_one() == ORACLE_ID
        assert conn.execute(text(
            "SELECT commander_oracle_id FROM decks WHERE id=1"
        )).scalar_one() == ORACLE_ID
        assert conn.execute(text(
            "SELECT synergy_tags FROM oracle_cards WHERE oracle_id=:oid"
        ), {"oid": ORACLE_ID}).scalar_one() == '["mana_acceleration"]'
        assert conn.execute(text(
            "SELECT set_code FROM card_printings WHERE scryfall_id=:sid"
        ), {"sid": PRINTING_B}).scalar_one() == "bbb"
        assert conn.execute(text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='card_cache'"
        )).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM schema_versions WHERE version=4"
        )).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM schema_versions WHERE version=5"
        )).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='mechanic_profiles'"
        )).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM mechanic_profiles"
        )).scalar_one() == 0
        assert conn.execute(text(
            "SELECT COUNT(*) FROM schema_versions WHERE version=6"
        )).scalar_one() == 1
        for table_name in (
            "recommendation_runs", "recommendation_feedback",
            "recommendation_card_preferences",
        ):
            assert conn.execute(text(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:name"
            ), {"name": table_name}).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM schema_versions WHERE version=7"
        )).scalar_one() == 1
        for table_name in ("oracle_embeddings", "semantic_query_embeddings"):
            assert conn.execute(text(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:name"
            ), {"name": table_name}).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM schema_versions WHERE version=8"
        )).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM schema_versions WHERE version=9"
        )).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM schema_versions WHERE version=10"
        )).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM schema_versions WHERE version=11"
        )).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM schema_versions WHERE version=12"
        )).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='deck_inventory_additions'"
        )).scalar_one() == 1
        allocation_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info('deck_cards')")
        }
        assert {"grabbed_quantity", "proxy_quantity"} <= allocation_columns
        assert conn.execute(text(
            "SELECT grabbed_quantity + proxy_quantity FROM deck_cards"
        )).scalar_one() == 0
        migrated_allocation = conn.execute(text(
            "SELECT deck_card_id, scryfall_id, status, quantity "
            "FROM deck_card_allocations"
        )).one()
        assert migrated_allocation == (1, None, "pending", 1)
        assert conn.execute(text(
            "SELECT SUM(quantity) FROM deck_card_allocations "
            "WHERE deck_card_id = 1"
        )).scalar_one() == conn.execute(text(
            "SELECT quantity FROM deck_cards WHERE id = 1"
        )).scalar_one()
        assert conn.execute(text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='openai_usage_records'"
        )).scalar_one() == 1
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert {row[2] for row in conn.exec_driver_sql(
            "PRAGMA foreign_key_list('inventory_lines')"
        )} == {"card_printings"}
        assert {row[2] for row in conn.exec_driver_sql(
            "PRAGMA foreign_key_list('deck_cards')"
        )} == {"decks", "card_printings", "oracle_cards"}
        assert {row[2] for row in conn.exec_driver_sql(
            "PRAGMA foreign_key_list('deck_card_allocations')"
        )} == {"deck_cards", "card_printings"}

    engine.dispose()


def test_migration_11_repairs_commander_pointer_and_infers_treatment(
    tmp_path: Path,
) -> None:
    path = tmp_path / "migration-11.db"
    _create_legacy_database(path)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    run_migrations(engine)

    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE decks SET commander_scryfall_id=NULL, commander_oracle_id=NULL"
        ))
        conn.execute(text(
            "UPDATE deck_cards SET grabbed_quantity=1, proxy_quantity=0"
        ))
        conn.execute(text(
            "UPDATE deck_card_allocations "
            "SET status='grabbed', scryfall_id=:sid, foil=NULL"
        ), {"sid": PRINTING_A})
        conn.execute(text("DELETE FROM schema_versions WHERE version=11"))

    run_migrations(engine)
    run_migrations(engine)
    with engine.connect() as conn:
        repaired = conn.execute(text(
            "SELECT commander_scryfall_id, commander_oracle_id FROM decks WHERE id=1"
        )).one()
        assert repaired == (PRINTING_A, ORACLE_ID)
        assert conn.execute(text(
            "SELECT foil FROM deck_card_allocations WHERE deck_card_id=1"
        )).scalar_one() == 0
        assert conn.execute(text(
            "SELECT COUNT(*) FROM schema_versions WHERE version=11"
        )).scalar_one() == 1

    engine.dispose()
