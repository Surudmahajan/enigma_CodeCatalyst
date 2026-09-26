"""Object storage abstraction. Files never live in PostgreSQL or inside the code tree."""

from pathlib import Path
from typing import Protocol

from app.core.config import get_settings


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, base_dir: str):
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.base / key).resolve()
        if not path.is_relative_to(self.base):  # defence in depth against path traversal
            raise ValueError("Invalid storage key")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Storage:
    """S3-compatible storage (AWS S3, MinIO, Cloudflare R2...). Requires ``boto3``."""

    def __init__(self) -> None:
        import boto3  # optional dependency, imported only when configured

        settings = get_settings()
        self.bucket = settings.storage_bucket
        self.client = boto3.client("s3", endpoint_url=settings.storage_endpoint_url or None,
                                   aws_access_key_id=settings.storage_access_key,
                                   aws_secret_access_key=settings.storage_secret_key)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type,
                               ServerSideEncryption="AES256")

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        settings = get_settings()
        _storage = S3Storage() if settings.storage_backend == "s3" else LocalStorage(settings.storage_local_dir)
    return _storage
