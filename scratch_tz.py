import psycopg2
import datetime
conn = psycopg2.connect("postgresql://lina:123@postgres-db:5432/lina")
cur = conn.cursor()
cur.execute("SET TIME ZONE 'Africa/Cairo'")
cur.execute('SELECT "timestamp" FROM entry_logs LIMIT 1')
val = cur.fetchone()[0]
print(repr(val), val.isoformat())
