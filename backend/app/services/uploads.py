from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

UPLOAD_DIR = Path('data') / 'uploads'


async def save_uploaded_video(file: UploadFile) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or '').suffix or '.mp4'
    target_path = UPLOAD_DIR / f'{uuid4()}{suffix}'

    with target_path.open('wb') as output:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
    await file.close()
    return str(target_path.resolve())
