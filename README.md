# Expense Tracker MCP Server

A remote MCP server for tracking personal expenses with budget management and analytics. Deployed on fastmcp.cloud with OAuth authentication.

## Connect to the Server

Your server is deployed at:
```
https://nikhilmankali-expense-server.fastmcp.app/mcp
```

### Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/settings.json` on Mac, `%APPDATA%\Claude\settings.json` on Windows):

```json
{
  "mcpServers": {
    "expense-tracker": {
      "url": "https://nikhilmankali-expense-server.fastmcp.app/mcp"
    }
  }
}
```

Restart Claude Desktop. The expense tracker tools will appear in the MCP server list.

### Other MCP Clients

Any MCP-compatible client (Claude Desktop, Cursor, Windsurf, etc.) can connect using the same URL.

## Features

### Expense Management
- **add_expense** — Add a new expense (date, amount, category, note)
- **update_expense** — Modify an expense by ID
- **delete_expense** — Remove an expense by ID
- **list_expenses** — List expenses filtered by date range, category
- **summarize** — Total spending per category

### Budget Management
- **set_budget** — Set monthly budget for a category
- **delete_budget** — Remove a budget
- **list_budgets** — View budgets for a month
- **budget_status** — Compare spending vs budget

### Analytics
- **monthly_trend** — Month-by-month totals (last N months)
- **top_categories** — Top spending categories
- **spending_insights** — Full monthly breakdown with daily average

### Category Management
- **add_category**, **list_categories**, **delete_category**

### Resources & Prompts
- **expense://categories** — JSON resource
- **monthly_report** — Generate narrative monthly report
- **budget_health** — Budget health assessment
- **spending_advice** — Personalized spending advice

## Data Isolation

Each user gets their own isolated data:
- Expenses and budgets are scoped to the authenticated user
- Categories are shared across all users

The server uses the OAuth token's `sub` claim to identify users.

## Tech Stack

- **FastMCP** — MCP framework
- **aiosqlite** — Async SQLite
- **SQLite** — Local database