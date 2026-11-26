import json, time, boto3
from botocore.config import Config

REGION = "ap-northeast-2"
DOCS_BUCKET = "px4-rag-docs-jhw"
CHUNKS_KEY = "chunks/v1.17.0/chunks.jsonl"
VEC_BUCKET = "px4-rag-vectors-jhw"
INDEX = "px4-docs"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
BATCH = 50

cfg = Config(region_name=REGION, retries={"max_attempts": 10, "mode": "adaptive"}, read_timeout=60)
s3 = boto3.client("s3", config=cfg)
bedrock = boto3.client("bedrock-runtime", config=cfg)
s3v = boto3.client("s3vectors", config=cfg)


def embed(text):
    for attempt in range(8):
        try:
            r = bedrock.invoke_model(
                modelId=EMBED_MODEL,
                body=json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}),
            )
            return json.loads(r["body"].read())["embedding"]
        except Exception as e:
            if "Throttling" in str(e) and attempt < 7:
                time.sleep(3 * (attempt + 1))
                continue
            raise


def stored_keys():
    keys, token = set(), None
    while True:
        kw = dict(vectorBucketName=VEC_BUCKET, indexName=INDEX, maxResults=1000)
        if token:
            kw["nextToken"] = token
        res = s3v.list_vectors(**kw)
        for v in res.get("vectors", []):
            keys.add(v["key"])
        token = res.get("nextToken")
        if not token:
            return keys


def put(batch):
    s3v.put_vectors(vectorBucketName=VEC_BUCKET, indexName=INDEX, vectors=batch)


def main():
    obj = s3.get_object(Bucket=DOCS_BUCKET, Key=CHUNKS_KEY)
    text = obj["Body"].read().decode("utf-8")
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    have = stored_keys()
    missing = [r for r in rows if r["id"] not in have]
    print("전체 조각:", len(rows))
    print("이미 저장된 벡터:", len(have))
    print("누락:", len(missing), flush=True)
    t0 = time.time()
    batch, done, failed = [], 0, []
    for n, row in enumerate(missing, 1):
        try:
            vec = embed(row["text"])
        except Exception as e:
            failed.append((row["id"], str(e)[:200]))
            continue
        batch.append({
            "key": row["id"],
            "data": {"float32": vec},
            "metadata": {
                "text": row["text"],
                "url": row["url"],
                "title": row["title"][:200],
                "section": row["section"][:300],
                "doc": row["doc"],
            },
        })
        if len(batch) >= BATCH:
            put(batch)
            done += len(batch)
            batch = []
            print("진행: %d/%d (%d초)" % (n, len(missing), time.time() - t0), flush=True)
    if batch:
        put(batch)
        done += len(batch)
    print("=== 결과 ===")
    print("이번에 채운 벡터:", done)
    print("실패:", len(failed))
    for rid, err in failed[:5]:
        print("   -", rid, err)
    total = len(stored_keys())
    print("저장된 벡터 총수:", total, "/", len(rows))
    print("전체 완료 여부:", "완료" if total == len(rows) else "미완료(같은 명령을 다시 실행하세요)")
    print("소요 시간: %d초" % (time.time() - t0))


main()
