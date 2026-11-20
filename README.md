# px4-rag-chatbot

PX4 Autopilot 문서를 한국어로 질문하면 근거 문서 링크와 함께 답해 주는 AWS 기반 RAG 챗봇 (클라우드 아키텍처 수업 과제).

## 구성
- 서울 리전(ap-northeast-2)
- 임베딩: Amazon Titan Text Embeddings V2
- 벡터 저장소: Amazon S3 Vectors
- 생성 모델: Claude Sonnet 4.6 (Amazon Bedrock)
- 백엔드: AWS Lambda + API Gateway

## 현재 상태 (2주차)
- `lambda/hello`: API Gateway 연결 테스트용 함수
- `lambda/smoketest`: Titan 임베딩 → S3 Vectors 저장·검색 확인용 함수
