#!/usr/bin/env python3
"""从讲义 md 提取闪卡：选择题卡 + 问答卡 v2
自动扫描 raw/ 目录下的所有 .md 文件（文件名即章节名），
提取真题选择题（A./B./C./D. + 【答案】）和知识点问答。
用法：
    python3 scripts/build_cards.py
    # 把你的讲义按章节命名丢进 raw/，如 第一章法律基本原理.md（任意文件名均可）
"""
import re, os, json, hashlib
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / 'raw'
OUT = BASE / 'data'
os.makedirs(OUT, exist_ok=True)

def scan_files():
    """自动扫描 raw/ 下所有 .md；文件名即"章节名 章节标题"。
    支持两种命名：'第一章法律基本原理.md'（中文序号开头）或任意文件名（直接作标题）。"""
    if not RAW.exists():
        print(f"[提示] raw/ 目录不存在（{RAW}），请先放入讲义 md 文件")
        return []
    files = sorted(RAW.glob('*.md'))
    if not files:
        print("[提示] raw/ 下没有 .md 文件，请先放入讲义")
        return []
    result = []
    for fp in files:
        name = fp.stem
        m = re.match(r'^(第[一二三四五六七八九十百\d]+章)\s*(.*)$', name)
        if m:
            chapter, title = m.group(1), m.group(2) or name
        else:
            chapter, title = name, name
        result.append((fp, chapter, title))
    return result

def demo_cards():
    """生成内置示例卡片（无讲义时开箱体验用）"""
    cards = []
    demo = [
        ("示例章", "问答", "什么是间隔重复（Spaced Repetition）？",
         "在记忆即将遗忘的临界点安排复习，用递增间隔强化长期记忆。", "SRS 核心概念"),
        ("示例章", "问答", "FSRS 是什么？",
         "Free Spaced Repetition Scheduler，一种现代间隔重复调度算法（Anki 同款）。", "调度算法"),
        ("示例章", "选择", "下列哪项是间隔重复的优势？\n\nA. 一次学完永不遗忘\nB. 按遗忘曲线安排复习\nC. 无需任何复习\nD. 只适合背单词",
         "B. 按遗忘曲线安排复习", "间隔重复按遗忘曲线安排复习时机，效率远高于死记硬背。"),
        ("示例章", "问答", "如何生成自己的卡片库？",
         "将讲义按章节命名放入 raw/ 目录（如 第一章xxx.md），运行 python3 scripts/build_cards.py。", "使用指南"),
    ]
    for i, (ch, t, q, a, e) in enumerate(demo):
        cards.append({
            "id": f"demo-{i}", "type": "choice" if t == "选择" else "qa",
            "chapter": ch, "chapter_title": ch, "question": q, "answer": a,
            "explain": e, "tags": [],
        })
    return cards

def extract_choice_cards(text, chapter, ch_title):
    """按【答案】位置切分：题干区域 = 上一【解析】结束 到 当前【答案】"""
    cards = []
    ans_matches = list(re.finditer(r'【答案】\s*([^\n]*)', text))
    exp_matches = list(re.finditer(r'【解析】', text))
    for i, m in enumerate(ans_matches):
        # 题干区域起点：上一个【解析】结束 或 文本开头
        prev_end = 0
        for em in exp_matches:
            if em.start() < m.start():
                prev_end = em.end()
            else:
                break
        before = text[prev_end:m.start()].strip()
        # 选项
        opts = re.findall(r'([A-D])[.、．]\s*([^\n]+)', before)
        if len(opts) < 2:
            continue
        # 题干 = 第一个选项之前，只取最后一段（去掉前置章节噪声）
        first_pos = min(before.find(f"{l}.") if f"{l}." in before else before.find(f"{l}、") for l, _ in opts)
        stem = before[:first_pos].strip()
        # 题干噪声清理：取最后一个 \n\n 之后的段落
        if '\n\n' in stem:
            stem = stem.split('\n\n')[-1].strip()
        if len(stem) < 8:
            continue
        opt_text = "\n".join(f"{l}. {t}" for l, t in opts)
        # 答案
        answer_letters = m.group(1).strip()
        correct = "\n".join(f"{l}. {t}" for l, t in opts if l in answer_letters)
        if not correct:
            correct = answer_letters
        # 解析：当前答案之后最近的【解析】
        explain = ''
        for em in exp_matches:
            if em.start() > m.start():
                explain = text[em.end():em.end()+200].strip().split('\n\n')[0].strip()
                break
        cards.append({
            "type": "choice", "chapter": chapter, "chapter_title": ch_title,
            "question": f"{stem}\n\n{opt_text}", "answer": correct,
            "explain": explain, "tags": [],
            "id": hashlib.md5(f"choice:{chapter}:{stem[:60]}".encode()).hexdigest()[:12],
        })
    return cards

def make_qa_cards(text, chapter, ch_title):
    cards = []
    sections = re.split(r'(?=【知识点[一二三四五六七八九十\d]+】)', text)
    for sec in sections:
        km = re.match(r'【知识点[一二三四五六七八九十\d]+】([^\n]*)', sec)
        if not km:
            continue
        kp_title = km.group(1).strip()
        body = sec[len(km.group(0)):]
        def_m = re.search(r'([\u4e00-\u9fff]{2,20})(?:是指|是指：|是)([^\n。；]{10,80}。?)', body)
        if def_m and len(def_m.group(0)) > 15:
            cards.append({
                "type": "qa", "chapter": chapter, "chapter_title": ch_title,
                "question": f"什么是「{def_m.group(1)}」？", "answer": def_m.group(0).strip(),
                "explain": f"出自知识点：{kp_title}", "tags": [kp_title],
                "id": hashlib.md5(f"qa:{chapter}:{def_m.group(1)}".encode()).hexdigest()[:12],
            })
        items = re.findall(r'\n?(\d+)[.、．]\s*([^\n]{4,60})', body)
        if len(items) >= 3:
            q_items = "\n".join(f"{n}. {t}" for n, t in items[:8])
            cards.append({
                "type": "qa", "chapter": chapter, "chapter_title": ch_title,
                "question": f"【{kp_title}】的要点有哪些？", "answer": q_items,
                "explain": f"出自知识点：{kp_title}", "tags": [kp_title],
                "id": hashlib.md5(f"qa:{chapter}:{kp_title}".encode()).hexdigest()[:12],
            })
    return cards

all_cards = []
scanned = scan_files()
if scanned:
    for path, chapter, ch_title in scanned:
        text = open(path).read()
        choice = extract_choice_cards(text, chapter, ch_title)
        qa = make_qa_cards(text, chapter, ch_title)
        all_cards += choice + qa
        print(f"{chapter} {ch_title}: 选择题 {len(choice)} + 问答 {len(qa)}")
else:
    # 无讲义时生成内置示例卡，保证开箱即有内容可体验
    all_cards = demo_cards()
    print("[提示] 未找到讲义，已生成 4 张示例卡片（用 --demo 或放入 raw/ 后重新运行）")

from collections import Counter
print(f"\n总计: {len(all_cards)} 张卡", Counter(c["type"] for c in all_cards))

# 按章节分割保存：每章一个 JSON + 总索引
chap_dir = os.path.join(OUT, 'chapters')
os.makedirs(chap_dir, exist_ok=True)
by_chapter = {}
for c in all_cards:
    by_chapter.setdefault(c["chapter"], []).append(c)

index = []
for path, chapter, ch_title in scanned:
    cards = by_chapter.get(chapter, [])
    fname = f"{chapter}{ch_title}.json"
    with open(os.path.join(chap_dir, fname), 'w') as f:
        json.dump(cards, f, ensure_ascii=False)
    index.append({
        "chapter": chapter, "chapter_title": ch_title,
        "file": f"chapters/{fname}",
        "count": len(cards),
        "choice": sum(1 for c in cards if c["type"] == "choice"),
        "qa": sum(1 for c in cards if c["type"] == "qa"),
    })
    print(f"  {fname}: {len(cards)} 张")

with open(os.path.join(OUT, 'index.json'), 'w') as f:
    json.dump(index, f, ensure_ascii=False, indent=1)
print(f"已保存总索引 {OUT}/index.json")
# 抽样选择题
shown = 0
for c in all_cards:
    if c["type"] == "choice" and shown < 2:
        print("\n--- 选择题样例 ---")
        print(c["question"][:200])
        print("答案:", c["answer"])
        print("解析:", c["explain"][:80])
        shown += 1
