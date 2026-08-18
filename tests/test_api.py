"""pytest 测试：FSRS 调度 + API 端点"""
import os, sys, tempfile, time
from pathlib import Path

# 测试用独立数据目录（不污染生产库）
TEST_DIR = Path(tempfile.mkdtemp(prefix="flashcard-test-"))
ROOT = Path(__file__).resolve().parent.parent
os.environ["FLASHCARD_DATA_DIR"] = str(TEST_DIR / "data")
os.environ["FLASHCARD_DB"] = str(TEST_DIR / "review.db")
os.environ["FLASHCARD_WEB_DIR"] = str(ROOT / "web")

# 造一份最小测试数据
(TEST_DIR / "data" / "chapters").mkdir(parents=True)
(TEST_DIR / "data").joinpath("index.json").write_text(
    '[{"chapter":"第一章","chapter_title":"测试章","file":"chapters/测试.json","count":3}]',
    encoding="utf-8")
(TEST_DIR / "data" / "chapters").joinpath("测试.json").write_text(
    '[{"id":"t1","type":"qa","chapter":"第一章","chapter_title":"测试章","question":"Q1?","answer":"A1","explain":"E1","tags":[]},'
    '{"id":"t2","type":"choice","chapter":"第一章","chapter_title":"测试章","question":"Q2?\\nA. x\\nB. y","answer":"A. x","explain":"","tags":[]},'
    '{"id":"t3","type":"qa","chapter":"第一章","chapter_title":"测试章","question":"Q3?","answer":"A3","explain":"","tags":[]}]',
    encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))
import server
from fastapi.testclient import TestClient

client = TestClient(server.app)


def test_index():
    r = client.get("/api/index")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert data["chapters"][0]["chapter"] == "第一章"


def test_cards_due_mode():
    r = client.get("/api/cards", params={"chapter": "第一章", "limit": 10, "mode": "due"})
    assert r.status_code == 200
    cards = r.json()["cards"]
    assert len(cards) == 3  # 全为新卡，due 模式应全部返回


def test_cards_type_filter():
    r = client.get("/api/cards", params={"chapter": "第一章", "type": "choice"})
    cards = r.json()["cards"]
    assert len(cards) == 1
    assert cards[0]["type"] == "choice"


def test_review_bad_rating():
    r = client.post("/api/review", json={"card_id": "t1", "rating": 5})
    assert r.status_code == 400


def test_review_unknown_card():
    r = client.post("/api/review", json={"card_id": "nope", "rating": 2})
    assert r.status_code == 404


def test_review_fsrs_schedule():
    """FSRS：简单（rating=3）应给出正间隔；忘记（rating=0）应重学"""
    r = client.post("/api/review", json={"card_id": "t1", "rating": 3})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["interval_days"] > 0  # 简单 → 未来复习
    assert data["state"] == 2  # Review 状态

    # 忘记 → 10 分钟内重学（FSRS Again 间隔），状态进入 Relearning(3)
    r2 = client.post("/api/review", json={"card_id": "t1", "rating": 0})
    data2 = r2.json()
    assert data2["interval_days"] < 1
    assert data2["state"] == 3  # Relearning 状态


def test_review_marketing_metrics():
    """复习后 stats 应有记录 + 热力图"""
    client.post("/api/review", json={"card_id": "t2", "rating": 2})
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total_reviewed"] >= 1
    assert len(data["heatmap"]) >= 1
    assert "第一章" in data["by_chapter"]


def test_due_count():
    r = client.get("/api/due")
    assert r.status_code == 200
    assert "due" in r.json()


def test_export_csv():
    r = client.get("/api/export")
    assert r.status_code == 200
    assert "question" in r.text
    assert "Q1?" in r.text


def test_import_csv():
    csv_content = "question,answer,explain,chapter,type,tags\n导入题,导入答,导入解,导入章,qa,\n"
    r = client.post("/api/import", files={"file": ("test.csv", csv_content, "text/csv")})
    assert r.status_code == 200
    assert r.json()["imported"] == 1


# ---------- 卡片 CRUD 与文件夹 ----------

def test_create_card():
    r = client.post("/api/cards", json={
        "chapter": "第一章", "type": "qa", "question": "新增题?", "answer": "新增答", "explain": "", "tags": ["新"]})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    cid = data["card"]["id"]
    assert len(cid) == 12  # md5 前 12 位
    # 章节 JSON 与 cards 表都已更新
    r2 = client.get("/api/cards", params={"chapter": "第一章", "limit": 100, "mode": "all"})
    ids = [c["id"] for c in r2.json()["cards"]]
    assert cid in ids
    conn = __import__("sqlite3").connect(os.environ["FLASHCARD_DB"])
    n = conn.execute("SELECT COUNT(*) FROM cards WHERE card_id=?", (cid,)).fetchone()[0]
    conn.close()
    assert n == 1
    # 重复内容 → 409
    r3 = client.post("/api/cards", json={
        "chapter": "第一章", "type": "qa", "question": "新增题?", "answer": "新增答", "explain": ""})
    assert r3.status_code == 409


def test_update_card():
    # 修改 t1 内容与题型
    r = client.put("/api/cards/t1", json={
        "chapter": "第一章", "type": "choice", "question": "Q1改?\nA. x\nB. y", "answer": "A. x", "explain": "解析改", "tags": ["改"]})
    assert r.status_code == 200
    assert r.json()["card"]["question"].startswith("Q1改")
    r2 = client.get("/api/cards", params={"chapter": "第一章", "limit": 100, "mode": "all"})
    t1 = next(c for c in r2.json()["cards"] if c["id"] == "t1")
    assert t1["type"] == "choice"
    assert t1["explain"] == "解析改"


def test_move_card_chapter():
    # 新建文件夹，把 t2 移过去
    r = client.post("/api/folders", json={"name": "易错题"})
    assert r.status_code == 200
    r2 = client.put("/api/cards/t2", json={
        "chapter": "易错题", "type": "choice", "question": "Q2?\nA. x\nB. y", "answer": "A. x", "explain": ""})
    assert r2.status_code == 200
    assert r2.json()["card"]["chapter"] == "易错题"
    # 原章节不再有 t2，新章节有
    r3 = client.get("/api/cards", params={"chapter": "第一章", "limit": 100, "mode": "all"})
    assert all(c["id"] != "t2" for c in r3.json()["cards"])
    r4 = client.get("/api/cards", params={"chapter": "易错题", "limit": 100, "mode": "all"})
    assert any(c["id"] == "t2" for c in r4.json()["cards"])
    # 复习 t2 后再移动，reviews 的 chapter 同步
    client.post("/api/review", json={"card_id": "t2", "rating": 2})
    conn = __import__("sqlite3").connect(os.environ["FLASHCARD_DB"])
    chap = conn.execute("SELECT chapter FROM reviews WHERE card_id='t2'").fetchone()[0]
    conn.close()
    assert chap == "易错题"


def test_delete_card():
    client.post("/api/review", json={"card_id": "t3", "rating": 2})
    r = client.delete("/api/cards/t3")
    assert r.status_code == 200
    # 卡片、进度、日志全部清除
    r2 = client.get("/api/cards", params={"chapter": "第一章", "limit": 100, "mode": "all"})
    assert all(c["id"] != "t3" for c in r2.json()["cards"])
    conn = __import__("sqlite3").connect(os.environ["FLASHCARD_DB"])
    for tbl in ("cards", "reviews", "review_log"):
        n = conn.execute(f"SELECT COUNT(*) FROM {tbl} WHERE card_id='t3'").fetchone()[0]
        assert n == 0
    conn.close()
    # 不存在 → 404
    assert client.delete("/api/cards/nope").status_code == 404


def test_create_folder_duplicate():
    r = client.post("/api/folders", json={"name": "易错题"})
    assert r.status_code == 409
    r2 = client.post("/api/folders", json={"name": "  "})
    assert r2.status_code == 400
    # 新文件夹出现在 index
    r3 = client.get("/api/index")
    assert any(c["chapter"] == "易错题" for c in r3.json()["chapters"])
