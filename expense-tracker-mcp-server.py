from fastmcp import FastMCP
import os
import json
from dotenv import load_dotenv
from contextlib import contextmanager
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

load_dotenv()

CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), "categories.json")

_conn_str = os.environ.get("DATABASE_URL")

connection_pool = pool.SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    dsn=_conn_str
)

mcp = FastMCP("ExpenseTracker")


@contextmanager
def get_cursor(commit=False):
    """Borrow a connection from the pool, yield a dict-cursor, then return it."""
    conn = connection_pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
            if commit:
                conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        connection_pool.putconn(conn)


def init_db():
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                amount NUMERIC(12, 2) NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT ''
            )
            """
        )
        # Helpful for date-range queries and category summaries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category)")


init_db()


@mcp.tool()
def add_expense(date, amount, category, subcategory="", note=""):
    """Add a new expense entry to the database."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO expenses (date, amount, category, subcategory, note)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (date, amount, category, subcategory, note),
        )
        new_id = cur.fetchone()["id"]
        return {"status": "ok", "id": new_id}


@mcp.tool()
def list_expenses(start_date, end_date):
    """List expense entries within an inclusive date range."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, date, amount, category, subcategory, note
            FROM expenses
            WHERE date BETWEEN %s AND %s
            ORDER BY id ASC
            """,
            (start_date, end_date),
        )
        rows = cur.fetchall()
        # Convert Decimal/date objects to JSON-friendly types
        return [
            {
                **row,
                "date": row["date"].isoformat(),
                "amount": float(row["amount"]),
            }
            for row in rows
        ]


@mcp.tool()
def summarize(start_date, end_date, category=None):
    """Summarize expenses by category within an inclusive date range."""
    with get_cursor() as cur:
        query = """
            SELECT category, SUM(amount) AS total_amount
            FROM expenses
            WHERE date BETWEEN %s AND %s
        """
        params = [start_date, end_date]
        if category:
            query += " AND category = %s"
            params.append(category)
        query += " GROUP BY category ORDER BY category ASC"
        cur.execute(query, params)
        rows = cur.fetchall()
        return [
            {"category": row["category"], "total_amount": float(row["total_amount"])}
            for row in rows
        ]


@mcp.resource("expense://categories", mime_type="application/json")
def categories():
    # Read fresh each time so you can edit the file without restarting
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    mcp.run()