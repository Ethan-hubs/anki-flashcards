#!/usr/bin/env python3
"""Spaced Repetition Flashcards - 后端
FastAPI + SQLite + FSRS 间隔重复（Free Spaced Repetition Scheduler）
API:
  GET   /api/index          章节列表（含每章卡片数）
  GET   /api/cards?chapter=&type=&limit=&mode=  获取卡片
  POST  /api/review         提交复习结果 {card_id, rating 0-3}
  GET   /api/stats          学习统计（总量/今日/热力图数据）
  GET   /api/due            今日待复习数量
  GET   /api/export         导出卡片 CSV
  POST  /api/import         导入卡片 CSV
"""
import json, os, sqlite3, time, csv, io
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fsrs import Card as FSRSCard, Rating as FSRSRating, Scheduler, State

# ---------- 配置（环境变量外部化） ----------
BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FLASHCARD_DATA_DIR", BASE / "data"))
DB_PATH = Path(os.environ.get("FLASHCARD_DB", BASE / "review.db"))
WEB_DIR = Path(os.environ.get("FLASHCARD_WEB_DIR", BASE / "web"))
HOST = os.environ.get("FLASHCARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("FLASHCARD_PORT", "8090"))

app = FastAPI(title="Spaced Repetition Flashcards")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_scheduler = Scheduler()

# ---------- 数据库 ----------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            card_id TEXT PRIMARY KEY,
            chapter TEXT,
            card_type TEXT,
            question TEXT,
            answer TEXT,
            explain TEXT,
            tags TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            card_id TEXT PRIMARY KEY,
            chapter TEXT,
            card_type TEXT,
            state INTEGER DEFAULT 0,
            step INTEGER DEFAULT 0,
            stability REAL DEFAULT 0,
            difficulty REAL DEFAULT 0,
            due_at REAL DEFAULT 0,
            last_review REAL DEFAULT 0,
            reps INTEGER DEFAULT 0,
            lapses INTEGER DEFAULT 0,
            scheduled_days REAL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS review_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT,
            rating INTEGER,
            reviewed_at REAL,
            state INTEGER,
            stability REAL,
            difficulty REAL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- 卡片数据 ----------
_index = None
def load_index():
    global _index
    if _index is None:
        idx_file = DATA_DIR / "index.json"
        if not idx_file.exists():
            # 零配置兜底：无数据时生成内置示例卡，保证开箱即有内容
            _bootstrap_demo()
            if not idx_file.exists():
                return []
        _index = json.loads(idx_file.read_text())
    return _index

def _bootstrap_demo():
    """生成内置示例卡片数据（首次启动且无讲义时）"""
    from scripts.build_cards import demo_cards  # noqa: E402
    demo = demo_cards()
    if not demo:
        return
    chap_dir = DATA_DIR / "chapters"
    chap_dir.mkdir(parents=True, exist_ok=True)
    fname = "示例章.json"
    with open(chap_dir / fname, "w") as f:
        json.dump(demo, f, ensure_ascii=False)
    idx = [{"chapter": "示例章", "chapter_title": "示例章", "file": f"chapters/{fname}",
            "count": len(demo),
            "choice": sum(1 for c in demo if c["type"] == "choice"),
            "qa": sum(1 for c in demo if c["type"] == "qa")}]
    with open(DATA_DIR / "index.json", "w") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    print("[零配置] 未找到卡片数据，已生成内置示例卡（放入 raw/ 并运行 scripts/build_cards.py 可替换）")

_cache = {}
def load_chapter(chapter_file):
    if chapter_file not in _cache:
        fp = DATA_DIR / chapter_file
        if not fp.exists():
            return []
        _cache[chapter_file] = json.loads(fp.read_text())
    return _cache[chapter_file]

def find_card(card_id):
    for i in load_index():
        for c in load_chapter(i["file"]):
            if c["id"] == card_id:
                return c
    return None

def seed_cards_from_data():
    """把 data/chapters/*.json 里的卡片同步进 cards 表（首次启动）"""
    conn = get_db()
    n = 0
    for i in load_index():
        for c in load_chapter(i["file"]):
            conn.execute("INSERT OR IGNORE INTO cards (card_id, chapter, card_type, question, answer, explain, tags) VALUES (?,?,?,?,?,?,?)",
                         (c["id"], c["chapter"], c["type"], c["question"], c["answer"], c.get("explain", ""), ",".join(c.get("tags", []))))
            n += 1
    conn.commit()
    conn.close()
    return n

seed_cards_from_data()

# ---------- FSRS 调度 ----------
# FSRS Card.card_id 需要 int，用内部自增 id_map 映射外部字符串 card_id
def fsrs_int_id(card_id):
    """字符串 card_id → FSRS 需要的 int（稳定映射）"""
    return abs(hash(card_id)) % (10**15)

def review_fsrs(card_id, rating_int, now=None):
    """执行 FSRS 调度，返回 (新状态 dict)"""
    now = now or datetime.now(timezone.utc)
    fsrs_id = fsrs_int_id(card_id)
    conn = get_db()
    row = conn.execute("SELECT * FROM reviews WHERE card_id=?", (card_id,)).fetchone()
    if row:
        card_dict = {
            "card_id": fsrs_id,
            "stability": row["stability"],
            "difficulty": row["difficulty"],
            "state": row["state"],
            "step": row["step"],
            "due": datetime.fromtimestamp(row["due_at"], tz=timezone.utc).isoformat(),
        }
        if row["last_review"]:
            card_dict["last_review"] = datetime.fromtimestamp(row["last_review"], tz=timezone.utc).isoformat()
        card = FSRSCard.from_dict(card_dict)
    else:
        card = FSRSCard(card_id=fsrs_id)
    # 前端评分 0-3（重来/困难/良好/简单）→ FSRS Rating 1-4
    rating_map = {0: FSRSRating.Again, 1: FSRSRating.Hard, 2: FSRSRating.Good, 3: FSRSRating.Easy}
    rating = rating_map[int(rating_int)]
    new_card, log = _scheduler.review_card(card, rating, review_datetime=now)
    due_ts = new_card.due.timestamp()
    # FSRS 6.x 不暴露 reps/lapses，用 review_log 计数代替
    src = find_card(card_id)
    chapter = src["chapter"] if src else ""
    card_type = src["type"] if src else ""
    row = conn.execute("SELECT COUNT(*) n FROM review_log WHERE card_id=?", (card_id,)).fetchone()
    reps = row["n"]
    lapses = conn.execute("SELECT COUNT(*) n FROM review_log WHERE card_id=? AND rating=0", (card_id,)).fetchone()["n"]
    conn.execute("""
        INSERT OR REPLACE INTO reviews (card_id, chapter, card_type, state, step, stability, difficulty, due_at, last_review, reps, lapses, scheduled_days)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (card_id, chapter, card_type, int(new_card.state), new_card.step, new_card.stability, new_card.difficulty,
          due_ts, now.timestamp(), reps, lapses, 0))
    conn.execute("""
        INSERT INTO review_log (card_id, rating, reviewed_at, state, stability, difficulty)
        VALUES (?,?,?,?,?,?)
    """, (card_id, int(rating), now.timestamp(), int(new_card.state), new_card.stability, new_card.difficulty))
    conn.commit()
    conn.close()
    return {"state": int(new_card.state), "stability": new_card.stability, "difficulty": new_card.difficulty,
            "due_at": due_ts, "interval_days": max(0, (due_ts - now.timestamp()) / 86400)}

# ---------- API ----------
@app.get("/api/index")
def get_index():
    idx = load_index()
    conn = get_db()
    due_map = {}
    total_map = {}
    for row in conn.execute("SELECT chapter, COUNT(*) n FROM reviews WHERE due_at <= ? GROUP BY chapter", (time.time(),)):
        due_map[row["chapter"]] = row["n"]
    for row in conn.execute("SELECT chapter, COUNT(*) n FROM reviews GROUP BY chapter"):
        total_map[row["chapter"]] = row["n"]
    conn.close()
    out = []
    for item in idx:
        item["due"] = due_map.get(item["chapter"], 0)
        item["learned"] = total_map.get(item["chapter"], 0)
        out.append(item)
    return {"chapters": out, "total": sum(i["count"] for i in idx)}

@app.get("/api/cards")
def get_cards(chapter: str | None = None, type: str | None = None, limit: int = 20, mode: str = "due"):
    idx = load_index()
    if chapter:
        items = [i for i in idx if i["chapter"] == chapter]
        if not items:
            raise HTTPException(404, "章节不存在")
        cards = load_chapter(items[0]["file"])
    else:
        cards = []
        for i in idx:
            cards.extend(load_chapter(i["file"]))
    if type and type in ("choice", "qa"):
        cards = [c for c in cards if c["type"] == type]

    conn = get_db()
    now = time.time()
    def has_review(c):
        return conn.execute("SELECT 1 FROM reviews WHERE card_id=?", (c["id"],)).fetchone() is not None
    def due_time(c):
        row = conn.execute("SELECT due_at FROM reviews WHERE card_id=?", (c["id"],)).fetchone()
        return row["due_at"] if row else 0
    if mode == "due":
        # 已复习且到期 + 从未复习的新卡（新卡只算一次）
        due_cards = [c for c in cards if has_review(c) and due_time(c) <= now]
        new_cards = [c for c in cards if not has_review(c)]
        selected = (due_cards + new_cards)[:limit]
    elif mode == "new":
        new_cards = [c for c in cards if not has_review(c)]
        selected = new_cards[:limit]
    else:
        selected = cards[:limit]
    conn.close()
    out = []
    for c in selected:
        out.append({"id": c["id"], "type": c["type"], "chapter": c["chapter"],
                    "chapter_title": c["chapter_title"], "question": c["question"],
                    "answer": c["answer"], "explain": c.get("explain", ""),
                    "tags": c.get("tags", [])})
    return {"cards": out}

class ReviewBody(BaseModel):
    card_id: str
    rating: int  # 0-3

@app.post("/api/review")
def submit_review(body: ReviewBody):
    if body.rating not in (0, 1, 2, 3):
        raise HTTPException(400, "rating 必须 0-3")
    card = find_card(body.card_id)
    if not card:
        # 允许导入的卡片（不在 chapters json 里）
        conn = get_db()
        row = conn.execute("SELECT card_id FROM cards WHERE card_id=?", (body.card_id,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(404, "卡片不存在")
    result = review_fsrs(body.card_id, body.rating)
    return {"ok": True, **result}

@app.get("/api/stats")
def stats():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) n FROM reviews").fetchone()["n"]
    due = conn.execute("SELECT COUNT(*) n FROM reviews WHERE due_at <= ?", (time.time(),)).fetchone()["n"]
    today_start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    today = conn.execute("SELECT COUNT(*) n FROM review_log WHERE reviewed_at >= ?", (today_start,)).fetchone()["n"]
    # 热力图数据：最近 13 周每日复习数
    heatmap = {}
    week_start = today_start - 90 * 86400
    for row in conn.execute("SELECT reviewed_at FROM review_log WHERE reviewed_at >= ?", (week_start,)):
        day = datetime.fromtimestamp(row["reviewed_at"]).strftime("%Y-%m-%d")
        heatmap[day] = heatmap.get(day, 0) + 1
    by_type = {r["card_type"]: r["n"] for r in conn.execute("SELECT card_type, COUNT(*) n FROM reviews GROUP BY card_type")}
    by_chapter = {r["chapter"]: r["n"] for r in conn.execute("SELECT chapter, COUNT(*) n FROM reviews GROUP BY chapter")}
    conn.close()
    return {"total_reviewed": total, "due_now": due, "today_reviewed": today,
            "heatmap": heatmap, "by_type": by_type, "by_chapter": by_chapter}

@app.get("/api/due")
def due_count():
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) n FROM reviews WHERE due_at <= ?", (time.time(),)).fetchone()["n"]
    conn.close()
    return {"due": n}

@app.get("/api/export")
def export_csv():
    """导出卡片为 CSV（question,answer,explain,chapter,type）"""
    conn = get_db()
    rows = conn.execute("SELECT card_id, chapter, card_type, question, answer, explain, tags FROM cards").fetchall()
    conn.close()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["question", "answer", "explain", "chapter", "type", "tags"])
    for r in rows:
        writer.writerow([r["question"], r["answer"], r["explain"], r["chapter"], r["card_type"], r["tags"]])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=flashcards.csv"})

@app.post("/api/import")
async def import_csv(file: UploadFile = File(...)):
    """导入卡片 CSV（question,answer,explain,chapter,type,tags）"""
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    conn = get_db()
    n = 0
    for row in reader:
        q = row.get("question", "").strip()
        a = row.get("answer", "").strip()
        if not q or not a:
            continue
        card_id = row.get("card_id") or f"imp-{abs(hash(q)):x}"
        conn.execute("""
            INSERT OR REPLACE INTO cards (card_id, chapter, card_type, question, answer, explain, tags)
            VALUES (?,?,?,?,?,?,?)
        """, (card_id, row.get("chapter", "导入"), row.get("type", "qa"), q, a,
              row.get("explain", ""), row.get("tags", "")))
        n += 1
    conn.commit()
    conn.close()
    return {"ok": True, "imported": n}

# 静态前端
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
