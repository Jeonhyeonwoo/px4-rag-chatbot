import json, os, sys, time, boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor

REGION = "ap-northeast-2"
DOCS_BUCKET = "px4-rag-docs-jhw"
CHUNKS_KEY = "chunks/v1.17.0/chunks.jsonl"
VEC_BUCKET = "px4-rag-vectors-jhw"
INDEX = "px4-docs"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
WORKERS = 6
BATCH = 100
PROGRESS = os.path.expanduser("~/embed_progress.txt")

cfg = Config(region_name=REGION, retries={"max_attempts": 10, "mode": "adaptive"}, read_timeout=60)
s3 = boto3.client("s3", config=cfg)
bedrock = boto3.client("bedrock-runtime", config=cfg)
s3v = boto3.client("s3vectors", config=cfg)


def embed(text):
    r = bedrock.invoke_model(
        modelId=EMBED_MODEL,
        body=json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}),
    )
    return json.loads(r["body"].read())["embedding"]


def load_chunks(limit):
    obj = s3.get_object(Bucket=DOCS_BUCKET, Key=CHUNKS_KEY)
    text = obj["Body"].read().decode("utf-8")
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if limit:
        rows = rows[:: max(1, len(rows) // limit)][:limit]
    return rows


def to_vector(row):
    return {
        "key": row["id"],
        "data": {"float32": embed(row["text"])},
        "metadata": {
            "text": row["text"],
            "url": row["url"],
            "title": row["title"][:200],
            "section": row["section"][:300],
            "doc": row["doc"],
        },
    }


def safe(row):
    try:
        return row["id"], to_vector(row), None
    except Exception as e:
        return row["id"], None, str(e)[:300]


def read_progress():
    try:
        with open(PROGRESS) as f:
            return int(f.read().strip())
    except Exception:
        return 0


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    rows = load_chunks(limit)
    start = 0 if limit else read_progress()
    print("대상 조각 수:", len(rows), "/ 시작 위치:", start, flush=True)
    t0 = time.time()
    done, failed, ok_prefix = 0, [], True
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i in range(start, len(rows), BATCH):
            part = rows[i:i + BATCH]
            batch, bad = [], 0
            for rid, vec, err in ex.map(safe, part):
                if err:
                    failed.append((rid, err))
                    bad += 1
                else:
                    batch.append(vec)
            if batch:
                try:
                    s3v.put_vectors(vectorBucketName=VEC_BUCKET, indexName=INDEX, vectors=batch)
                    done += len(batch)
                except Exception as e:
                    print("저장 오류:", str(e)[:400], flush=True)
                    failed.extend((v["key"], "put_vectors 실패") for v in batch)
                    bad += len(batch)
            if bad:
                ok_prefix = False
            if ok_prefix and not limit:
                with open(PROGRESS, "w") as f:
                    f.write(str(i + len(part)))
            print("진행: %d/%d (%d초)" % (i + len(part), len(rows), time.time() - t0), flush=True)
    print("=== 결과 ===")
    print("이번 실행에서 저장 성공:", done)
    print("실패:", len(failed))
    for rid, err in failed[:5]:
        print("   -", rid, err)
    print("소요 시간: %d초" % (time.time() - t0))
    if not limit:
        print("전체 완료 여부:", "완료" if ok_prefix else "미완료(같은 명령을 다시 실행하세요)")
    q = "How do I calibrate the compass?"
    res = s3v.query_vectors(
        vectorBucketName=VEC_BUCKET, indexName=INDEX,
        queryVector={"float32": embed(q)}, topK=3,
        returnMetadata=True, returnDistance=True,
    )
    print("검색 확인:", q)
    for v in res["vectors"]:
        m = v["metadata"]
        print("  %.3f  %s | %s" % (v["distance"], m["section"], m["url"]))


main()
