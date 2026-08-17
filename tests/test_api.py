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
