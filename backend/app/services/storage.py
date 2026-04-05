from urllib.parse import quote

from app.core.config import settings


def build_public_asset_url(key: str) -> str:
    normalized = quote(key.lstrip('/'))
    return f'https://{settings.s3_bucket}.s3.{settings.s3_region}.amazonaws.com/{normalized}'
