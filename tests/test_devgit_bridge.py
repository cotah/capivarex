"""Tests for DevGit Bridge — Dev Agent + GitHub integration."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from services.business.devgit_bridge import (
    format_summary,
    format_push_result,
    get_preview,
    cleanup_expired,
    _create_preview,
    _make_id,
    _pending_projects,
    _code_previews,
)
from api.routes.devgit import router
from api.dependencies import get_current_user


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router)
    # Override auth — devgit routes now require authentication
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user", "plan": "professional"}
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestFormatSummary:
    def test_basic_summary(self):
        project = {
            "name": "task-api",
            "total_files": 3,
            "total_lines": 100,
            "language": "python",
            "batches": 1,
            "files": [
                {"path": "main.py", "content": "", "lines": 50},
                {"path": "models.py", "content": "", "lines": 30},
                {"path": "README.md", "content": "", "lines": 20},
            ],
        }
        result = format_summary(project)
        assert "task-api" in result
        assert "3 arquivos" in result
        assert "100 linhas" in result
        assert "main.py" in result

    def test_summary_with_preview(self):
        project = {
            "name": "test",
            "total_files": 1,
            "total_lines": 10,
            "language": "python",
            "batches": 1,
            "preview_id": "abc123",
            "files": [{"path": "main.py", "content": "", "lines": 10}],
        }
        result = format_summary(project, "https://example.com")
        assert "preview/abc123" in result

    def test_summary_multiple_batches(self):
        project = {
            "name": "big-project",
            "total_files": 15,
            "total_lines": 500,
            "language": "python",
            "batches": 2,
            "files": [
                {"path": f"file{i}.py", "content": "", "lines": 33} for i in range(15)
            ],
        }
        result = format_summary(project)
        assert "2 lotes" in result


class TestFormatPushResult:
    def test_done(self):
        result = format_push_result(
            {
                "done": True,
                "repo_url": "https://github.com/user/repo",
                "total_pushed": 5,
            }
        )
        assert "✅" in result
        assert "github.com/user/repo" in result

    def test_batch_in_progress(self):
        result = format_push_result(
            {
                "done": False,
                "batch": 1,
                "batches": 3,
                "files_pushed": 10,
            }
        )
        assert "Lote 1/3" in result
        assert "continuar" in result.lower()


class TestPreview:
    def test_create_and_get(self):
        files = [{"path": "test.py", "content": "print('hi')", "lines": 1}]
        preview_id = _create_preview("proj1", files)
        preview = get_preview(preview_id)
        assert preview is not None
        assert preview["files"] == files

    def test_expired_preview(self):
        _code_previews["expired123"] = {
            "project_id": "p1",
            "files": [],
            "created_at": 0,
            "expires_at": 0,
        }
        assert get_preview("expired123") is None

    def test_nonexistent_preview(self):
        assert get_preview("doesnotexist") is None


class TestCleanup:
    def test_cleanup_expired(self):
        _code_previews["old1"] = {
            "expires_at": 0,
            "project_id": "p",
            "files": [],
            "created_at": 0,
        }
        _pending_projects["old2"] = {"created_at": 0, "user_id": "u", "files": []}
        cleanup_expired()
        assert "old1" not in _code_previews
        assert "old2" not in _pending_projects


class TestHelpers:
    def test_make_id(self):
        id1 = _make_id("user1", "project")
        assert len(id1) == 16
        assert isinstance(id1, str)


class TestPreviewRoute:
    def test_preview_not_found(self, client):
        resp = client.get("/preview/nonexistent")
        assert resp.status_code == 404
        assert "expired" in resp.text.lower()

    def test_preview_renders(self, client):
        files = [
            {"path": "main.py", "content": "print('hello')", "lines": 1},
            {"path": "README.md", "content": "# Hello", "lines": 1},
        ]
        preview_id = _create_preview("test-proj", files)
        resp = client.get(f"/preview/{preview_id}")
        assert resp.status_code == 200
        assert "main.py" in resp.text
        assert "README.md" in resp.text
        assert "Capivarex" in resp.text
        assert "highlight.js" in resp.text


class TestGenerateRoute:
    def test_generate_missing_fields(self, client):
        resp = client.post("/generate", json={"user_id": "u1"})
        assert resp.status_code == 400

    def test_generate_success(self, client):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            '{"name": "task-api", "description": "Task manager", '
            '"files": [{"path": "main.py", "content": "from fastapi import FastAPI\\napp = FastAPI()"}]}'
        )

        with patch(
            "services.business.devgit_bridge.get_service", return_value=mock_openai
        ):
            resp = client.post(
                "/generate",
                json={
                    "user_id": "user-123",
                    "description": "FastAPI task manager",
                    "language": "python",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "task-api"
        assert data["total_files"] == 1
        assert "preview_url" in data


class TestPushRoute:
    def test_push_missing_project_id(self, client):
        resp = client.post("/push", json={})
        assert resp.status_code == 400

    def test_push_project_not_found(self, client):
        resp = client.post("/push", json={"project_id": "nonexistent"})
        assert resp.status_code == 404


class TestProjectRoute:
    def test_project_not_found(self, client):
        resp = client.get("/project/nonexistent")
        assert resp.status_code == 404

    def test_project_found(self, client):
        _pending_projects["test-proj-123"] = {
            "project_id": "test-proj-123",
            "name": "my-project",
            "total_files": 3,
            "pushed_files": 0,
            "current_batch": 0,
            "batches": 1,
            "repo_url": "",
        }
        resp = client.get("/project/test-proj-123")
        assert resp.status_code == 200
        assert resp.json()["name"] == "my-project"
        _pending_projects.pop("test-proj-123", None)


class TestGenerateProject:
    @pytest.mark.asyncio
    async def test_no_openai(self):
        from services.business.devgit_bridge import generate_project

        with patch("services.business.devgit_bridge.get_service", return_value=None):
            result = await generate_project("u1", "test project")
        assert result is None

    @pytest.mark.asyncio
    async def test_openai_bad_json(self):
        from services.business.devgit_bridge import generate_project

        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = "not json at all"

        with patch(
            "services.business.devgit_bridge.get_service", return_value=mock_openai
        ):
            result = await generate_project("u1", "test project")
        assert result is None

    @pytest.mark.asyncio
    async def test_openai_empty_files(self):
        from services.business.devgit_bridge import generate_project

        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = '{"name": "test", "files": []}'

        with patch(
            "services.business.devgit_bridge.get_service", return_value=mock_openai
        ):
            result = await generate_project("u1", "test project")
        assert result is None

    @pytest.mark.asyncio
    async def test_openai_success(self):
        from services.business.devgit_bridge import generate_project

        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            '{"name": "my-api", "description": "API", '
            '"files": [{"path": "main.py", "content": "print(1)\\nprint(2)"}]}'
        )

        with patch(
            "services.business.devgit_bridge.get_service", return_value=mock_openai
        ):
            result = await generate_project("u1", "test api")
        assert result is not None
        assert result["name"] == "my-api"
        assert result["total_files"] == 1
        assert result["files"][0]["lines"] == 2

    def test_preview_html_has_syntax_highlighting(self, client):
        files = [
            {
                "path": "app.py",
                "content": "def hello():\n    return 'world'",
                "lines": 2,
            }
        ]
        pid = _create_preview("p1", files)
        resp = client.get(f"/preview/{pid}")
        assert "highlight.js" in resp.text
        assert "def hello" in resp.text

    def test_summary_single_file(self):
        project = {
            "name": "single",
            "total_files": 1,
            "total_lines": 5,
            "language": "python",
            "batches": 1,
            "files": [{"path": "main.py", "content": "", "lines": 5}],
        }
        result = format_summary(project)
        assert "1 arquivo" in result  # singular


class TestPushToGitHub:
    @pytest.mark.asyncio
    async def test_push_no_project(self):
        from services.business.devgit_bridge import push_to_github

        result = await push_to_github("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_push_no_db(self):
        from services.business.devgit_bridge import push_to_github

        _pending_projects["test-push"] = {
            "user_id": "u1",
            "name": "test",
            "files": [],
            "current_batch": 0,
            "pushed_files": 0,
            "batches": 1,
            "description": "test",
            "repo_url": "",
        }
        with patch("services.business.devgit_bridge.get_service", return_value=None):
            result = await push_to_github("test-push")
        assert result is None
        _pending_projects.pop("test-push", None)
