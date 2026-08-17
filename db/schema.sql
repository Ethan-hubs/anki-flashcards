-- Spaced Repetition Flashcards - 数据库结构
-- SQLite 3 兼容。应用首次启动会自动创建这些表（见 server.py init_db），
-- 本文件用于文档参考 / 手动重建 / 迁移。

-- 卡片表：所有卡片（含 build_cards.py 生成 + CSV 导入的）
CREATE TABLE IF NOT EXISTS cards (
    card_id  TEXT PRIMARY KEY,      -- 卡片唯一 ID（md5 短哈希）
    chapter  TEXT,                  -- 章节名（如"第一章"）
    card_type TEXT,                 -- 'choice' 选择题 / 'qa' 问答
    question TEXT,                  -- 题干（支持 Markdown）
    answer   TEXT,                  -- 答案
    explain  TEXT,                  -- 解析（可选）
    tags     TEXT DEFAULT ''        -- 逗号分隔标签
);

-- 复习进度表：每张卡的 FSRS 调度状态（1:1 卡片）
CREATE TABLE IF NOT EXISTS reviews (
    card_id        TEXT PRIMARY KEY,
    chapter        TEXT,
    card_type      TEXT,
    state          INTEGER DEFAULT 0,   -- FSRS State: 0=New 1=Learning 2=Review 3=Relearning
    step           INTEGER DEFAULT 0,
    stability      REAL DEFAULT 0,
    difficulty     REAL DEFAULT 0,
    due_at         REAL DEFAULT 0,      -- Unix 时间戳，到期时间
    last_review    REAL DEFAULT 0,      -- 上次复习时间
    reps           INTEGER DEFAULT 0,   -- 复习次数
    lapses         INTEGER DEFAULT 0,   -- 遗忘次数
    scheduled_days REAL DEFAULT 0
);

-- 复习日志表：每次复习的流水（用于统计热力图）
CREATE TABLE IF NOT EXISTS review_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     TEXT,
    rating      INTEGER,                -- 0=Again 1=Hard 2=Good 3=Easy
    reviewed_at REAL,                   -- 复习时间戳
    state       INTEGER,
    stability   REAL,
    difficulty  REAL
);

-- 常用查询
-- 今日待复习：SELECT COUNT(*) FROM reviews WHERE due_at <= strftime('%s','now');
-- 热力图数据：SELECT date(reviewed_at,'unixepoch','localtime') day, COUNT(*) FROM review_log GROUP BY day;
