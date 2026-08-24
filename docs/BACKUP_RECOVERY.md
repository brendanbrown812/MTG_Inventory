# Spellbinder database backup and recovery

Spellbinder stores all collection and deck data in SQLite. Card images and Scryfall data can be fetched again, but inventory and deck changes cannot, so create a backup before migrations, upgrades, or bulk edits.

The backup command uses SQLite's online backup API. It creates a consistent snapshot even while the application is running, verifies the snapshot with `PRAGMA integrity_check`, and refuses to overwrite an existing backup unless explicitly requested.

## Local Windows installation

From the project root:

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force backups | Out-Null
backend\.venv\Scripts\python.exe backend/app/backup.py backup backend/mtg_inventory.db "backups/spellbinder-$stamp.db"
```

If the project environment does not exist, use `py -3` or `python` after installing the backend requirements.

Verify any backup independently:

```powershell
backend\.venv\Scripts\python.exe backend/app/backup.py verify backups/spellbinder-YYYYMMDD-HHMMSS.db
```

## Docker installation

The Compose configuration mounts the host `backups` directory at `/backups` in the backend container.

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force backups | Out-Null
docker compose exec backend python -m app.backup backup /data/mtg_inventory.db "/backups/spellbinder-$stamp.db"
```

The resulting file is stored under `backups` on the host, outside the named database volume.

## Recovery

Recovery replaces the active database. Stop the backend first, preserve the current database with one final backup when possible, and verify the selected recovery file before restoring it.

### Local recovery

```powershell
backend\.venv\Scripts\python.exe backend/app/backup.py verify backups/spellbinder-YYYYMMDD-HHMMSS.db
# Stop the Spellbinder API window before the next command.
backend\.venv\Scripts\python.exe backend/app/backup.py restore backups/spellbinder-YYYYMMDD-HHMMSS.db backend/mtg_inventory.db --yes
```

### Docker recovery

```powershell
docker compose stop backend
docker compose run --rm backend python -m app.backup verify /backups/spellbinder-YYYYMMDD-HHMMSS.db
docker compose run --rm backend python -m app.backup restore /backups/spellbinder-YYYYMMDD-HHMMSS.db /data/mtg_inventory.db --yes
docker compose up -d backend
docker compose ps
```

After recovery, open the Collection and Decks pages and confirm expected totals and deck names before making new changes.

## Retention

Keep at least three known-good backups and periodically copy one outside this computer or Docker host. The `backups` directory is intentionally ignored by Git because it contains personal collection data.
