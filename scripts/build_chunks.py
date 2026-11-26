import json, os, re, statistics

ROOT = os.path.expanduser("~/PX4-Autopilot/docs/en")
VERSION = "v1.17.0"
BASE_URL = "https://docs.px4.io/v1.17/en/"
OUT_DIR = os.path.expanduser("~/chunks/" + VERSION)
INCLUDE_LINES = [(1, 430), (881, 10**9)]   # SUMMARY.md line ranges to include
MAX_BYTES = 80000                          # skip huge generated files
MAX_CHARS = 2400                           # ~600 tokens
MIN_CHARS = 250
OVERLAP = 250
FENCE = "`" * 3

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)")
HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
TAGS = "a|b|br|div|span|p|img|video|iframe|table|thead|tbody|tr|td|th|ul|ol|li|strong|em|sup|sub|details|summary|center|font|kbd"
TAG_RE = re.compile(r"</?(?:%s)\b[^>]*>" % TAGS, re.I)


def parse_summary():
    files, seen = [], set()
    with open(os.path.join(ROOT, "SUMMARY.md"), encoding="utf-8") as f:
        for no, line in enumerate(f, 1):
            if not any(a <= no <= b for a, b in INCLUDE_LINES):
                continue
            for m in LINK.finditer(line):
                target = m.group(1).split("#")[0]
                if not target.endswith(".md") or target.startswith("http"):
                    continue
                target = os.path.normpath(target)
                if target not in seen and os.path.exists(os.path.join(ROOT, target)):
                    seen.add(target)
                    files.append(target)
    return files


def clean(text):
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<(script|style)\b.*?</\1>", "", text, flags=re.S | re.I)
    out, in_code = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith(FENCE):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
        s = re.sub(r"\[\s*\]\([^)]*\)", "", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
        m = re.match(r"^:::\s*(\w+)?\s*(.*)$", s)
        if m:
            kind, rest = m.group(1), m.group(2)
            s = (kind.upper() + ": " + rest).strip() if kind else ""
        s = TAG_RE.sub("", s)
        out.append(s)
    return "\n".join(out)


def doc_title(text, rel):
    for line in text.split("\n"):
        m = re.match(r"^#\s+(.*)", line)
        if m:
            return m.group(1).strip()
    return rel


def split_sections(text, fallback_title):
    secs, stack, cur = [], {}, []
    path = fallback_title
    in_code = False

    def flush():
        body = "\n".join(cur).strip()
        if body:
            secs.append((path, body))

    for line in text.split("\n"):
        if line.lstrip().startswith(FENCE):
            in_code = not in_code
            cur.append(line)
            continue
        m = None if in_code else HEAD.match(line)
        if m and len(m.group(1)) <= 3:
            flush()
            del cur[:]
            lvl, title = len(m.group(1)), m.group(2).strip()
            stack = {k: v for k, v in stack.items() if k < lvl}
            stack[lvl] = title
            path = " > ".join(stack[k] for k in sorted(stack))
        else:
            cur.append(line)
    flush()
    return secs


def hard_split(p):
    pieces, cur, n = [], [], 0
    for line in p.split("\n"):
        while len(line) > MAX_CHARS:
            if cur:
                pieces.append("\n".join(cur)); cur, n = [], 0
            pieces.append(line[:MAX_CHARS]); line = line[MAX_CHARS:]
        if cur and n + len(line) + 1 > MAX_CHARS:
            pieces.append("\n".join(cur)); cur, n = [], 0
        cur.append(line); n += len(line) + 1
    if cur:
        pieces.append("\n".join(cur))
    return pieces


def pack(body):
    if len(body) <= MAX_CHARS:
        return [body]
    chunks, cur, curlen = [], [], 0
    for p in re.split(r"\n\s*\n", body):
        for piece in (hard_split(p) if len(p) > MAX_CHARS else [p]):
            if cur and curlen + len(piece) + 2 > MAX_CHARS:
                chunks.append("\n\n".join(cur))
                tail, tl = [], 0
                for q in reversed(cur):
                    if tl + len(q) > OVERLAP:
                        break
                    tail.insert(0, q); tl += len(q)
                cur, curlen = tail, tl
            cur.append(piece); curlen += len(piece) + 2
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def merge_small(items):
    merged = []
    for path, text in items:
        if merged and len(merged[-1][1]) < MIN_CHARS:
            p0, t0 = merged[-1]
            add = text if path == p0 else path + "\n" + text
            merged[-1] = (p0, t0 + "\n\n" + add)
        else:
            merged.append((path, text))
    return merged


def url_for(rel):
    p = rel[:-3]
    if p == "index" or p.endswith("/index"):
        return BASE_URL + p[:-5]
    return BASE_URL + p + ".html"


def main():
    files = parse_summary()
    os.makedirs(OUT_DIR, exist_ok=True)
    excluded, records, per_doc = [], [], {}
    for rel in files:
        full = os.path.join(ROOT, rel)
        size = os.path.getsize(full)
        if size > MAX_BYTES:
            excluded.append((rel, size))
            continue
        with open(full, encoding="utf-8") as f:
            text = clean(f.read())
        title = doc_title(text, rel)
        items = []
        for path, body in split_sections(text, title):
            for piece in pack(body):
                items.append((path, piece))
        url, n = url_for(rel), 0
        for path, piece in merge_small(items):
            piece = piece.strip()
            if len(piece) < 40:
                continue
            records.append({
                "id": "%s#%03d" % (rel, n),
                "doc": rel,
                "title": title,
                "section": path,
                "url": url,
                "text": "[%s]\n%s" % (path, piece),
            })
            n += 1
        per_doc[rel] = n
    out = os.path.join(OUT_DIR, "chunks.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    lens = [len(r["text"]) for r in records]
    print("=== 결과 ===")
    print("목차 범위 문서 수:", len(files))
    print("크기 때문에 제외:", len(excluded))
    for rel, size in excluded:
        print("   -", rel, size // 1024, "KB")
    print("사용 문서 수:", len([k for k, v in per_doc.items() if v > 0]))
    print("조각 수:", len(records))
    print("조각 길이(글자) 평균/중앙값/최대:", int(statistics.mean(lens)), int(statistics.median(lens)), max(lens))
    print("대략 전체 토큰(글자/4):", sum(lens) // 4)
    print("조각이 가장 많은 문서 5개:")
    for rel, n in sorted(per_doc.items(), key=lambda x: -x[1])[:5]:
        print("   -", rel, n)
    print("저장 위치:", out)
    for r in (records[0], records[len(records) // 2]):
        print("--- 샘플 %s ---" % r["id"])
        print(r["url"])
        print(r["text"][:500])


main()
