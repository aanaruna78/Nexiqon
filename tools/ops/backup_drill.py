"""Back up the platform database and prove it restores, against the clock (G-03).

    uv run python -m tools.ops.backup_drill                 # local stack (docker compose)
    uv run python -m tools.ops.backup_drill --keep DIR      # also keep the dump in DIR

Steps:
1. ``pg_dump -Fc`` of the whole database (every service schema) inside the postgres container;
2. restore it into a scratch database ``nexiqon_drill``;
3. compare exact row counts, table by table, in every application schema;
4. drop the scratch database;
5. print a JSON report with each step's time.

It exits non-zero if any table differs. Run it before each release, and record the times in
docs/runbooks/backup-restore.md. In Kubernetes, run the same commands in the backup CronJob's
image (deploy/helm, ``backup.enabled``) or against the managed database's latest backup.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy/compose/docker-compose.yml")]
DB, DRILL, USER = "nexiqon", "nexiqon_drill", "nexiqon"
# Every service's schema (deploy/groups.yaml), with dashes as underscores.
SKIP_SCHEMAS = {"pg_catalog", "information_schema", "public", "pg_toast"}


def psql(sql: str, db: str = DB) -> str:
    out = subprocess.run(
        [*COMPOSE, "exec", "-T", "postgres", "psql", "-U", USER, "-d", db, "-tAc", sql],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def counts(db: str) -> dict[str, int]:
    tables = psql(
        "SELECT table_schema || '.' || table_name FROM information_schema.tables "
        "WHERE table_type = 'BASE TABLE' AND table_schema NOT IN "
        f"({', '.join(repr(s) for s in sorted(SKIP_SCHEMAS))}) "
        "AND table_schema NOT LIKE 'pg_%' ORDER BY 1",
        db,
    ).splitlines()
    if not tables:
        return {}
    # Owner role: RLS does not apply to the table owner, so counts are exact across tenants.
    union = " UNION ALL ".join(f"SELECT '{t}', count(*) FROM {t}" for t in tables)
    rows = psql(union, db).splitlines()
    return {name: int(n) for name, n in (r.split("|") for r in rows)}


def timed(label: str, report: dict[str, float], fn: object, *args: object) -> object:
    started = time.monotonic()
    result = fn(*args)  # type: ignore[operator]
    report[label] = round(time.monotonic() - started, 2)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=Path, help="copy the dump into this directory")
    args = parser.parse_args()
    seconds: dict[str, float] = {}

    def dump() -> int:
        subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-U",
                USER,
                "-Fc",
                "-f",
                "/tmp/drill.dump",
                DB,
            ],
            check=True,
        )
        return int(psql("SELECT pg_database_size(current_database())"))

    def restore() -> None:
        psql(f"DROP DATABASE IF EXISTS {DRILL}")
        psql(f"CREATE DATABASE {DRILL}")
        subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "-U",
                USER,
                "-d",
                DRILL,
                "--no-owner",
                "--exit-on-error",
                "/tmp/drill.dump",
            ],
            check=True,
        )

    before = counts(DB)  # taken first, so a busy stack can only add rows the dump may also have
    size = timed("dump", seconds, dump)
    timed("restore", seconds, restore)
    after = timed("verify", seconds, counts, DRILL)
    assert isinstance(after, dict)
    missing = {t: (n, after.get(t)) for t, n in before.items() if after.get(t, -1) < n}
    if args.keep:
        args.keep.mkdir(parents=True, exist_ok=True)
        target = args.keep / f"nexiqon-{time.strftime('%Y%m%d-%H%M%S')}.dump"
        with target.open("wb") as fh:
            subprocess.run(
                [*COMPOSE, "exec", "-T", "postgres", "cat", "/tmp/drill.dump"],
                check=True,
                stdout=fh,
            )
    psql(f"DROP DATABASE IF EXISTS {DRILL}")
    subprocess.run([*COMPOSE, "exec", "-T", "postgres", "rm", "-f", "/tmp/drill.dump"], check=True)
    report = {
        "database_bytes": size,
        "tables": len(before),
        "rows": sum(before.values()),
        "seconds": seconds,
        "total_seconds": round(sum(seconds.values()), 2),
        "ok": not missing,
        "missing_rows": missing,
    }
    print(json.dumps(report, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    if shutil.which("docker") is None:
        sys.exit("docker is required (the drill runs inside the local postgres container)")
    sys.exit(main())
