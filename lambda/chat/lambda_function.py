import base64
import json
import os
import re
import time

import boto3
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
VEC_BUCKET = os.environ.get("VEC_BUCKET", "px4-rag-vectors-jhw")
VEC_INDEX = os.environ.get("VEC_INDEX", "px4-docs")
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
GEN_MODEL_ID = os.environ.get("GEN_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
QUERY_MODEL_ID = os.environ.get("QUERY_MODEL_ID", GEN_MODEL_ID)
TOP_K = int(os.environ.get("TOP_K", "6"))
THRESHOLD = float(os.environ.get("THRESHOLD", "0.6"))  # cosine distance: smaller = more similar
MAX_SOURCES = 4
REFUSAL = "죄송합니다. PX4 문서에서 이 질문에 대한 근거를 찾지 못했습니다."

cfg = Config(region_name=REGION, retries={"max_attempts": 5, "mode": "adaptive"},
             connect_timeout=5, read_timeout=25)
bedrock = boto3.client("bedrock-runtime", config=cfg)
s3v = boto3.client("s3vectors", config=cfg)

QUERY_SYSTEM = (
    "You convert a user's question about the PX4 Autopilot (drone flight controller software) "
    "into one concise English search query for a documentation search engine. "
    "Use PX4 terminology. Keep parameter names, commands, board and model names exactly as written. "
    "If the question is already in English, keep it. Output only the query, nothing else."
)

ANSWER_SYSTEM = (
    "You are a Korean-language assistant for the PX4 Autopilot v1.17 documentation. "
    "Answer ONLY with information contained in the numbered documentation excerpts provided by the user. "
    "If the excerpts do not contain the answer, reply with exactly: NO_ANSWER\n"
    "Rules:\n"
    "- Write the answer in Korean. Keep English technical terms, parameter names, commands and mode names as they are.\n"
    "- Be concise and practical. Use a numbered list for procedures.\n"
    "- After each statement, cite the excerpt number(s) it came from, like [1] or [2][3].\n"
    "- Never invent parameter names, values or steps that are not in the excerpts."
)


def claude(model_id, system, user, max_tokens, temperature=0.0):
    r = bedrock.converse(
        modelId=model_id,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )
    return r["output"]["message"]["content"][0]["text"].strip()


def embed(text):
    for attempt in range(3):
        try:
            r = bedrock.invoke_model(
                modelId=EMBED_MODEL_ID,
                body=json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}),
            )
            return json.loads(r["body"].read())["embedding"]
        except Exception as e:
            if "Throttling" in str(e) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise


def parse_question(event):
    if not isinstance(event, dict):
        return ""
    if "question" in event:
        return str(event["question"])
    body = event.get("body")
    if not body:
        return ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    try:
        return str(json.loads(body).get("question", ""))
    except Exception:
        return ""


def respond(status, payload):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(payload, ensure_ascii=False),
    }


def to_search_query(question):
    q = claude(QUERY_MODEL_ID, QUERY_SYSTEM, question, 80)
    return q.splitlines()[0].strip() if q else question


def search(query_en):
    res = s3v.query_vectors(
        vectorBucketName=VEC_BUCKET, indexName=VEC_INDEX,
        queryVector={"float32": embed(query_en)}, topK=TOP_K,
        returnMetadata=True, returnDistance=True,
    )
    return res.get("vectors", [])


def build_prompt(question, hits):
    parts = []
    for i, h in enumerate(hits, 1):
        md = h["metadata"]
        parts.append("[%d] %s\n%s" % (i, md.get("url", ""), md.get("text", "")[:2500]))
    return "문서 발췌:\n\n" + "\n\n".join(parts) + "\n\n질문: " + question


def pick_sources(answer, hits):
    cited = []
    for m in re.finditer(r"\[(\d+)\]", answer):
        n = int(m.group(1))
        if 1 <= n <= len(hits) and n not in cited:
            cited.append(n)
    order = cited if cited else list(range(1, len(hits) + 1))
    sources, seen = [], set()
    for n in order:
        md = hits[n - 1]["metadata"]
        url = md.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        sources.append({
            "n": n,
            "title": md.get("title", ""),
            "section": md.get("section", ""),
            "url": url,
            "distance": round(hits[n - 1]["distance"], 3),
        })
        if len(sources) >= MAX_SOURCES:
            break
    return sources


def lambda_handler(event, context):
    t0 = time.time()
    question = parse_question(event).strip()
    if not question:
        return respond(400, {"error": "question 값이 비어 있습니다."})
    question = question[:500]

    search_query = to_search_query(question)
    hits = search(search_query)
    best = round(hits[0]["distance"], 3) if hits else None
    good = [h for h in hits if h["distance"] <= THRESHOLD]

    answer, sources, refused = REFUSAL, [], True
    if good:
        raw = claude(GEN_MODEL_ID, ANSWER_SYSTEM, build_prompt(question, good), 900, 0.2)
        if "NO_ANSWER" not in raw:
            answer, sources, refused = raw, pick_sources(raw, good), False

    payload = {
        "answer": answer,
        "sources": sources,
        "refused": refused,
        "search_query": search_query,
        "best_distance": best,
    }
    print(json.dumps({"question": question, "search_query": search_query, "best_distance": best,
                      "used_chunks": len(good), "refused": refused,
                      "latency_ms": int((time.time() - t0) * 1000)}, ensure_ascii=False))
    return respond(200, payload)