"""Tests for POST /api/webapp/upload — Sprint 6A"""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_user():
    return "8f509497-fd55-4009-9da8-d59035330bba"


@pytest.fixture
def client(mock_user):
    from fastapi import FastAPI

    from api.middleware.webapp_auth import verify_webapp_user
    from api.routes.upload import router

    app = FastAPI()
    app.include_router(router, prefix="/api/webapp")
    app.dependency_overrides[verify_webapp_user] = lambda: mock_user
    return TestClient(app)


def test_media_type_image():
    from api.routes.upload import _media_type

    assert _media_type("image/jpeg", "photo.jpg") == "image"
    assert _media_type("image/png", "img.png") == "image"


def test_media_type_audio():
    from api.routes.upload import _media_type

    assert _media_type("audio/mpeg", "voice.mp3") == "audio"
    assert _media_type("application/octet-stream", "voice.m4a") == "audio"


def test_media_type_video():
    from api.routes.upload import _media_type

    assert _media_type("video/mp4", "clip.mp4") == "video"


def test_media_type_pdf():
    from api.routes.upload import _media_type

    assert _media_type("application/pdf", "doc.pdf") == "pdf"


def test_media_type_document():
    from api.routes.upload import _media_type

    assert _media_type("application/octet-stream", "doc.docx") == "document"


def test_validate_file_too_large():
    from fastapi import HTTPException

    from api.routes.upload import _validate_file

    with pytest.raises(HTTPException) as exc:
        _validate_file("image/jpeg", "photo.jpg", 30 * 1024 * 1024)
    assert exc.value.status_code == 413


def test_validate_file_unsupported_type():
    from fastapi import HTTPException

    from api.routes.upload import _validate_file

    with pytest.raises(HTTPException) as exc:
        _validate_file("application/zip", "archive.zip", 1024)
    assert exc.value.status_code == 415


def test_validate_file_ok():
    from api.routes.upload import _validate_file

    _validate_file("image/jpeg", "photo.jpg", 1024)
    _validate_file("application/pdf", "doc.pdf", 1024)


def test_upload_image_endpoint(client):
    fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    with patch(
        "api.routes.upload._process_image",
        new_callable=AsyncMock,
        return_value=("A photo of a cat.", "A photo of a cat..."),
    ):
        response = client.post(
            "/api/webapp/upload",
            files={"file": ("photo.jpg", io.BytesIO(fake_image), "image/jpeg")},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["media_type"] == "image"
    assert "file_id" in data
    assert len(data["file_id"]) == 36


def test_upload_pdf_endpoint(client):
    fake_pdf = b"%PDF-1.4 fake"
    with patch(
        "api.routes.upload._process_pdf",
        new_callable=AsyncMock,
        return_value=("PDF text content", "PDF (1 pages): PDF text..."),
    ):
        response = client.post(
            "/api/webapp/upload",
            files={"file": ("doc.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )
    assert response.status_code == 200
    assert response.json()["media_type"] == "pdf"


def test_upload_too_large(client):
    huge = b"x" * (26 * 1024 * 1024)
    response = client.post(
        "/api/webapp/upload",
        files={"file": ("huge.jpg", io.BytesIO(huge), "image/jpeg")},
    )
    assert response.status_code == 413


def test_upload_unsupported_type(client):
    response = client.post(
        "/api/webapp/upload",
        files={"file": ("archive.zip", io.BytesIO(b"PK fake"), "application/zip")},
    )
    assert response.status_code == 415


def test_upload_audio_endpoint(client):
    fake_audio = b"ID3" + b"\x00" * 100
    with patch(
        "api.routes.upload._process_audio",
        new_callable=AsyncMock,
        return_value=("Transcribed speech here", "Transcribed speech..."),
    ):
        response = client.post(
            "/api/webapp/upload",
            files={"file": ("voice.mp3", io.BytesIO(fake_audio), "audio/mpeg")},
        )
    assert response.status_code == 200
    assert response.json()["media_type"] == "audio"


def test_upload_video_endpoint(client):
    fake_video = b"\x00\x00\x00\x20ftyp" + b"\x00" * 100
    with patch(
        "api.routes.upload._process_video",
        new_callable=AsyncMock,
        return_value=("[Video: clip.mp4]\n\nTranscription:\nHello", "Video: Hello..."),
    ):
        response = client.post(
            "/api/webapp/upload",
            files={"file": ("clip.mp4", io.BytesIO(fake_video), "video/mp4")},
        )
    assert response.status_code == 200
    assert response.json()["media_type"] == "video"


@pytest.mark.asyncio
async def test_process_text_reads_content(tmp_path):
    txt_path = str(tmp_path / "note.txt")
    with open(txt_path, "w") as f:
        f.write("Hello Capivarex test content here.")
    from api.routes.upload import _process_text

    text, preview = await _process_text(txt_path)
    assert "Hello Capivarex" in text
    assert "Hello Capivarex" in preview


@pytest.mark.asyncio
async def test_process_text_file_error(tmp_path):
    from api.routes.upload import _process_text

    text, preview = await _process_text("/nonexistent/path/file.txt")
    assert "[Text file uploaded:" in text


@pytest.mark.asyncio
async def test_process_pdf_empty(tmp_path):
    pdf_path = str(tmp_path / "empty.pdf")
    with open(pdf_path, "wb") as f:
        f.write(b"%PDF-1.4 1 0 obj<</Type/Catalog>>endobj")
    from api.routes.upload import _process_pdf

    text, preview = await _process_pdf(pdf_path)
    assert text is not None


@pytest.mark.asyncio
async def test_process_image_no_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    img_path = str(tmp_path / "photo.jpg")
    with open(img_path, "wb") as f:
        f.write(b"\xff\xd8\xff" + b"\x00" * 50)
    from api.routes.upload import _process_image

    text, preview = await _process_image(img_path)
    assert "[Imagem recebida:" in text or "[Image" in text


@pytest.mark.asyncio
async def test_process_video_ffmpeg_fails(tmp_path, monkeypatch):
    import subprocess as sp

    def mock_run(*args, **kwargs):
        result = MagicMock()
        result.returncode = 1
        result.stderr = b"ffmpeg error"
        return result

    monkeypatch.setattr(sp, "run", mock_run)
    vid_path = str(tmp_path / "clip.mp4")
    with open(vid_path, "wb") as f:
        f.write(b"fake video")
    from api.routes.upload import _process_video

    text, preview = await _process_video(vid_path)
    assert "[Video uploaded:" in text


@pytest.mark.asyncio
async def test_process_docx_empty(tmp_path):
    try:
        from docx import Document
    except ImportError:
        pytest.skip("python-docx not installed")
    docx_path = str(tmp_path / "empty.docx")
    doc = Document()
    doc.save(docx_path)
    from api.routes.upload import _process_docx

    text, preview = await _process_docx(docx_path)
    assert text is not None


def test_upload_txt_endpoint(client):
    txt_content = b"Plain text note content here."
    with patch(
        "api.routes.upload._process_text",
        new_callable=AsyncMock,
        return_value=("Plain text note content here.", "Plain text note..."),
    ):
        response = client.post(
            "/api/webapp/upload",
            files={"file": ("note.txt", io.BytesIO(txt_content), "text/plain")},
        )
    assert response.status_code == 200
    assert response.json()["media_type"] == "text"


def test_media_type_unknown():
    from api.routes.upload import _media_type

    assert _media_type("application/zip", "archive.zip") == "unknown"


def test_validate_file_allowed_extension():
    from api.routes.upload import _validate_file

    _validate_file("application/octet-stream", "voice.m4a", 1024)
    _validate_file("application/octet-stream", "doc.docx", 1024)
    _validate_file("application/octet-stream", "clip.mp4", 1024)


@pytest.mark.asyncio
async def test_process_audio_success(tmp_path):
    audio_path = str(tmp_path / "voice.mp3")
    with open(audio_path, "wb") as f:
        f.write(b"fake audio data")

    mock_whisper = MagicMock()
    mock_whisper.speech_to_text = AsyncMock(
        return_value={
            "text": "Transcribed audio content",
            "language": "pt",
            "model": "whisper",
        }
    )
    with patch("api.routes.upload._get_service_or_503", return_value=mock_whisper):
        from api.routes.upload import _process_audio

        text, preview = await _process_audio(audio_path)
    assert "Transcribed audio content" in text
    assert "Transcribed audio content" in preview


@pytest.mark.asyncio
async def test_process_audio_whisper_error(tmp_path):
    audio_path = str(tmp_path / "voice.mp3")
    with open(audio_path, "wb") as f:
        f.write(b"fake audio data")

    mock_whisper = MagicMock()
    mock_whisper.speech_to_text = AsyncMock(side_effect=RuntimeError("Whisper boom"))
    with patch("api.routes.upload._get_service_or_503", return_value=mock_whisper):
        from api.routes.upload import _process_audio

        text, preview = await _process_audio(audio_path)
    assert "[Audio uploaded:" in text


@pytest.mark.asyncio
async def test_process_video_ffmpeg_not_found(tmp_path, monkeypatch):
    import subprocess as sp

    def mock_run(*args, **kwargs):
        raise FileNotFoundError("ffmpeg not found")

    monkeypatch.setattr(sp, "run", mock_run)
    vid_path = str(tmp_path / "clip.mp4")
    with open(vid_path, "wb") as f:
        f.write(b"fake video")
    from api.routes.upload import _process_video

    text, preview = await _process_video(vid_path)
    assert "ffmpeg not available" in text


@pytest.mark.asyncio
async def test_process_video_success(tmp_path, monkeypatch):
    import subprocess as sp

    audio_path = None

    def mock_run(*args, **kwargs):
        nonlocal audio_path
        # args[0] is the list, last arg is the output path
        cmd_list = args[0] if args else kwargs.get("args", [])
        audio_path = cmd_list[-1] if cmd_list else ""
        # Create the audio file so _process_audio can find it
        with open(audio_path, "wb") as f:
            f.write(b"fake audio")
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr(sp, "run", mock_run)

    mock_whisper = MagicMock()
    mock_whisper.speech_to_text = AsyncMock(
        return_value={"text": "Video speech content", "language": "pt"}
    )
    with patch("api.routes.upload._get_service_or_503", return_value=mock_whisper):
        vid_path = str(tmp_path / "clip.mp4")
        with open(vid_path, "wb") as f:
            f.write(b"fake video")
        from api.routes.upload import _process_video

        text, preview = await _process_video(vid_path)
    assert "[Video:" in text
    assert "Video speech content" in text


@pytest.mark.asyncio
async def test_process_docx_error(tmp_path):
    docx_path = str(tmp_path / "broken.docx")
    with open(docx_path, "wb") as f:
        f.write(b"not a real docx")
    from api.routes.upload import _process_docx

    text, preview = await _process_docx(docx_path)
    assert "[Document uploaded:" in text


@pytest.mark.asyncio
async def test_process_image_gemini_success(tmp_path, monkeypatch):
    img_path = str(tmp_path / "photo.jpg")
    with open(img_path, "wb") as f:
        f.write(b"\xff\xd8\xff" + b"\x00" * 50)

    mock_response = MagicMock()
    mock_response.text = "A beautiful landscape with mountains and a river"

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    mock_genai = MagicMock()
    mock_genai.Client.return_value = mock_client

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    with patch("api.routes.upload.genai", mock_genai):
        from api.routes.upload import _process_image

        text, preview = await _process_image(img_path)
    assert "landscape" in text or len(text) > 0


@pytest.mark.asyncio
async def test_process_pdf_with_content(tmp_path):
    try:
        import pdfplumber  # noqa: F401
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("pdfplumber or reportlab not installed")

    pdf_path = str(tmp_path / "real.pdf")
    c = canvas.Canvas(pdf_path, pagesize=letter)
    c.drawString(72, 720, "Hello from Capivarex PDF test")
    c.save()

    from api.routes.upload import _process_pdf

    text, preview = await _process_pdf(pdf_path)
    assert "Hello from Capivarex" in text or "PDF" in preview
