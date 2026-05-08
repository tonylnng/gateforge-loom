# VM Deployment Guide

Target: a single Ubuntu 22.04 LTS VM with Docker + Compose. Tested against
2 vCPU / 4 GB RAM minimum; recommended 4 vCPU / 8 GB RAM for live LLM use.

---

## 1. Prerequisites

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git make jq

# Docker Engine + Compose plugin (official repo)
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Allow current user to run docker
sudo usermod -aG docker "$USER"
newgrp docker      # or log out and back in
```

Verify:
```bash
docker --version
docker compose version
```

---

## 2. Clone and configure

```bash
git clone https://github.com/tonylnng/gateforge-loom.git /opt/gateforge-loom
cd /opt/gateforge-loom
cp .env.example .env
chmod 600 .env

# Edit .env — at minimum, change:
#   POSTGRES_PASSWORD
#   REDIS_PASSWORD
#   INTERNAL_API_TOKEN          (32+ random chars)
#   N8N_BASIC_AUTH_PASSWORD
#   N8N_ENCRYPTION_KEY          (exactly 32 chars; KEEP STABLE)
#   ANTHROPIC_API_KEY           (when going live)
$EDITOR .env
```

Generate secrets quickly:
```bash
openssl rand -hex 16        # for INTERNAL_API_TOKEN
openssl rand -hex 16        # for N8N_ENCRYPTION_KEY (32 hex chars)
```

---

## 3. Bring it up

```bash
make up
make health
make test
```

After ~10 seconds:
- n8n → <http://VM_IP:5678>  (basic-auth from `.env`)
- claude-gateway → <http://VM_IP:8001/health>
- openclaw       → <http://VM_IP:8002/health>
- hermes         → <http://VM_IP:8003/health>

Import the workflow:
1. Log in to n8n.
2. Workflows → Import from File → select
   `n8n/workflows/gateforge-loom-pipeline.json`.
3. Click **Activate**.
4. Trigger via the Webhook URL shown in the **Webhook Trigger** node.

---

## 4. Network exposure

Recommended firewall rules (UFW):

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 5678/tcp comment 'n8n UI'
# Do NOT expose 8001-8003 to the public internet.
sudo ufw enable
```

For a multi-machine setup, prefer **Tailscale**:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
# Now reach internal services at http://<tailnet-name>.ts.net:8001 etc.
```

Then put a reverse proxy (Caddy or nginx) in front of n8n with HTTPS:

```caddyfile
loom.example.com {
    reverse_proxy localhost:5678
}
```

---

## 5. Backups

Two volumes matter: `postgres-data` (durable memory) and `n8n-data`
(workflows + credentials).

Nightly backup script — drop into `/etc/cron.daily/gateforge-loom-backup`:

```bash
#!/usr/bin/env bash
set -euo pipefail
DEST="/var/backups/gateforge-loom"
mkdir -p "$DEST"
DATE=$(date +%F)

# Postgres logical dump
docker exec gfl-postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > "$DEST/hermes-$DATE.sql.gz"

# n8n volume snapshot
docker run --rm \
  -v gateforge-loom_n8n-data:/src:ro \
  -v "$DEST":/dst \
  alpine tar czf "/dst/n8n-$DATE.tgz" -C /src .

# Retain 14 days
find "$DEST" -type f -mtime +14 -delete
```

Test restore quarterly. A backup you haven't restored is a wish, not a backup.

---

## 6. Updating

```bash
cd /opt/gateforge-loom
git pull
make build       # rebuild changed images
make up          # rolling recreate (Compose uses --force-recreate as needed)
```

Zero-downtime updates require a load balancer; for a single-VM PoC,
expect ~10 s of API gap during `up`.

---

## 7. Hardening checklist

- [ ] All passwords in `.env` are unique and ≥ 24 chars
- [ ] `.env` is `chmod 600`, owner-only
- [ ] `INTERNAL_API_TOKEN` is set (so inter-service calls require auth)
- [ ] `N8N_ENCRYPTION_KEY` will not change (otherwise n8n can't decrypt
      stored credentials)
- [ ] UFW or cloud security group blocks ports 8001-8003 from public
- [ ] Reverse proxy fronts n8n with HTTPS
- [ ] Postgres + n8n volumes backed up nightly
- [ ] Logs aggregated (Loki / Papertrail / CloudWatch)
- [ ] Healthcheck monitoring wired (uptime-kuma, Healthchecks.io)
- [ ] Per-job token budget configured in Redis to prevent runaway costs

---

## 8. Troubleshooting

| Symptom | First check |
|---|---|
| `make up` fails on Postgres | `docker logs gfl-postgres` — usually a stale `postgres-data` volume from a previous run with a different password. `make clean` will wipe it. |
| n8n returns 401 | `N8N_BASIC_AUTH_*` mismatch with what you typed. |
| Hermes `/health` returns `degraded` | DB connection issue; check `DATABASE_URL` and that `gfl-postgres` is healthy. |
| Inter-service calls 401 | `INTERNAL_API_TOKEN` differs between caller and callee. All services share one token. |
| n8n can't reach `claude-gateway:8000` | n8n internal URL must use the *service name*, not `localhost`. |
| Stub mode returning real-looking errors | Check `STUB_MODE=1` is actually exported into the container (`docker exec gfl-claude-gateway env | grep STUB`). |
