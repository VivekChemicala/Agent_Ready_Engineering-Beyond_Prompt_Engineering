"""Postgres connector: reads table schemas from information_schema."""

from __future__ import annotations

COLUMNS_SQL = """
SELECT c.column_name, c.data_type, c.is_nullable,
       col_description(format('%s.%s', c.table_schema, c.table_name)::regclass,
                       c.ordinal_position) AS column_comment
FROM information_schema.columns c
WHERE c.table_schema = %(schema)s AND c.table_name = %(table)s
ORDER BY c.ordinal_position
"""


def discover_columns(conn, schema: str, table: str) -> list[dict]:
    rows = conn.execute(COLUMNS_SQL, {"schema": schema, "table": table}).fetchall()
    # column_comment holds source-system tags such as "tags: pii,email";
    # it is not mapped into the event today.
    return [{"name": r[0], "type": r[1], "nullable": r[2] == "YES"} for r in rows]
