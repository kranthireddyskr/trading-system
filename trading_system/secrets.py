from __future__ import annotations

import json
import os
from pathlib import Path


def resolve_secret(name, default=""):
    value = os.getenv(name)
    if value:
        return value

    secrets_file = os.getenv("TRADING_SECRET_FILE")
    if secrets_file and Path(secrets_file).exists():
        payload = json.loads(Path(secrets_file).read_text(encoding="utf-8"))
        if name in payload:
            return payload[name]

    secret_id = os.getenv("AWS_SECRETS_MANAGER_SECRET_ID")
    if secret_id:
        try:
            import boto3
        except ImportError:
            raise RuntimeError("Install boto3 to load secrets from AWS Secrets Manager.")
        client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
        response = client.get_secret_value(SecretId=secret_id)
        secret_string = response.get("SecretString", "{}")
        payload = json.loads(secret_string)
        if name in payload:
            return payload[name]

    return default
