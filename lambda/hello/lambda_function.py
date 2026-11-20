import json


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(
            {"message": "PX4 RAG 챗봇 테스트 API 동작 중"},
            ensure_ascii=False,
        ),
    }
