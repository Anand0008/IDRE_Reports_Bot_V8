# Reports Bot — API for UI/UX

One endpoint. Call it. Done.

---

## Endpoint

```
POST https://<bot-host>/api/v1/query
Content-Type: application/json
```

### Request

```json
{
  "query": "How many open disputes this month?",
  "history": [
    { "role": "user",      "content": "Show me cases in PENDING_PAYMENTS" },
    { "role": "assistant", "content": "Found 1,204 cases..." }
  ]
}
```

- `query` — string, required. The user's question.
- `history` — optional. Last ~10 messages of the chat. Lets the bot resolve "show me top 5 of those" etc. Store it client-side (component state / localStorage) and pass it in each call.

No auth headers, no role, no user info. The bot reads the IDRE session cookie automatically via `credentials: "include"` — it figures out who's asking from that.

### Response (200)

```json
{
  "answer":      "**43,994** open disputes.\n\n_Assumptions: 'open' = not in terminal status._",
  "table":       [{ "status": "PENDING_PAYMENTS", "count": 24110 }],
  "chart":       { "type": "bar", "x": "status", "y": "count" },
  "suggestions": ["Break that down by organization", "Show trend over last 6 months"],
  "sql":         "SELECT status, COUNT(*) ..."
}
```

- `answer` — always present. Markdown. Render as the chat bubble.
- `table` — optional. Array of rows. Render as a table if present.
- `chart` — optional. `type` is `"bar" | "line" | "pie" | "kpi"`. Field names (`x`, `y`) reference column names in `table`. If absent, no chart.
- `suggestions` — optional. Strings. Render as clickable chips.
- `sql` — optional. Hide behind a "Show SQL" toggle for devs.

### Errors

All errors look like this:

```json
{ "error": "UNAUTHORIZED", "message": "Your session has expired." }
```

| HTTP | `error`           | What to do                                    |
| ---- | ----------------- | --------------------------------------------- |
| 400  | `BAD_REQUEST`     | Show "Please rephrase your question"          |
| 401  | `UNAUTHORIZED`    | Prompt to refresh page / re-login             |
| 403  | `FORBIDDEN`       | Hide the widget for this user's role          |
| 429  | `RATE_LIMITED`    | "Try again in a moment"                       |
| 500  | `INTERNAL_ERROR`  | Generic "something went wrong"                |
| 504  | `TIMEOUT`         | "Try a narrower question"                     |

---

## Drop-in client (TypeScript)

```ts
type ChatMsg = { role: "user" | "assistant"; content: string };

export type BotReply = {
  answer: string;
  table?: Array<Record<string, unknown>>;
  chart?: { type: "bar" | "line" | "pie" | "kpi"; x?: string; y?: string; label?: string; value?: string | number };
  suggestions?: string[];
  sql?: string;
};

export async function askBot(query: string, history: ChatMsg[]): Promise<BotReply> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_BOT_URL}/api/v1/query`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, history: history.slice(-10) }),
    signal: AbortSignal.timeout(35_000),
  });

  const body = await res.json();
  if (!res.ok) {
    throw Object.assign(new Error(body.message ?? "Bot error"), {
      code: body.error ?? "UNKNOWN",
      status: res.status,
    });
  }
  return body;
}
```

Set `NEXT_PUBLIC_BOT_URL` to wherever the bot is deployed.

---

## Notes for UI/UX

- **Latency:** 2–10 seconds typical, up to 30s for complex queries. Show a loading indicator; don't freeze the input.
- **History:** The widget owns it. Keep last ~10 turns in component state (or localStorage if you want it to survive reload). Bot is stateless.
- **403 = hide the widget.** Users with a role the bot won't serve (e.g. `party`) should just not see the chat icon.
- **Chart rendering:** Use whatever — Recharts, Chart.js. The bot tells you *what* to chart via `chart.x` / `chart.y`; you pick *how*.

---

## Deployment plan (not UI/UX's problem, but FYI)

- Bot runs as a separate service at `https://<bot-host>` (same root domain as IDRE so the auth cookie flows).
- Bot validates every request by forwarding the IDRE session cookie to `GET /api/auth/get-session` on IDRE. Invalid = 401, `party` role = 403. UI/UX doesn't send any auth info — it's all cookie-based.
- Backend engineer owns building the FastAPI wrapper around `core/orchestrator.run_query()`. It's roughly 60 lines of code; see `server.py` template in the repo when it lands.
