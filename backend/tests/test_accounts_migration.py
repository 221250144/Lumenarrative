"""Exercise the actual migration over a pre-account database, not create_all."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_upgrade_preserves_legacy_projects_and_explicitly_assigns_owner(tmp_path):
    root = Path(__file__).resolve().parents[2]
    database = tmp_path / "legacy.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}",
           "DATA_DIR": str(tmp_path / "media"), "PYTHONPATH": str(root / "backend")}

    def run(*args, password=None):
        return subprocess.run([sys.executable, *args], cwd=root, env=env,
                              input=password, text=True, capture_output=True, check=True)

    run("-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "0001")
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("""INSERT INTO projects
            (id,created_at,title,intent,target_duration_s,style,input_mode,constraints_json,revision)
            VALUES ('legacy','2026-09-23','原项目','审看',60,'自然','vlog','{}',1)""")
        db.execute("""INSERT INTO jobs
            (id,created_at,project_id,type,status,stage,completed_units,total_units,retry_count,data)
            VALUES ('legacy-job','2026-09-23','legacy','analysis','succeeded','完成',1,1,0,'{}')""")
    run("-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT title,owner_id,deleted_at FROM projects").fetchone() == ("原项目", None, None)
        assert db.execute("SELECT project_id FROM jobs").fetchone() == ("legacy",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert any(row[2:5] == ("users", "owner_id", "id") for row in db.execute("PRAGMA foreign_key_list(projects)"))
    result = run("-m", "app.manage_users", "caozheng", "--password-stdin", "--claim-legacy", password="migration-test-password\n")
    assert "assigned 1 legacy projects" in result.stdout
    assert "migration-test-password" not in result.stdout + result.stderr
    run("-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head")
    with sqlite3.connect(database) as db:
        user_id = db.execute("SELECT id FROM users WHERE username='caozheng'").fetchone()[0]
        assert db.execute("SELECT owner_id FROM projects").fetchone() == (user_id,)
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
