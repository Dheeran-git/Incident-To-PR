from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

database, key = Path(sys.argv[1]), sys.argv[2]
if not database.is_file():
    raise SystemExit(0)
try:
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    if row:
        print(row[0])
except sqlite3.Error:
    pass
