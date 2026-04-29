"""
analyze_db.py — Deep schema analysis of idre_stage database.
Connects to AWS RDS MySQL, inspects all tables, columns, FK relationships,
and sample values. Outputs schema_catalog.json for use in the chatbot.
"""
import json
import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    ssl_ca = os.getenv('DB_SSL_CA', './global-bundle.pem')
    if not os.path.exists(ssl_ca):
        ssl_ca = None
    cfg = {
        'host': os.getenv('DB_HOST'),
        'port': int(os.getenv('DB_PORT', 3306)),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'connection_timeout': 20,
    }
    if ssl_ca:
        cfg['ssl_ca'] = ssl_ca
    return mysql.connector.connect(**cfg)

def fetch_all(cur, query, params=None):
    cur.execute(query, params or ())
    return cur.fetchall()

def analyze(conn):
    cur = conn.cursor()
    db = os.getenv('DB_NAME')

    # ── 1. Table list with row counts and sizes ──────────────────────────────
    cur.execute("""
        SELECT table_name,
               table_rows,
               table_comment,
               ROUND(data_length/1024/1024, 2)  AS data_mb,
               ROUND(index_length/1024/1024, 2) AS index_mb,
               create_time,
               update_time
        FROM information_schema.tables
        WHERE table_schema = %s
        ORDER BY table_name
    """, (db,))
    tables = cur.fetchall()
    print(f"\nFound {len(tables)} tables in `{db}`\n")

    catalog = {}

    for (tname, trows, tcomment, data_mb, index_mb, create_time, update_time) in tables:
        print(f"  Analysing: {tname} (~{trows or 0:,} rows) ...", end='', flush=True)

        # ── 2. Column details ──────────────────────────────────────────────
        cur.execute("""
            SELECT column_name, column_type, is_nullable,
                   column_default, extra, column_comment, column_key
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (db, tname))
        cols = cur.fetchall()

        columns = []
        for (cname, ctype, nullable, default, extra, ccomment, ckey) in cols:
            columns.append({
                "name": cname,
                "type": ctype,
                "nullable": nullable == 'YES',
                "default": default,
                "extra": extra,
                "comment": ccomment,
                "key": ckey  # PRI / MUL / UNI / ""
            })

        # ── 3. Sample distinct values for small-cardinality columns ──────
        sample_values = {}
        for col in columns:
            cname = col['name']
            ctype_lower = col['type'].lower()
            # Only sample enum-like, status-like, or short varchar columns
            if ('varchar' in ctype_lower or 'enum' in ctype_lower or 'char' in ctype_lower):
                try:
                    cur.execute(f"SELECT DISTINCT `{cname}` FROM `{tname}` LIMIT 20")
                    vals = [r[0] for r in cur.fetchall() if r[0] is not None]
                    if vals and len(vals) <= 20:
                        sample_values[cname] = vals
                except Exception:
                    pass

        # ── 4. Foreign keys ───────────────────────────────────────────────
        cur.execute("""
            SELECT kcu.column_name,
                   kcu.referenced_table_name,
                   kcu.referenced_column_name
            FROM information_schema.key_column_usage kcu
            JOIN information_schema.referential_constraints rc
              ON rc.constraint_name = kcu.constraint_name
             AND rc.constraint_schema = kcu.table_schema
            WHERE kcu.table_schema = %s AND kcu.table_name = %s
        """, (db, tname))
        fks_raw = cur.fetchall()
        foreign_keys = [
            {"column": fk[0], "references_table": fk[1], "references_column": fk[2]}
            for fk in fks_raw
        ]

        # ── 5. Indexes ─────────────────────────────────────────────────────
        cur.execute(f"SHOW INDEX FROM `{tname}`")
        idx_rows = cur.fetchall()
        indexes = {}
        for row in idx_rows:
            idx_name = row[2]
            col_name = row[4]
            unique = row[1] == 0
            if idx_name not in indexes:
                indexes[idx_name] = {"columns": [], "unique": unique}
            indexes[idx_name]["columns"].append(col_name)

        catalog[tname] = {
            "row_count_approx": trows or 0,
            "comment": tcomment or "",
            "data_size_mb": float(data_mb or 0),
            "index_size_mb": float(index_mb or 0),
            "last_updated": str(update_time) if update_time else None,
            "columns": columns,
            "sample_values": sample_values,
            "foreign_keys": foreign_keys,
            "indexes": list(indexes.values()),
        }
        print(" done")

    cur.close()
    return catalog

def build_join_graph(catalog):
    """Build a flat join graph from FK relationships for the Schema Mapper agent."""
    join_graph = []
    for tname, tmeta in catalog.items():
        for fk in tmeta['foreign_keys']:
            join_graph.append({
                "from_table": tname,
                "from_column": fk['column'],
                "to_table": fk['references_table'],
                "to_column": fk['references_column'],
                "join_type": "INNER"
            })
    return join_graph

def print_summary(catalog):
    print("\n" + "="*70)
    print(f"{'TABLE':<40} {'ROWS':>10} {'DATA MB':>10} {'COLS':>6}")
    print("="*70)
    total_rows = 0
    for tname, m in sorted(catalog.items(), key=lambda x: -x[1]['row_count_approx']):
        print(f"{tname:<40} {m['row_count_approx']:>10,} {m['data_size_mb']:>10.1f} {len(m['columns']):>6}")
        total_rows += m['row_count_approx']
    print("="*70)
    print(f"{'TOTAL':>40} {total_rows:>10,}")

if __name__ == "__main__":
    print("Connecting to AWS RDS...")
    conn = get_connection()
    print("Connected.")

    catalog = analyze(conn)
    conn.close()

    join_graph = build_join_graph(catalog)

    # Save schema catalog
    out = {
        "database": os.getenv('DB_NAME'),
        "host": os.getenv('DB_HOST'),
        "analyzed_at": __import__('datetime').datetime.utcnow().isoformat(),
        "table_count": len(catalog),
        "tables": catalog,
        "join_graph": join_graph,
    }

    with open("schema_catalog.json", "w") as f:
        json.dump(out, f, indent=2, default=str)

    print(f"\nDONE: schema_catalog.json written ({len(catalog)} tables, {len(join_graph)} FK relationships)")
    print_summary(catalog)
