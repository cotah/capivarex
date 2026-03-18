"""
Upload route — Sprint 6A
POST /api/webapp/upload
"""

from __future__ import annotations

import base64
import mimetypes
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from loguru import logger

from api.middleware.rate_limit import limiter
from api.middleware.webapp_auth import verify_webapp_user
from api.routes._helpers import _get_service_or_503

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None

router = APIRouter()

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB

ALLOWED_MIME_PREFIXES = ("image/", "audio/", "video/")
ALLOWED_MIME_EXACT = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
)

MediaType = Literal["image", "audio", "pdf", "document", "video", "text", "unknown"]


def _media_type(content_type: str, filename: str) -> MediaType:
    ct = (content_type or "").lower()
    ext = Path(filename).suffix.lower()
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("audio/") or ext in (
        ".mp3",
        ".wav",
        ".ogg",
        ".m4a",
        ".webm",
        ".flac",
    ):
        return "audio"
    if ct.startswith("video/") or ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
        return "video"
    if ct == "application/pdf" or ext == ".pdf":
        return "pdf"
    if ext in (".docx", ".doc") or "word" in ct:
        return "document"
    if ct.startswith("text/") or ext in (".txt", ".md"):
        return "text"
    return "unknown"


def _validate_file(content_type: str, filename: str, size: int) -> None:
    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, detail="File too large. Maximum size is 25 MB."
        )
    ct = (content_type or "").lower()
    ext = Path(filename).suffix.lower()
    allowed = (
        any(ct.startswith(p) for p in ALLOWED_MIME_PREFIXES) or ct in ALLOWED_MIME_EXACT
    )
    allowed_ext = ext in (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".heic",
        ".mp3",
        ".wav",
        ".ogg",
        ".m4a",
        ".webm",
        ".flac",
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".pdf",
        ".docx",
        ".doc",
        ".txt",
        ".md",
    )
    if not (allowed or allowed_ext):
        raise HTTPException(
            status_code=415, detail=f"Unsupported file type: {content_type or ext}."
        )


async def _process_image(path: str) -> tuple[str, str]:
    try:
        if genai is None:
            raise RuntimeError("google-genai not installed")

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        client = genai.Client(api_key=api_key)
        with open(path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()
        ext = Path(path).suffix.lower().lstrip(".")
        mime = (
            f"image/{ext}"
            if ext in ("jpg", "jpeg", "png", "gif", "webp")
            else "image/jpeg"
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                genai_types.Part.from_bytes(
                    data=base64.b64decode(image_data), mime_type=mime
                ),
                "Describe this image in detail. Include: what you see, any text present, "
                "colors, objects, people, context.",
            ],
        )
        text = response.text or ""
        preview = text[:200] + ("..." if len(text) > 200 else "")
        logger.info("Upload: Gemini Vision analysed image — {} chars", len(text))
        return text, preview
    except Exception as e:
        logger.warning("Upload: Gemini Vision failed ({}), returning placeholder", e)
        filename = Path(path).name
        text = f"[Imagem recebida: {filename}. Responde à pergunta do utilizador sobre esta imagem.]"
        preview = f"Imagem: {filename}"
        return text, preview


async def _process_audio(path: str) -> tuple[str, str]:
    try:
        whisper = _get_service_or_503("whisper", "Whisper STT")
        result = await whisper.speech_to_text(path, language="pt")
        text = result.get("text", "")
        preview = text[:200] + ("..." if len(text) > 200 else "")
        logger.info("Upload: Whisper transcribed audio — {} chars", len(text))
        return text, preview
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Upload: Whisper failed ({})", e)
        filename = Path(path).name
        text = f"[Audio uploaded: {filename}]"
        return text, text


async def _process_pdf(path: str) -> tuple[str, str]:
    try:
        from services.media.pdf_service import extract_pdf

        result = extract_pdf(path)
        text = result["text"]
        preview = result["preview"]
        return text, preview
    except Exception as e:
        logger.warning("Upload: PDF extraction failed ({})", e)
        filename = Path(path).name
        text = f"[PDF uploaded: {filename} — could not extract text]"
        return text, text


async def _process_docx(path: str) -> tuple[str, str]:
    try:
        from docx import Document

        doc = Document(path)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs)
        if not text.strip():
            text = "[Document uploaded — no extractable text found]"
        preview = "Document: " + text[:150].replace("\n", " ") + "..."
        logger.info("Upload: DOCX extracted {} chars", len(text))
        return text, preview
    except ImportError:
        filename = Path(path).name
        text = f"[Document uploaded: {filename}]"
        return text, text
    except Exception as e:
        logger.warning("Upload: DOCX extraction failed ({})", e)
        filename = Path(path).name
        text = f"[Document uploaded: {filename} — could not extract text]"
        return text, text


async def _process_video(path: str) -> tuple[str, str]:
    audio_path = path + "_audio.mp3"
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-i",
                path,
                "-vn",
                "-acodec",
                "mp3",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-y",
                audio_path,
            ],
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[:200]}")
        text, preview = await _process_audio(audio_path)
        filename = Path(path).name
        full_text = f"[Video: {filename}]\n\nTranscription:\n{text}"
        return full_text, f"Video transcription: {preview}"
    except FileNotFoundError:
        logger.warning("Upload: ffmpeg not found, returning placeholder")
        filename = Path(path).name
        text = f"[Video uploaded: {filename} — ffmpeg not available for transcription]"
        return text, text
    except Exception as e:
        logger.warning("Upload: video processing failed ({})", e)
        filename = Path(path).name
        text = f"[Video uploaded: {filename} — could not extract audio]"
        return text, text
    finally:
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass


async def _process_text(path: str) -> tuple[str, str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        preview = text[:200] + ("..." if len(text) > 200 else "")
        return text, preview
    except Exception as e:
        logger.warning("Upload: text read failed ({})", e)
        filename = Path(path).name
        text = f"[Text file uploaded: {filename}]"
        return text, text


@router.post("/upload")
@limiter.limit("20/minute")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(verify_webapp_user),
):
    content = await file.read()
    size = len(content)
    filename = file.filename or "upload"
    content_type = (
        file.content_type
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )

    _validate_file(content_type, filename, size)

    media = _media_type(content_type, filename)
    file_id = str(uuid.uuid4())

    logger.info(
        "Upload: user={} file='{}' type={} size={} media={}",
        user_id[:8],
        filename,
        content_type,
        size,
        media,
    )

    temp_dir = "temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"upload_{file_id}_{filename}")

    UPLOAD_PERSIST_DIR = "/tmp/capivarex_uploads"
    os.makedirs(UPLOAD_PERSIST_DIR, exist_ok=True)

    try:
        with open(temp_path, "wb") as f_out:
            f_out.write(content)

        if media == "image":
            # Persist image for GPT-4o vision in webapp.py
            ext = os.path.splitext(filename)[1].lower() or ".jpg"
            persist_path = os.path.join(UPLOAD_PERSIST_DIR, f"{file_id}{ext}")
            shutil.copy2(temp_path, persist_path)
            logger.info("Upload: persisted image {} → {}", file_id, persist_path)
            extracted_text, preview = await _process_image(temp_path)
        elif media == "audio":
            extracted_text, preview = await _process_audio(temp_path)
        elif media == "pdf":
            extracted_text, preview = await _process_pdf(temp_path)
        elif media == "document":
            extracted_text, preview = await _process_docx(temp_path)
        elif media == "video":
            extracted_text, preview = await _process_video(temp_path)
        elif media == "text":
            extracted_text, preview = await _process_text(temp_path)
        else:
            extracted_text = f"[File uploaded: {filename}]"
            preview = extracted_text
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

    logger.info(
        "Upload: user={} file_id={} extracted={} chars",
        user_id[:8],
        file_id[:8],
        len(extracted_text),
    )

    return {
        "file_id": file_id,
        "filename": filename,
        "content_type": content_type,
        "size_bytes": size,
        "media_type": media,
        "preview": preview,
        "extracted_text": extracted_text,
    }
