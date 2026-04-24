"""AWS backend: Aurora Data API + Secrets Manager + SageMaker + S3 Vectors."""
from __future__ import annotations

import json
import os
from typing import Any

import boto3

from .interface import Backend, DB, Secrets, Embedder, Vectors


def _aws_region() -> str:
    return os.environ.get("AWS_REGION", os.environ.get("AWS_REGION_NAME", "us-east-1"))


class AuroraDB(DB):
    """rds-data:ExecuteStatement — identical bind-param style (`:name`) as SQLite."""

    def __init__(self):
        self.cluster_arn = os.environ["AURORA_CLUSTER_ARN"]
        self.secret_arn = os.environ["AURORA_SECRET_ARN"]
        self.database = os.environ.get("AURORA_DATABASE", "devforge")
        self.client = boto3.client("rds-data", region_name=_aws_region())

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        parameters = [
            {"name": k, "value": _sql_value(v)} for k, v in (params or {}).items()
        ]
        resp = self.client.execute_statement(
            resourceArn=self.cluster_arn,
            secretArn=self.secret_arn,
            database=self.database,
            sql=sql,
            parameters=parameters,
            includeResultMetadata=True,
        )
        return _rows(resp)


def _sql_value(v: Any) -> dict:
    if v is None:
        return {"isNull": True}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"longValue": v}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def _rows(resp: dict) -> list[dict]:
    cols = [m["name"] for m in resp.get("columnMetadata", [])]
    out: list[dict] = []
    for record in resp.get("records", []):
        row: dict[str, Any] = {}
        for i, cell in enumerate(record):
            if cell.get("isNull"):
                row[cols[i]] = None
            elif "stringValue" in cell:
                row[cols[i]] = cell["stringValue"]
            elif "longValue" in cell:
                row[cols[i]] = cell["longValue"]
            elif "doubleValue" in cell:
                row[cols[i]] = cell["doubleValue"]
            elif "booleanValue" in cell:
                row[cols[i]] = cell["booleanValue"]
            else:
                row[cols[i]] = next(iter(cell.values()))
        out.append(row)
    return out


class SecretsManagerSecrets(Secrets):
    """Secrets Manager — short names map to 'devforge/<name>' ids."""

    _PREFIX = "devforge/"

    def __init__(self):
        self.client = boto3.client("secretsmanager", region_name=_aws_region())

    def get(self, name: str) -> str:
        secret_id = name if name.startswith("arn:") or "/" in name else f"{self._PREFIX}{name}"
        resp = self.client.get_secret_value(SecretId=secret_id)
        return resp["SecretString"]


class SageMakerEmbedder(Embedder):
    def __init__(self):
        self.endpoint_name = os.environ.get("SAGEMAKER_ENDPOINT", "devforge-embedding-endpoint")
        self.client = boto3.client("sagemaker-runtime", region_name=_aws_region())

    def embed(self, text: str) -> list[float]:
        resp = self.client.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="application/json",
            Body=json.dumps({"inputs": text}),
        )
        result = json.loads(resp["Body"].read().decode())
        # HuggingFace feature-extraction pipeline returns [[[embedding]]]
        while isinstance(result, list) and len(result) > 0 and isinstance(result[0], list):
            result = result[0]
        return result  # type: ignore[return-value]


class S3VectorsStore(Vectors):
    def __init__(self):
        self.bucket = os.environ["VECTOR_BUCKET"]
        self.client = boto3.client("s3vectors", region_name=_aws_region())

    def put(self, index: str, key: str, vector: list[float], metadata: dict) -> None:
        self.client.put_vectors(
            vectorBucketName=self.bucket,
            indexName=index,
            vectors=[{
                "key": key,
                "data": {"float32": vector},
                "metadata": metadata,
            }],
        )

    def put_many(self, index: str, items: list[dict]) -> None:
        # S3 Vectors put_vectors supports up to 500 per call. Chunk conservatively.
        batch = []
        for it in items:
            batch.append({
                "key": it["key"],
                "data": {"float32": it["vector"]},
                "metadata": it["metadata"],
            })
            if len(batch) >= 100:
                self.client.put_vectors(
                    vectorBucketName=self.bucket, indexName=index, vectors=batch
                )
                batch = []
        if batch:
            self.client.put_vectors(
                vectorBucketName=self.bucket, indexName=index, vectors=batch
            )

    def query(self, index: str, vector: list[float], k: int = 8) -> list[dict]:
        resp = self.client.query_vectors(
            vectorBucketName=self.bucket,
            indexName=index,
            queryVector={"float32": vector},
            topK=k,
            returnMetadata=True,
            returnDistance=True,
        )
        return [
            {
                "key": r["key"],
                "score": r.get("distance"),
                "metadata": r.get("metadata", {}),
                "text": r.get("metadata", {}).get("text", ""),
            }
            for r in resp.get("vectors", [])
        ]


class AWSBackend(Backend):
    def __init__(self):
        self.db = AuroraDB()
        self.secrets = SecretsManagerSecrets()
        self.embedder = SageMakerEmbedder()
        self.vectors = S3VectorsStore()
