import os
import json
import sqlite3
from datetime import datetime
from typing import Optional

from fastmcp import FastMCP

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses.db")
CATEGORIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "categories.json")

mcp = FastMCP("Expense-Tracker")


# ── helpers ───────────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def validate_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except ValueError:
        raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD.")


def validate_month(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m")
        return value
    except ValueError:
        raise ValueError(f"Invalid month '{value}'. Use YYYY-MM.")


def validate_amount(value: float) -> float:
    if value <= 0:
        raise ValueError(f"Amount must be positive, got {value}.")
    return value


def rows_to_dicts(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


# ── schema init ───────────────────────────────────────────────────────────────

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT    NOT NULL,
                amount       REAL    NOT NULL CHECK(amount > 0),
                category     TEXT    NOT NULL,
                subcategory  TEXT    DEFAULT '',
                note         TEXT    DEFAULT '',
                is_recurring INTEGER DEFAULT 0,
                created_at   TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                category   TEXT    NOT NULL,
                month      TEXT    NOT NULL,
                amount     REAL    NOT NULL CHECK(amount > 0),
                created_at TEXT    DEFAULT (datetime('now')),
                UNIQUE(category, month)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                name   TEXT NOT NULL UNIQUE,
                parent TEXT DEFAULT NULL
            )
        """)
        # One-time migration from categories.json → DB
        count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if count == 0 and os.path.exists(CATEGORIES_PATH):
            with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for parent, children in data.items():
                conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (parent,))
                for child in children:
                    conn.execute(
                        "INSERT OR IGNORE INTO categories (name, parent) VALUES (?, ?)",
                        (child, parent),
                    )


init_db()


# ── expense CRUD ──────────────────────────────────────────────────────────────

@mcp.tool()
def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = "",
    is_recurring: bool = False,
) -> dict:
    """Add a new expense. date must be YYYY-MM-DD, amount must be positive."""
    validate_date(date)
    validate_amount(amount)
    if not category.strip():
        raise ValueError("category cannot be empty.")

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO expenses (date, amount, category, subcategory, note, is_recurring)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (date, amount, category.strip(), subcategory.strip(), note.strip(), int(is_recurring)),
        )
        return {
            "id": cur.lastrowid,
            "status": "added",
            "date": date,
            "amount": amount,
            "category": category,
        }


@mcp.tool()
def update_expense(
    id: int,
    date: Optional[str] = None,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    note: Optional[str] = None,
    is_recurring: Optional[bool] = None,
) -> dict:
    """Update an existing expense by ID. Only the provided fields are changed."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (id,)).fetchone()
        if not row:
            raise ValueError(f"No expense with id={id}.")

        new_date       = validate_date(date) if date else row["date"]
        new_amount     = validate_amount(amount) if amount is not None else row["amount"]
        new_category   = category.strip() if category else row["category"]
        new_sub        = subcategory.strip() if subcategory is not None else row["subcategory"]
        new_note       = note.strip() if note is not None else row["note"]
        new_recurring  = int(is_recurring) if is_recurring is not None else row["is_recurring"]

        conn.execute(
            """UPDATE expenses
               SET date=?, amount=?, category=?, subcategory=?, note=?, is_recurring=?
               WHERE id=?""",
            (new_date, new_amount, new_category, new_sub, new_note, new_recurring, id),
        )
        return {"id": id, "status": "updated"}


@mcp.tool()
def delete_expense(id: int) -> dict:
    """Delete an expense by ID."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM expenses WHERE id = ?", (id,))
        if cur.rowcount == 0:
            raise ValueError(f"No expense with id={id}.")
        return {"id": id, "status": "deleted"}


@mcp.tool()
def list_expenses(
    start_date: str,
    end_date: str,
    category: Optional[str] = None,
    recurring_only: bool = False,
) -> list[dict]:
    """List expenses in a date range, optionally filtered by category or recurring flag."""
    validate_date(start_date)
    validate_date(end_date)

    query = "SELECT * FROM expenses WHERE date BETWEEN ? AND ?"
    params: list = [start_date, end_date]

    if category:
        query += " AND category = ?"
        params.append(category)
    if recurring_only:
        query += " AND is_recurring = 1"

    query += " ORDER BY date DESC, id DESC"

    with get_conn() as conn:
        return rows_to_dicts(conn.execute(query, params))


@mcp.tool()
def summarize(start_date: str, end_date: str, category: Optional[str] = None) -> list[dict]:
    """Summarize total spending per category within a date range."""
    validate_date(start_date)
    validate_date(end_date)

    query = """
        SELECT category,
               SUM(amount)  AS total_amount,
               COUNT(*)     AS num_transactions
        FROM expenses
        WHERE date BETWEEN ? AND ?
    """
    params: list = [start_date, end_date]
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " GROUP BY category ORDER BY total_amount DESC"

    with get_conn() as conn:
        return rows_to_dicts(conn.execute(query, params))


# ── budget tools ──────────────────────────────────────────────────────────────

@mcp.tool()
def set_budget(category: str, month: str, amount: float) -> dict:
    """Set or update a monthly budget for a category. month must be YYYY-MM."""
    validate_month(month)
    validate_amount(amount)
    if not category.strip():
        raise ValueError("category cannot be empty.")

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO budgets (category, month, amount) VALUES (?, ?, ?)
               ON CONFLICT(category, month) DO UPDATE SET amount = excluded.amount""",
            (category.strip(), month, amount),
        )
        return {"status": "set", "category": category, "month": month, "budget": amount}


@mcp.tool()
def delete_budget(category: str, month: str) -> dict:
    """Remove a budget entry for a category and month (YYYY-MM)."""
    validate_month(month)
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM budgets WHERE category = ? AND month = ?", (category, month)
        )
        if cur.rowcount == 0:
            raise ValueError(f"No budget for category='{category}', month='{month}'.")
        return {"status": "deleted", "category": category, "month": month}


@mcp.tool()
def list_budgets(month: str) -> list[dict]:
    """List all budgets set for a given month (YYYY-MM)."""
    validate_month(month)
    with get_conn() as conn:
        return rows_to_dicts(
            conn.execute("SELECT * FROM budgets WHERE month = ? ORDER BY category", (month,))
        )


@mcp.tool()
def budget_status(month: str) -> list[dict]:
    """Compare actual spending vs budget for every budgeted category in a month."""
    validate_month(month)
    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute(
            """
            SELECT
                b.category,
                b.amount                                    AS budget,
                COALESCE(SUM(e.amount), 0)                  AS spent,
                b.amount - COALESCE(SUM(e.amount), 0)       AS remaining,
                ROUND(COALESCE(SUM(e.amount), 0) * 100.0
                      / b.amount, 1)                        AS pct_used
            FROM budgets b
            LEFT JOIN expenses e
                ON  e.category = b.category
                AND strftime('%Y-%m', e.date) = b.month
            WHERE b.month = ?
            GROUP BY b.category
            ORDER BY pct_used DESC
            """,
            (month,),
        ))
        for row in rows:
            row["status"] = "over_budget" if row["spent"] > row["budget"] else "ok"
        return rows


# ── analytics ─────────────────────────────────────────────────────────────────

@mcp.tool()
def monthly_trend(months: int = 6, category: Optional[str] = None) -> list[dict]:
    """Show month-by-month spending totals for the last N months (max 24)."""
    if not 1 <= months <= 24:
        raise ValueError("months must be between 1 and 24.")

    query = """
        SELECT strftime('%Y-%m', date) AS month,
               SUM(amount)             AS total,
               COUNT(*)                AS num_transactions
        FROM expenses
        WHERE date >= date('now', ? || ' months')
    """
    params: list = [f"-{months}"]
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " GROUP BY month ORDER BY month ASC"

    with get_conn() as conn:
        return rows_to_dicts(conn.execute(query, params))


@mcp.tool()
def top_categories(start_date: str, end_date: str, limit: int = 5) -> list[dict]:
    """Return the top spending categories in a date range."""
    validate_date(start_date)
    validate_date(end_date)
    if limit < 1:
        raise ValueError("limit must be at least 1.")

    with get_conn() as conn:
        return rows_to_dicts(conn.execute(
            """
            SELECT category,
                   SUM(amount)        AS total,
                   COUNT(*)           AS num_transactions,
                   ROUND(AVG(amount), 2) AS avg_transaction
            FROM expenses
            WHERE date BETWEEN ? AND ?
            GROUP BY category
            ORDER BY total DESC
            LIMIT ?
            """,
            (start_date, end_date, limit),
        ))


@mcp.tool()
def spending_insights(month: str) -> dict:
    """Full spending breakdown for a month: totals, per-category, budget status, daily average."""
    validate_month(month)
    with get_conn() as conn:
        total_row = conn.execute(
            """SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count
               FROM expenses WHERE strftime('%Y-%m', date) = ?""",
            (month,),
        ).fetchone()

        by_category = rows_to_dicts(conn.execute(
            """SELECT category, SUM(amount) AS total, COUNT(*) AS count
               FROM expenses WHERE strftime('%Y-%m', date) = ?
               GROUP BY category ORDER BY total DESC""",
            (month,),
        ))

        budget_rows = rows_to_dicts(conn.execute(
            """
            SELECT b.category,
                   b.amount                              AS budget,
                   COALESCE(SUM(e.amount), 0)            AS spent,
                   b.amount - COALESCE(SUM(e.amount), 0) AS remaining
            FROM budgets b
            LEFT JOIN expenses e
                ON  e.category = b.category
                AND strftime('%Y-%m', e.date) = b.month
            WHERE b.month = ?
            GROUP BY b.category
            """,
            (month,),
        ))

        active_days = conn.execute(
            "SELECT COUNT(DISTINCT date) AS d FROM expenses WHERE strftime('%Y-%m', date) = ?",
            (month,),
        ).fetchone()["d"]

    total = total_row["total"]
    return {
        "month": month,
        "total_spent": total,
        "total_transactions": total_row["count"],
        "daily_average": round(total / max(active_days, 1), 2),
        "by_category": by_category,
        "budget_status": budget_rows,
    }


# ── category management ───────────────────────────────────────────────────────

@mcp.tool()
def add_category(name: str, parent: Optional[str] = None) -> dict:
    """Add a new expense category, optionally nested under a parent category."""
    if not name.strip():
        raise ValueError("name cannot be empty.")
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO categories (name, parent) VALUES (?, ?)",
                (name.strip(), parent.strip() if parent else None),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"Category '{name}' already exists.")
        return {"status": "added", "name": name, "parent": parent}


@mcp.tool()
def list_categories() -> list[dict]:
    """List all expense categories with their parent (if any)."""
    with get_conn() as conn:
        return rows_to_dicts(conn.execute(
            "SELECT name, parent FROM categories ORDER BY parent, name"
        ))


@mcp.tool()
def delete_category(name: str) -> dict:
    """Delete a category by name."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM categories WHERE name = ?", (name,))
        if cur.rowcount == 0:
            raise ValueError(f"Category '{name}' not found.")
        return {"status": "deleted", "name": name}


# ── resource ──────────────────────────────────────────────────────────────────

@mcp.resource("expense://categories", mime_type="application/json")
def categories_resource() -> str:
    """All categories as JSON, grouped by parent."""
    with get_conn() as conn:
        rows = rows_to_dicts(conn.execute(
            "SELECT name, parent FROM categories ORDER BY parent, name"
        ))
    return json.dumps(rows, indent=2)


# ── prompts ───────────────────────────────────────────────────────────────────

@mcp.prompt()
def monthly_report(month: str) -> str:
    """Prompt: generate a full narrative monthly expense report."""
    return f"""
Use the expense tracker tools to generate a complete monthly report for {month}.

1. Call spending_insights(month="{month}") for the overview.
2. Call budget_status(month="{month}") to check budget adherence.
3. Call top_categories(start_date="{month}-01", end_date="{month}-31") for the top spenders.

Write a concise report covering:
- Total spending and transaction count
- Top 3 spending categories with amounts and % of total
- Budget status: which categories are over/under and by how much
- One actionable recommendation to reduce spending next month
""".strip()


@mcp.prompt()
def budget_health(month: str) -> str:
    """Prompt: assess budget health and flag at-risk categories for a month."""
    return f"""
Assess budget health for {month}.

1. Call budget_status(month="{month}").
2. Call spending_insights(month="{month}").

Provide:
- A traffic-light summary (green / amber / red) per category based on % of budget used
- Categories at risk (> 80 % used) with projected end-of-month overspend
- Suggestions for rebalancing if any category is already over budget
""".strip()


@mcp.prompt()
def spending_advice(month: str) -> str:
    """Prompt: get personalised spending advice based on the last 3 months of data."""
    return f"""
Analyse spending patterns over the 3 months leading up to {month} and give advice.

1. Call monthly_trend(months=3) for the trend.
2. Call spending_insights(month="{month}") for the current month.

Provide:
- Whether overall spending is trending up or down
- The category with the fastest-growing spend
- Two specific, actionable suggestions to cut expenses next month
""".strip()


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
