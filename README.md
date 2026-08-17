<p align="center">
  <h1 align="center">📚 Spaced Repetition Flashcards</h1>
  <p align="center">Self-hosted flashcard web app with <b>FSRS scheduling</b> — turn your study notes into an interactive review deck.</p>
  <p align="center">
    <a href="https://www.python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square" alt="Python"></a>
    <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.110%2B-009688?style=flat-square" alt="FastAPI"></a>
    <a href="https://github.com/open-spaced-repetition/fsrs4python"><img src="https://img.shields.io/badge/Scheduler-FSRS-4f6ef7?style=flat-square" alt="FSRS"></a>
    <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License"></a>
    <a href="https://github.com/Ethan-hubs/anki-flashcards/actions"><img src="https://img.shields.io/github/actions/workflow/status/Ethan-hubs/anki-flashcards/ci.yml?style=flat-square" alt="CI"></a>
  </p>
</p>

---

## ✨ Features

| | |
|---|---|
| 🔁 **FSRS scheduling** | The modern Free Spaced Repetition Scheduler — the algorithm family behind Anki. Rate Again / Hard / Good / Easy. |
| 📝 **Two card modes** | Multiple-choice (instant feedback + explanation) and Q&A (tap to flip). |
| 📂 **Per-chapter review** | Study one chapter at a time, or sweep all due cards at once. |
| 📊 **Study stats** | 13-week review heatmap, daily counts, per-chapter / per-type breakdown. |
| ✨ **Markdown cards** | Questions, answers and explanations support markdown — tables, code, lists. |
| 🧾 **CSV import / export** | Bring cards in from a spreadsheet; back your deck up anytime. |
| 🛠 **Auto card extraction** | Drop your notes in `raw/`, run one command — `scripts/build_cards.py` auto-scans and generates cards. |
| 🔒 **PIN lock (optional)** | Client-side SHA-256 PIN gate. Disabled by default (zero-config); set a hash to enable. |
| 📱 **Mobile-friendly** | Works great on phones; no app install. |
| 🐳 **Docker-ready** | One command to deploy via `docker compose up -d`. |

## 🚀 Quick Start

**Docker (recommended):**

```bash
git clone https://github.com/Ethan-hubs/anki-flashcards.git
cd anki-flashcards
docker compose up -d
# → http://localhost:8090
```

**Bare metal:**

```bash
pip install -r requirements.txt

# 零配置：直接启动，内置示例卡开箱即用
python3 server.py        # → http://127.0.0.1:8090

# 用你自己的讲义生成卡片（自动扫描 raw/ 下所有 .md，文件名即章节名）：
mkdir -p raw data
cp ~/我的讲义.md raw/第一章xxx.md
python3 scripts/build_cards.py
```

## 📁 Project Layout

```
anki-flashcards/
├── server.py              # FastAPI backend (REST API + static hosting)
├── scripts/
│   └── build_cards.py     # Card extractor: markdown notes → choice + Q&A cards
├── web/
│   ├── index.html         # Frontend SPA (PIN lock, stats heatmap, markdown)
│   └── marked.min.js      # Markdown renderer (vendored, no CDN dependency)
├── tests/
│   └── test_api.py        # pytest suite (scheduler + API endpoints)
├── deploy/
│   ├── anki-flashcards.service   # systemd unit example
│   └── Caddyfile.example         # Caddy reverse proxy example
├── data/                  # Generated card data (from build_cards.py, gitignored)
├── raw/                   # Your lecture notes (gitignored)
├── db/
│   └── schema.sql         # Database schema (SQLite, for reference/migration)
├── Dockerfile             # Container image
├── docker-compose.yml     # One-command deployment
├── pyproject.toml         # Package metadata (pip install -e .)
├── requirements.txt       # Runtime dependencies
└── requirements-dev.txt   # Dev/test dependencies
```

## ⚙️ Configuration

All settings are environment variables:

| Variable | Default | Description |
|---|---|---|
| `FLASHCARD_HOST` | `127.0.0.1` | Bind address |
| `FLASHCARD_PORT` | `8090` | Listen port |
| `FLASHCARD_DATA_DIR` | `./data` | Card data directory |
| `FLASHCARD_DB` | `./review.db` | SQLite database path |
| `FLASHCARD_WEB_DIR` | `./web` | Frontend static directory |

**PIN lock (optional):** disabled by default (zero-config). To enable, set `PIN_HASH` in `web/index.html`:

```bash
echo -n "your-pin" | sha256sum   # write the output into the PIN_HASH constant
```

> ⚠️ **Security note**: the PIN is a client-side lock (obfuscation only) — it deters casual visitors but is not real authentication. Anyone with the source can bypass it. For public deployments, put the app behind a real auth proxy (Caddy `basic_auth`, Authelia, nginx auth) or keep it on a trusted network. The write APIs (`/api/review`, `/api/import`) have no server-side auth by design (single-user tool).

## 📡 API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/index` | Chapter list (card counts + due counts) |
| GET | `/api/cards?chapter=&type=&limit=&mode=` | Fetch cards (`due` / `new` / `all`) |
| POST | `/api/review` | Submit a rating `{card_id, rating: 0-3}` |
| GET | `/api/stats` | Study statistics (totals + heatmap) |
| GET | `/api/due` | Due-card count |
| GET | `/api/export` | Export all cards as CSV |
| POST | `/api/import` | Import cards from CSV (`file` multipart) |

Rating values: `0` = Again, `1` = Hard, `2` = Good, `3` = Easy.

## 🧪 Development

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v
```

## 🌐 Deployment

**systemd:**

```bash
sudo cp deploy/anki-flashcards.service /etc/systemd/system/
sudo systemctl enable --now anki-flashcards
```

**Caddy reverse proxy:**

```nginx
anki.example.com {
	encode zstd gzip
	reverse_proxy localhost:8090
}
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m 'Add some feature'`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

## 📄 License

[MIT](LICENSE)
