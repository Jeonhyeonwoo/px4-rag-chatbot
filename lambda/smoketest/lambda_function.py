import json
import boto3

REGION = "ap-northeast-2"
BUCKET = "px4-rag-vectors-jhw"
INDEX = "px4-docs"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
s3v = boto3.client("s3vectors", region_name=REGION)


def embed(text):
    r = bedrock.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}),
    )
    return json.loads(r["body"].read())["embedding"]


def lambda_handler(event, context):
    text = "PX4 is an open source flight control software for drones."
    s3v.put_vectors(
        vectorBucketName=BUCKET,
        indexName=INDEX,
        vectors=[{
            "key": "smoke-1",
            "data": {"float32": embed(text)},
            "metadata": {"text": text, "source": "smoke-test"},
        }],
    )
    res = s3v.query_vectors(
        vectorBucketName=BUCKET,
        indexName=INDEX,
        queryVector={"float32": embed("What is PX4?")},
        topK=1,
        returnMetadata=True,
        returnDistance=True,
    )
    return {
        "statusCode": 200,
        "body": json.dumps(res["vectors"], ensure_ascii=False, default=str),
    }
