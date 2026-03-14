"""
GitHub Agent - Handles Git and GitHub operations via Telegram.
Refactored to use new BaseAgent architecture.

FIX [2025-02] — MÉTODO NÃO EXISTE:
  O agent chamava métodos que não existem no GitService:
  - get_status() → deve ser status()
  - get_log()    → deve ser log()
  - checkout_branch() → deve ser checkout()
  - clone_repo() → deve ser clone()
  - init_repo() retorno esperava 'path' ✅ (correcto)

  Também corrigidos os formatos de retorno:
  - status() retorna {branch, is_dirty, untracked, modified, staged}
    (agent esperava {status, branch})
  - log() retorna lista de dicts [{sha, message, author, date}]
    (agent esperava {commits: [{hash, message, ...}]})
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services.ai.model_config import INTENT_MODEL
from services import get_service

logger = logging.getLogger(__name__)

# Valid intents for GitHub commands
VALID_INTENTS = {
    "create_repo",
    "commit",
    "status",
    "log",
    "create_branch",
    "checkout_branch",
    "push",
    "pull",
    "clone",
    "help",
}


@register_agent("github")
class GitHubAgent(BaseAgent):
    """
    GitHub agent for Git and GitHub operations.

    Handles:
    - Creating repositories
    - Making commits
    - Checking status
    - Viewing commit log
    - Creating and switching branches
    - Pushing to GitHub
    - Pulling from GitHub
    - Cloning repositories
    """

    def __init__(self):
        """Initialise the GitHub agent."""
        super().__init__(
            name="github",
            description="Handles Git and GitHub operations",
        )

    async def _get_git_service(self) -> Optional[Any]:
        """Get the Git service, initializing if needed."""
        try:
            svc = get_service("git")
            if svc:
                if not svc.is_initialized():
                    await svc.initialize()
                return svc
            return None
        except Exception as e:
            self.logger.warning("Could not get Git service: %s", e)
            return None

    async def _load_stored_connection(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load GitHub connection from DB for a user."""
        try:
            db = get_service("database")
            if db:
                if not db.is_initialized():
                    await db.initialize()
                return await db.get_github_connection(user_id)
        except Exception as e:
            self.logger.warning("Could not load github connection: %s", e)
        return None

    async def _save_connection(
        self, user_id: str, github_username: str, access_token: str
    ) -> bool:
        """Persist GitHub connection to DB."""
        try:
            db = get_service("database")
            if db:
                if not db.is_initialized():
                    await db.initialize()
                return await db.save_github_connection(
                    user_id, github_username, access_token
                )
        except Exception as e:
            self.logger.warning("Could not save github connection: %s", e)
        return False

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------
    async def _analyze_intent(self, user_message: str) -> Dict[str, Any]:
        """Analyze user intent and extract parameters using OpenAI."""
        openai_svc = get_service("openai")
        if not openai_svc:
            return {"intent": "help"}

        if not openai_svc.is_initialized():
            try:
                await asyncio.wait_for(openai_svc.initialize(), timeout=10)
            except asyncio.TimeoutError:
                self.logger.warning("OpenAI init timed out for GitHub intent")
                return {"intent": "help"}

        client = openai_svc.client
        if not client:
            return {"intent": "help"}

        system_prompt = (
            "You are an intent classifier for Git/GitHub commands.\n\n"
            "Analyze the user's message and return a JSON object with:\n"
            '- "intent": one of: create_repo, commit, status, log, '
            "create_branch, checkout_branch, push, pull, clone, help\n"
            '- "repo_name": repository name if mentioned, or null\n'
            '- "commit_message": commit message if mentioned, or null\n'
            '- "branch_name": branch name if mentioned, or null\n'
            '- "repo_url": GitHub URL if mentioned, or null\n'
            '- "project_path": local project path if mentioned, or null\n\n'
            "Examples:\n"
            '"crie um repositório chamado meu-projeto" → '
            '{"intent":"create_repo","repo_name":"meu-projeto"}\n'
            "\"faça um commit com a mensagem 'fix: bug corrigido'\" → "
            '{"intent":"commit","commit_message":"fix: bug corrigido"}\n'
            '"mostre o status do repositório" → {"intent":"status"}\n'
            '"status do repositorio" → {"intent":"status"}\n'
            '"git status" → {"intent":"status"}\n'
            '"liste os últimos commits" → {"intent":"log"}\n'
            '"crie uma branch feature/nova" → '
            '{"intent":"create_branch","branch_name":"feature/nova"}\n'
            '"mude para a branch develop" → '
            '{"intent":"checkout_branch","branch_name":"develop"}\n'
            '"faça push para o GitHub" → {"intent":"push"}\n'
            '"faça pull do GitHub" → {"intent":"pull"}\n'
            '"clone https://github.com/user/repo" → '
            '{"intent":"clone","repo_url":"https://github.com/user/repo"}\n\n'
            "Return ONLY the JSON object, no other text."
        )

        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=INTENT_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.0,
                    max_completion_tokens=200,
                ),
                timeout=15,
            )

            result_text = (response.choices[0].message.content or "").strip()
            # Remove markdown code blocks if present
            if result_text.startswith("```"):
                parts = result_text.split("```")
                if len(parts) > 1:
                    result_text = parts[1]
                    if result_text.startswith(("json", "python", "text")):
                        result_text = result_text.split("\n", 1)[-1]

            result = json.loads(result_text)
            intent = result.get("intent", "help")
            if intent not in VALID_INTENTS:
                intent = "help"

            return {
                "intent": intent,
                "repo_name": result.get("repo_name"),
                "commit_message": result.get("commit_message"),
                "branch_name": result.get("branch_name"),
                "repo_url": result.get("repo_url"),
                "project_path": result.get("project_path"),
            }

        except Exception as e:
            self.logger.error("Intent analysis failed: %s", e)
            return {"intent": "help"}

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------
    def _resolve_path(self, git_svc: Any, analysis: Dict[str, Any]) -> str:
        """Resolve the project path from analysis or use workspace default."""
        custom_path = analysis.get("project_path")
        if custom_path:
            return custom_path
        # Use the service's base workspace
        base = getattr(git_svc, "base_workspace", None)
        if base:
            return str(base / "current")
        return "/tmp/workspace/current"

    @staticmethod
    def _is_git_repo(path: str) -> bool:
        """Check if a path exists and contains a git repository."""
        from pathlib import Path

        p = Path(path)
        return p.exists() and (p / ".git").exists()

    def _no_repo_response(self, path: str) -> AgentResponse:
        """Return a friendly message when no repo exists at the given path."""
        return AgentResponse(
            status=AgentStatus.ERROR,
            response=(
                f"📂 Nenhum repositório Git encontrado em `{path}`.\n\n"
                "Para começar, usa um destes comandos:\n"
                '• "crie um repositório chamado meu-projeto"\n'
                '• "clone https://github.com/user/repo"'
            ),
            error="No git repository at path",
        )

    # ------------------------------------------------------------------
    # Main execute
    # ------------------------------------------------------------------
    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """Process a GitHub/Git command."""
        try:
            git_svc = await self._get_git_service()
            if not git_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Serviço Git não disponível no momento.",
                    error="Git service not available",
                )

            analysis = await self._analyze_intent(prompt)
            intent = analysis["intent"]

            dispatch = {
                "create_repo": self._handle_create_repo,
                "commit": self._handle_commit,
                "status": self._handle_status,
                "log": self._handle_log,
                "create_branch": self._handle_create_branch,
                "checkout_branch": self._handle_checkout_branch,
                "push": self._handle_push,
                "pull": self._handle_pull,
                "clone": self._handle_clone,
                "help": self._handle_help,
            }

            handler = dispatch.get(intent, self._handle_help)
            return await handler(git_svc, analysis)

        except Exception as e:
            self.logger.error("GitHub agent failed: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao executar operação Git: {str(e)}",
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Handlers — FIX: Nomes de métodos corrigidos para match com GitService
    # ------------------------------------------------------------------

    async def _handle_create_repo(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle repository creation — creates on GitHub.com AND locally."""
        repo_name = analysis.get("repo_name")
        if not repo_name:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Por favor, especifique o nome do repositório.\n"
                    "Exemplo: 'crie um repositório chamado meu-projeto'"
                ),
            )

        # Clean repo name (remove brackets, extra spaces)
        repo_name = repo_name.strip().strip("[]").strip()

        # ── 1. Criar no GitHub.com via API ───────────────────────────
        github_token = getattr(git_svc, "github_token", None)
        github_url = None
        clone_url = None
        github_created = False

        if github_token:
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://api.github.com/user/repos",
                        headers={
                            "Authorization": f"token {github_token}",
                            "Accept": "application/vnd.github.v3+json",
                        },
                        json={
                            "name": repo_name,
                            "private": False,
                            "auto_init": True,  # Cria com README
                        },
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        data = await resp.json()

                        if resp.status == 201:
                            github_url = data.get("html_url", "")
                            clone_url = data.get("clone_url", "")
                            github_created = True
                            self.logger.info("GitHub repo created: %s", github_url)
                        elif resp.status == 422:
                            # Repo já existe
                            errors = data.get("errors", [])
                            if (
                                errors
                                and errors[0].get("message")
                                == "name already exists on this account"
                            ):
                                return AgentResponse(
                                    status=AgentStatus.ERROR,
                                    response=(
                                        f"⚠️ O repositório **{repo_name}** já existe na sua conta GitHub.\n"
                                        "Escolha outro nome ou use 'clone' para clonar o existente."
                                    ),
                                )
                            msg = data.get("message", "")
                            return AgentResponse(
                                status=AgentStatus.ERROR,
                                response=f"⚠️ GitHub recusou: {msg}",
                            )
                        else:
                            self.logger.warning("GitHub API %d: %s", resp.status, data)
            except Exception as e:
                self.logger.warning("GitHub API create failed: %s", e)
                # Continua — cria só local

        # ── 2. Clonar localmente (se criou no GitHub) ────────────────
        base = getattr(git_svc, "base_workspace", None)
        local_path = str(base / repo_name) if base else f"/tmp/workspace/{repo_name}"

        if github_created and clone_url:
            try:
                result = git_svc.clone(clone_url, local_path)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=(
                        f"✅ Repositório **{repo_name}** criado com sucesso!\n\n"
                        f"🐙 GitHub: {github_url}\n"
                        f"📂 Local: `{result['path']}`\n\n"
                        "O repositório já está pronto para uso com push/pull."
                    ),
                    data={"github_url": github_url, "path": result["path"]},
                )
            except Exception as e:
                # Criou no GitHub mas falhou clone local — ainda OK
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=(
                        f"✅ Repositório **{repo_name}** criado no GitHub!\n\n"
                        f"🐙 GitHub: {github_url}\n\n"
                        f"⚠️ Clone local falhou ({e}), mas o repo está no GitHub."
                    ),
                    data={"github_url": github_url},
                )

        # ── 3. Fallback: só local (se não tem token) ─────────────────
        result = git_svc.init_repo(local_path)
        response_text = (
            f"✅ Repositório **{repo_name}** criado localmente!\n"
            f"📂 Caminho: `{result['path']}`"
        )
        if not github_token:
            response_text += (
                "\n\n⚠️ GITHUB_TOKEN não configurado — repo criado apenas localmente."
                "\nPara criar no GitHub.com, configure a variável GITHUB_TOKEN."
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response_text,
            data=result,
        )

    async def _handle_commit(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle commit creation."""
        commit_message = analysis.get("commit_message")
        if not commit_message:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Por favor, especifique a mensagem do commit.\n"
                    "Exemplo: 'faça um commit com a mensagem \"fix: bug corrigido\"'"
                ),
            )

        project_path = self._resolve_path(git_svc, analysis)

        if not self._is_git_repo(project_path):
            return self._no_repo_response(project_path)

        # FIX: commit() está correcto no service ✅
        result = git_svc.commit(project_path, commit_message)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=(
                f"✅ Commit criado com sucesso!\n\n"
                f"🔑 SHA: `{result['commit'][:8]}`\n"
                f"💬 Mensagem: {commit_message}"
            ),
            data=result,
        )

    async def _handle_status(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle repository status check."""
        project_path = self._resolve_path(git_svc, analysis)

        if not self._is_git_repo(project_path):
            return self._no_repo_response(project_path)

        # FIX: Era get_status() → service tem status()
        result = git_svc.status(project_path)

        # FIX: Formatar o retorno real do service
        # Service retorna: {branch, is_dirty, untracked, modified, staged}
        branch = result.get("branch", "unknown")
        is_dirty = result.get("is_dirty", False)
        untracked = result.get("untracked", [])
        modified = result.get("modified", [])
        staged = result.get("staged", [])

        lines = ["📊 **Status do Repositório**\n", f"🌿 Branch: `{branch}`\n"]

        if not is_dirty and not untracked:
            lines.append("✅ Working tree limpa — nada para commitar.")
        else:
            if staged:
                lines.append("**Staged (prontos para commit):**")
                for f in staged[:15]:
                    lines.append(f"  ✅ `{f}`")
                lines.append("")

            if modified:
                lines.append("**Modificados (não staged):**")
                for f in modified[:15]:
                    lines.append(f"  📝 `{f}`")
                lines.append("")

            if untracked:
                lines.append("**Não rastreados:**")
                for f in untracked[:15]:
                    lines.append(f"  ❓ `{f}`")

            total = len(staged) + len(modified) + len(untracked)
            lines.append(f"\n📈 Total: {total} arquivo(s) com mudanças")

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data=result,
        )

    async def _handle_log(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle commit log viewing."""
        project_path = self._resolve_path(git_svc, analysis)

        if not self._is_git_repo(project_path):
            return self._no_repo_response(project_path)

        # FIX: Era get_log(path, limit=5) → service tem log(path, max_count=5)
        commits = git_svc.log(project_path, max_count=5)

        # FIX: Service retorna lista directa, não {commits: [...]}
        if not commits:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Nenhum commit encontrado.",
            )

        log_text = "📜 **Últimos Commits:**\n\n"
        for commit in commits:
            # FIX: Service usa 'sha' não 'hash'
            sha = commit.get("sha", "?")
            message = commit.get("message", "")
            author = commit.get("author", "")
            date = commit.get("date", "")[:10]
            log_text += f"• `{sha}` — {message}\n  👤 {author} · 📅 {date}\n\n"

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=log_text.strip(),
            data={"commits": commits},
        )

    async def _handle_create_branch(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle branch creation."""
        branch_name = analysis.get("branch_name")
        if not branch_name:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Por favor, especifique o nome da branch.\n"
                    "Exemplo: 'crie uma branch feature/nova-funcionalidade'"
                ),
            )

        project_path = self._resolve_path(git_svc, analysis)

        if not self._is_git_repo(project_path):
            return self._no_repo_response(project_path)

        # FIX: create_branch() está correcto no service ✅
        result = git_svc.create_branch(project_path, branch_name)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"✅ Branch **{branch_name}** criada com sucesso!",
            data=result,
        )

    async def _handle_checkout_branch(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle branch checkout."""
        branch_name = analysis.get("branch_name")
        if not branch_name:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Por favor, especifique o nome da branch.\n"
                    "Exemplo: 'mude para a branch develop'"
                ),
            )

        project_path = self._resolve_path(git_svc, analysis)

        if not self._is_git_repo(project_path):
            return self._no_repo_response(project_path)

        # FIX: Era checkout_branch() → service tem checkout()
        result = git_svc.checkout(project_path, branch_name)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"✅ Branch **{branch_name}** ativada!",
            data=result,
        )

    async def _handle_push(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle push to GitHub."""
        project_path = self._resolve_path(git_svc, analysis)
        branch_name = analysis.get("branch_name", "main")

        if not self._is_git_repo(project_path):
            return self._no_repo_response(project_path)

        # FIX: push() está correcto, mas branch default corrigido ✅
        result = git_svc.push(project_path, "origin", branch_name)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="✅ Push realizado com sucesso para o GitHub!",
            data=result,
        )

    async def _handle_pull(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle pull from GitHub."""
        project_path = self._resolve_path(git_svc, analysis)

        if not self._is_git_repo(project_path):
            return self._no_repo_response(project_path)

        # FIX: pull() está correcto ✅
        result = git_svc.pull(project_path)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="✅ Pull realizado com sucesso!",
            data=result,
        )

    async def _handle_clone(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle repository cloning."""
        repo_url = analysis.get("repo_url")
        if not repo_url:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Por favor, especifique a URL do repositório.\n"
                    "Exemplo: 'clone https://github.com/user/repo'"
                ),
            )

        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        base = getattr(git_svc, "base_workspace", None)
        if base:
            target_path = str(base / repo_name)
        else:
            target_path = f"/tmp/workspace/{repo_name}"

        # FIX: Era clone_repo() → service tem clone()
        result = git_svc.clone(repo_url, target_path)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"✅ Repositório clonado com sucesso em `{result['path']}`!",
            data=result,
        )

    async def _handle_help(
        self, git_svc: Any = None, analysis: Dict[str, Any] = None
    ) -> AgentResponse:
        """Show help message."""
        help_text = (
            "🐙 **GitHub Agent — Comandos Disponíveis**\n\n"
            "**Repositórios:**\n"
            '• "crie um repositório chamado [nome]"\n'
            '• "clone [url]"\n\n'
            "**Commits:**\n"
            "• \"faça um commit com a mensagem '[msg]'\"\n"
            '• "mostre o status"\n'
            '• "liste os últimos commits"\n\n'
            "**Branches:**\n"
            '• "crie uma branch [nome]"\n'
            '• "mude para a branch [nome]"\n\n'
            "**Sincronização:**\n"
            '• "faça push para o GitHub"\n'
            '• "faça pull do GitHub"\n\n'
            "**Exemplos:**\n"
            '• "crie um repositório chamado meu-app"\n'
            "• \"faça um commit com a mensagem 'feat: nova funcionalidade'\"\n"
            '• "crie uma branch feature/login"\n'
            '• "faça push para o GitHub"'
        )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=help_text,
        )

    def get_capabilities(self) -> List[str]:
        """Get GitHub agent capabilities."""
        return [
            "create_repository",
            "commit",
            "status",
            "log",
            "branch_management",
            "push_pull",
            "clone",
        ]
