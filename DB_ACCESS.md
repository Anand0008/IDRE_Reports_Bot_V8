# Reports Bot — IDRE Prod DB Access

What the bot needs from whoever owns the AWS RDS / IDRE prod DB.

---

## What to provision

A **read-only MySQL user** on the IDRE prod RDS cluster. Bot uses it to run `SELECT` queries only.

```sql
-- On the IDRE prod MySQL:
CREATE USER 'reports_bot_ro'@'%' IDENTIFIED BY '<strong-password>';
GRANT SELECT ON idre_prod.* TO 'reports_bot_ro'@'%';
FLUSH PRIVILEGES;
```

- User: `reports_bot_ro` (any name works, keep it obviously read-only)
- Permissions: **SELECT only**. No INSERT, UPDATE, DELETE, DDL.
- Scope: all tables in the IDRE prod schema. The bot's own role-based access control filters further per end-user.
- Network: the RDS security group must allow inbound from wherever the bot is deployed (VPC/subnet/IP of the FastAPI service).

---

## What to hand over

Share these five values with whoever deploys the bot (put them in the bot's `.env`, not in code):

| Variable       | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| `DB_HOST`      | RDS cluster endpoint, e.g. `<rds-endpoint>` |
| `DB_PORT`      | `3306`                                                          |
| `DB_NAME`      | IDRE prod schema name (likely `idre_prod` or similar)           |
| `DB_USER`      | `reports_bot_ro`                                                |
| `DB_PASSWORD`  | the password set above                                          |

Also drop the AWS RDS SSL bundle at `./global-bundle.pem` next to the bot code (already present in the repo, just confirm it's current — download from [AWS docs](https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem) if stale).

---

## Quick verification

From the bot's host, this should return `1`:

```bash
mysql -h $DB_HOST -P 3306 -u reports_bot_ro -p \
      --ssl-ca=./global-bundle.pem \
      -e "SELECT 1"
```

If that works, the bot will connect. If it hangs, it's a security group / VPC issue, not a credential issue.

---

## Security notes

- **Don't reuse the IDRE app's DB user.** That one has write access. If the bot ever misbehaves (prompt injection, bug), it could mutate prod data. A dedicated read-only user is the cheapest safety net.
- **Don't give the bot access to auth tables** if you can help it (`user`, `session`, `account`, `verification`, `twoFactor`). The bot doesn't need to query them. If you want to be strict:
  ```sql
  REVOKE SELECT ON idre_prod.user       FROM 'reports_bot_ro'@'%';
  REVOKE SELECT ON idre_prod.session    FROM 'reports_bot_ro'@'%';
  REVOKE SELECT ON idre_prod.account    FROM 'reports_bot_ro'@'%';
  REVOKE SELECT ON idre_prod.verification FROM 'reports_bot_ro'@'%';
  REVOKE SELECT ON idre_prod.twoFactor  FROM 'reports_bot_ro'@'%';
  ```
  Then confirm the bot's role-access config doesn't list those tables either.
- **Rotate the password** via Secrets Manager, not hardcoded in `.env` for long-lived deployments.
- **Log queries at RDS level** (enable MySQL general log or audit plugin) — gives you an audit trail separate from whatever the bot logs itself.
