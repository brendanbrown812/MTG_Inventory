from datetime import timedelta
import re

import pytest
from fastapi.testclient import TestClient

from app.auth_service import create_user, token_hash, utcnow
from app.config import settings
from app.database import SessionLocal
from app.guest_access import guest_cookie_name
from app.main import app
from app.models import CardPrinting, Deck, DeckCard, DeckCardAllocation, GuestAccess, GuestSession, InventoryLine, OracleCard

PASSWORD = "correct horse battery"


def admin_login(client):
    settings.auth_mode = "session"
    with SessionLocal() as db:
        create_user(db, "bbrown812", PASSWORD)
        db.commit()
    result = client.post("/api/auth/login", json={"username": "bbrown812", "password": PASSWORD})
    assert result.status_code == 200
    return {"X-CSRF-Token": result.json()["csrf_token"]}


def generate(client, headers):
    response = client.post("/api/auth/guest-link", headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()["token"]


def seed_deck():
    with SessionLocal() as db:
        oracle = OracleCard(oracle_id="oracle-one", name="Test Ring", type_line="Artifact")
        db.add(oracle)
        db.flush()
        printing = CardPrinting(scryfall_id="printing-one", oracle=oracle)
        deck = Deck(name="Friends deck", notes="Private owner notes", commander_oracle_id="oracle-one")
        db.add_all([oracle, printing, deck])
        db.flush()
        db.add(InventoryLine(scryfall_id=printing.scryfall_id, quantity=3, foil=False))
        db.add_all([
            DeckCard(deck_id=deck.id, scryfall_id=printing.scryfall_id, oracle_id=oracle.oracle_id,
                     quantity=1, is_commander=True),
            DeckCard(deck_id=deck.id, scryfall_id=printing.scryfall_id, oracle_id=oracle.oracle_id,
                     quantity=2, is_sideboard=True),
        ])
        db.commit()
        return deck.id


def test_shared_link_grants_collection_decks_and_cards_without_admin_cookie(client):
    headers = admin_login(client)
    assert client.get("/api/auth/guest-link").json()["enabled"] is False
    deck_id = seed_deck()
    token = generate(client, headers)
    with SessionLocal() as db:
        access = db.get(GuestAccess, 1)
        assert access.invite_hash == token_hash(token)
        assert token not in access.invite_hash
    with TestClient(app) as guest, TestClient(app) as friend:
        for browser in (guest, friend):
            response = browser.post("/api/auth/guest", json={"token": token})
            assert response.status_code == 200
            assert "HttpOnly" in response.headers["set-cookie"]
            assert "SameSite=strict" in response.headers["set-cookie"]
            status = browser.get("/api/auth/status").json()
            assert status["authenticated"] is True
            assert status["user"]["role"] == "guest"
            collection = browser.get("/api/guest/collection")
            assert collection.status_code == 200
            assert collection.headers["cache-control"] == "private, no-store"
            assert collection.json()[0]["total_quantity"] == 3
            assert collection.json()[0]["card"]["name"] == "Test Ring"
            decks = browser.get("/api/guest/decks").json()
            assert decks[0]["name"] == "Friends deck"
            assert decks[0]["commander_name"] == "Test Ring"
            assert decks[0]["notes"] is None
            detail = browser.get(f"/api/guest/decks/{deck_id}").json()
            assert detail["notes"] is None
            assert sum(card["quantity"] for card in detail["cards"]) == 3
            assert any(card["is_commander"] for card in detail["cards"])
            assert any(card["is_sideboard"] for card in detail["cards"])
            assert all(card["card"]["name"] == "Test Ring" for card in detail["cards"])
            assert browser.get("/api/guest/decks/9999").status_code == 404
        assert guest.cookies.get(guest_cookie_name()) != friend.cookies.get(guest_cookie_name())
    assert client.get("/api/auth/status").json()["user"]["role"] == "admin"


def test_guest_api_includes_owned_images_and_exact_deck_allocation_printings(client):
    headers = admin_login(client)
    deck_id = seed_deck()
    with SessionLocal() as db:
        original = db.get(CardPrinting, "printing-one")
        original.image_uri_normal = "https://images.example/original.jpg"
        alternate = CardPrinting(
            scryfall_id="printing-two", oracle_id=original.oracle_id,
            image_uri_normal="https://images.example/alternate.jpg", set_code="sld", collector_number="123",
        )
        db.add(alternate)
        db.flush()
        db.add(InventoryLine(scryfall_id=alternate.scryfall_id, quantity=1, foil=True))
        card = db.query(DeckCard).filter(DeckCard.deck_id == deck_id, DeckCard.is_commander.is_(True)).one()
        db.add(DeckCardAllocation(
            deck_card_id=card.id, quantity=1, status="grabbed", scryfall_id=alternate.scryfall_id, foil=True,
        ))
        db.commit()
    token = generate(client, headers)
    with TestClient(app) as guest:
        assert guest.post("/api/auth/guest", json={"token": token}).status_code == 200
        owned = guest.get("/api/guest/collection").json()[0]["printings"]
        assert {printing["image_uri_normal"] for printing in owned} == {
            "https://images.example/original.jpg", "https://images.example/alternate.jpg",
        }
        detail = guest.get(f"/api/guest/decks/{deck_id}").json()
        commander = next(card for card in detail["cards"] if card["is_commander"])
        allocation = commander["allocations"][0]
        assert commander["card"]["image_uri_normal"] == "https://images.example/original.jpg"
        assert allocation["printing"]["image_uri_normal"] == "https://images.example/alternate.jpg"
        assert allocation["printing"]["set_code"] == "sld"
        assert allocation["foil"] is True


def test_guests_cannot_call_any_administrator_route_or_write(client):
    headers = admin_login(client)
    token = generate(client, headers)
    with TestClient(app) as guest:
        assert guest.post("/api/auth/guest", json={"token": token}).status_code == 200
        csrf = {"X-CSRF-Token": guest.get("/api/auth/status").json()["csrf_token"]}
        public = {"/api/auth/status", "/api/auth/login", "/api/auth/guest", "/api/auth/logout", "/api/health"}
        for route in app.routes:
            path = route.path
            if not path.startswith("/api/") or path.startswith("/api/guest/") or path in public:
                continue
            if path == "/api/tags" and route.methods == {"GET"}:
                continue
            if path == "/api/cards/{oracle_id}/tags/{tag_id}":
                continue
            if path == "/api/card-tags/bulk-remove":
                continue
            path = re.sub(r"\{[^}]+\}", "1", path)
            for method in route.methods:
                response = guest.request(method, path, headers=csrf)
                assert response.status_code == 403, (method, path, response.text)
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD"):
            for path in ("/api/guest/collection", "/api/guest/decks", "/api/guest/decks/1"):
                assert guest.request(method, path, headers=csrf).status_code == 403
        assert guest.get("/api/guest/decks/1/export").status_code == 403
        assert guest.get("/api/guest/anything-new").status_code == 403


def test_guests_can_assign_existing_tags_but_cannot_manage_definitions(client):
    headers = admin_login(client)
    seed_deck()
    created = client.post(
        "/api/tags", json={"name": "Trade", "color": "amber"}, headers=headers,
    )
    assert created.status_code == 201
    tag = created.json()
    token = generate(client, headers)

    with TestClient(app) as guest:
        assert guest.post("/api/auth/guest", json={"token": token}).status_code == 200
        csrf = {"X-CSRF-Token": guest.get("/api/auth/status").json()["csrf_token"]}
        assert guest.get("/api/tags").json() == [tag]
        assert guest.post(f"/api/cards/oracle-one/tags/{tag['id']}").status_code == 403
        assigned = guest.post(f"/api/cards/oracle-one/tags/{tag['id']}", headers=csrf)
        assert assigned.status_code == 200
        assert guest.get("/api/guest/collection").json()[0]["tags"] == [tag]
        assert guest.post("/api/tags", json={"name": "Nope", "color": "red"}, headers=csrf).status_code == 403
        assert guest.delete(f"/api/tags/{tag['id']}", headers=csrf).status_code == 403
        assert guest.post("/api/card-tags/bulk-remove", json={
            "oracle_ids": ["oracle-one"], "tag_ids": [tag["id"]],
        }).status_code == 403
        bulk = guest.post("/api/card-tags/bulk-remove", json={
            "oracle_ids": ["oracle-one"], "tag_ids": [tag["id"]],
        }, headers=csrf)
        assert bulk.status_code == 403
        assert guest.get("/api/guest/collection").json()[0]["tags"] == [tag]


def test_rotation_and_disable_revoke_old_links_and_all_sessions(client):
    headers = admin_login(client)
    original = generate(client, headers)
    with TestClient(app) as guest, TestClient(app) as friend:
        for browser in (guest, friend):
            assert browser.post("/api/auth/guest", json={"token": original}).status_code == 200
        replacement = generate(client, headers)
        assert replacement != original
        for browser in (guest, friend):
            assert browser.get("/api/guest/decks").status_code == 401
            assert browser.get("/api/auth/status").json()["authenticated"] is False
            assert browser.post("/api/auth/guest", json={"token": original}).status_code == 401
            assert browser.post("/api/auth/guest", json={"token": replacement}).status_code == 200
        assert client.delete("/api/auth/guest-link", headers=headers).status_code == 200
        assert client.get("/api/auth/guest-link").json()["enabled"] is False
        for browser in (guest, friend):
            assert browser.get("/api/guest/collection").status_code == 401
            assert browser.post("/api/auth/guest", json={"token": replacement}).status_code == 401
        assert generate(client, headers) not in (original, replacement)


def test_unknown_expired_and_logged_out_guests_have_no_access(client):
    headers = admin_login(client)
    token = generate(client, headers)
    with TestClient(app) as guest:
        assert guest.get("/api/guest/decks").status_code == 401
        assert guest.post("/api/auth/guest", json={"token": "x" * 43}).status_code == 401
        assert guest.post("/api/auth/guest", json={"token": token}).status_code == 200
        csrf = guest.get("/api/auth/status").json()["csrf_token"]
        assert guest.post("/api/auth/logout").status_code == 403
        assert guest.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert guest.get("/api/guest/decks").status_code == 401
        assert not guest.cookies.get(guest_cookie_name())
        assert guest.post("/api/auth/guest", json={"token": token}).status_code == 200
        with SessionLocal() as db:
            db.query(GuestSession).update({"expires_at": utcnow() - timedelta(seconds=1)})
            db.commit()
        assert guest.get("/api/guest/decks").status_code == 401


@pytest.mark.parametrize("mode", ["disabled", "api_key", "external"])
def test_guest_management_requires_native_administrator_even_in_other_modes(client, mode):
    settings.auth_mode = mode
    settings.app_api_key = "test-key"
    settings.external_auth_enabled = True
    headers = {"X-Spellbinder-Key": "test-key"}
    for method in ("GET", "POST", "DELETE"):
        assert client.request(method, "/api/auth/guest-link", headers=headers).status_code == 403
    assert client.post("/api/auth/guest", json={"token": "x" * 43}).status_code == 404


def test_admin_csrf_and_guest_secure_cookie_and_invalid_link_throttle(client):
    headers = admin_login(client)
    assert client.post("/api/auth/guest-link").status_code == 403
    token = generate(client, headers)
    assert client.delete("/api/auth/guest-link").status_code == 403
    settings.session_cookie_secure = True
    with TestClient(app, base_url="https://testserver") as guest:
        result = guest.post("/api/auth/guest", json={"token": token})
        assert "__Host-spellbinder_guest=" in result.headers["set-cookie"]
        assert "Secure" in result.headers["set-cookie"]
        assert guest.get("/api/guest/decks").status_code == 200
        for _ in range(10):
            assert guest.post("/api/auth/guest", json={"token": "x" * 43}).status_code == 401
        assert guest.post("/api/auth/guest", json={"token": "x" * 43}).status_code == 429


@pytest.mark.parametrize("selection", ["flag", "oracle", "alternate_printing"])
def test_guest_commander_is_identified_from_flags_or_legacy_deck_settings(client, selection):
    headers = admin_login(client)
    deck_id = seed_deck()
    with SessionLocal() as db:
        deck = db.get(Deck, deck_id)
        original = db.query(DeckCard).filter(DeckCard.deck_id == deck_id, DeckCard.is_commander.is_(True)).one()
        original.is_commander = selection == "flag"
        if selection == "flag":
            deck.commander_oracle_id = None
        elif selection == "alternate_printing":
            alternate = CardPrinting(scryfall_id="commander-alternate", oracle_id=original.oracle_id)
            db.add(alternate)
            db.flush()
            deck.commander_oracle_id = None
            deck.commander_scryfall_id = alternate.scryfall_id
        db.commit()
        original_id = original.id
    token = generate(client, headers)
    with TestClient(app) as guest:
        guest.post("/api/auth/guest", json={"token": token})
        response = guest.get(f"/api/guest/decks/{deck_id}")
        assert response.status_code == 200
        detail = response.json()
        assert detail["commander_name"] == "Test Ring"
        commanders = [card for card in detail["cards"] if card["is_commander"]]
        assert len(commanders) == 1
        assert commanders[0]["id"] == original_id
        assert commanders[0]["is_sideboard"] is False
    with SessionLocal() as db:
        # Guest reads only fix the response, never the owner's saved deck.
        assert db.get(DeckCard, original_id).is_commander == (selection == "flag")


def test_revealing_link_preserves_token_and_existing_guest_sessions(client):
    headers = admin_login(client)
    token = generate(client, headers)
    with TestClient(app) as guest:
        guest.post("/api/auth/guest", json={"token": token})
        cookie = guest.cookies.get(guest_cookie_name())
        before = client.get("/api/auth/guest-link").json()
        assert before["recoverable"] is True
        assert "token" not in before
        for _ in range(2):
            reveal = client.get("/api/auth/guest-link/reveal")
            assert reveal.status_code == 200
            assert reveal.json() == {"token": token}
            assert reveal.headers["cache-control"] == "private, no-store"
            assert client.get("/api/auth/guest-link").json() == before
            assert guest.get("/api/guest/decks").status_code == 200
            assert guest.cookies.get(guest_cookie_name()) == cookie
        assert guest.get("/api/auth/guest-link/reveal").status_code == 403
        assert token not in guest.get("/api/auth/status").text
        with SessionLocal() as db:
            assert db.get(GuestAccess, 1).invite_token == token
            assert db.query(GuestSession).count() == 1
        replacement = generate(client, headers)
        assert client.get("/api/auth/guest-link/reveal").json() == {"token": replacement}
        assert guest.get("/api/guest/decks").status_code == 401
        client.delete("/api/auth/guest-link", headers=headers)
        assert client.get("/api/auth/guest-link/reveal").status_code == 404
        with SessionLocal() as db:
            assert db.get(GuestAccess, 1).invite_token is None


def test_legacy_link_recovers_on_valid_redemption_without_revoking_sessions(client):
    headers = admin_login(client)
    assert client.get("/api/auth/guest-link/reveal").status_code == 404
    token = generate(client, headers)
    with TestClient(app) as guest:
        guest.post("/api/auth/guest", json={"token": token})
        cookie = guest.cookies.get(guest_cookie_name())
        with SessionLocal() as db:
            db.get(GuestAccess, 1).invite_token = None
            db.commit()
        assert client.get("/api/auth/guest-link").json()["recoverable"] is False
        assert client.get("/api/auth/guest-link/reveal").status_code == 409
        assert guest.get("/api/guest/decks").status_code == 200
        assert guest.post("/api/auth/guest", json={"token": "x" * 43}).status_code == 401
        assert client.get("/api/auth/guest-link/reveal").status_code == 409
        with TestClient(app) as friend:
            assert friend.post("/api/auth/guest", json={"token": token}).status_code == 200
        assert client.get("/api/auth/guest-link/reveal").json() == {"token": token}
        assert guest.get("/api/guest/decks").status_code == 200
        assert guest.cookies.get(guest_cookie_name()) == cookie
        with SessionLocal() as db:
            assert db.get(GuestAccess, 1).invite_hash == token_hash(token)
            assert db.query(GuestSession).count() == 2


def test_guest_link_migration_preserves_old_link_and_sessions(tmp_path):
    from sqlalchemy import create_engine, text
    from app.database import Base, run_migrations
    migration_engine = create_engine(f"sqlite:///{tmp_path / 'legacy-guest.db'}")
    try:
        Base.metadata.create_all(migration_engine)
        with migration_engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE guest_access DROP COLUMN invite_token")
            connection.execute(text("INSERT INTO guest_access (id, invite_hash, enabled, created_at) VALUES (1, 'old-invite-hash', 1, CURRENT_TIMESTAMP)"))
            connection.execute(text("INSERT INTO guest_sessions (token_hash, invite_hash, csrf_token, expires_at) VALUES ('old-session', 'old-invite-hash', 'csrf', '2099-01-01')"))
        run_migrations(migration_engine)
        run_migrations(migration_engine)
        with migration_engine.connect() as connection:
            access = connection.execute(text("SELECT invite_hash, invite_token, enabled FROM guest_access")).one()
            assert tuple(access) == ("old-invite-hash", None, 1)
            assert connection.execute(text("SELECT token_hash FROM guest_sessions")).scalar_one() == "old-session"
            assert connection.execute(text("SELECT COUNT(*) FROM schema_versions WHERE version = 14")).scalar_one() == 1
    finally:
        migration_engine.dispose()
