import json, time, boto3

lam = boto3.client("lambda", region_name="ap-northeast-2")

QUESTIONS = [
    "컴퍼스 보정은 어떻게 하나요?",
    "멀티콥터의 포지션 모드가 뭔가요?",
    "배터리 페일세이프는 어떻게 설정하나요?",
    "QGroundControl로 PX4 펌웨어를 설치하는 방법을 알려 주세요.",
    "VTOL 전환(transition)은 어떻게 동작하나요?",
    "PX4 v1.17에서 새로 추가된 기능은 뭐가 있나요?",
    "MPC_XY_VEL_MAX 파라미터의 기본값이 뭔가요?",
    "오늘 서울 날씨 알려 주세요.",
    "김치찌개 맛있게 끓이는 법 알려 주세요.",
]


def main():
    results = []
    for i, q in enumerate(QUESTIONS, 1):
        t0 = time.time()
        r = lam.invoke(
            FunctionName="px4-rag-chat",
            Payload=json.dumps({"question": q}, ensure_ascii=False).encode("utf-8"),
        )
        res = json.loads(r["Payload"].read())
        sec = time.time() - t0
        print("[%d] %s" % (i, q))
        if "body" not in res:
            print("    오류:", str(res.get("errorMessage", res))[:300])
            continue
        b = json.loads(res["body"])
        results.append({"question": q, "latency_sec": round(sec, 1), **b})
        print("    거절: %s | 최소 거리: %s | %.1f초" % (b.get("refused"), b.get("best_distance"), sec))
        print("    검색어:", b.get("search_query"))
        print("    답변:", b.get("answer", "").replace("\n", " ")[:110])
        for s in b.get("sources", []):
            print("    출처 [%s] %s" % (s["n"], s["url"]))
    with open("/home/cloudshell-user/ask_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("=== 요약 ===")
    print("답변:", sum(1 for x in results if not x["refused"]), "| 거절:", sum(1 for x in results if x["refused"]))
    print("저장: ~/ask_results.json")


main()
