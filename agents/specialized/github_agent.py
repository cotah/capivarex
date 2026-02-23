"""
GitHub Agent - Handles Git and GitHub operations via Telegram.

Refactored to use new BaseAgent architecture.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


logger = logging.getLogger(__name__)

# Valid intents for GitHub commands
VALID_INTENTS = {
    "create_repo", "commit", "status", "log", "create_branch",
    "checkout_branch", "push", "pull", "clone", "help",
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
            self.logger.warning(f"Could not get Git service: {e}")
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
            self.logger.warning(f"Could not load github connection: {e}")
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
            self.logger.warning(f"Could not save github connection: {e}")
        return False

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    async def _analyze_intent(self, user_message: str) -> Dict[str, Any]:
        """Analyze user intent and extract parameters using OpenAI.

        Returns:
            Dict with 'intent' and extracted parameters.
        """
        openai_svc = get_service("openai")
        if not openai_svc:
            return {"intent": "help"}

        if not openai_svc.is_initialized():
            await openai_svc.initialize()

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
            '"faça um commit com a mensagem \'fix: bug corrigido\'" → '
            '{"intent":"commit","commit_message":"fix: bug corrigido"}\n'
            '"mostre o status do repositório" → {"intent":"status"}\n'
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
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                max_tokens=200,
            )

            result_text = (response.choices[0].message.content or "").strip()

            # Remove markdown code blocks if present
            if result_text.startswith("```"):
                parts = result_text.split("```")
                if len(parts) > 1:
                    result_text = parts[1]
                    # Remove optional language identifier on first line (e.g., "json\n")
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
                "project_path": result.get("project_path") or "./workspace/current",
            }

        except Exception as e:
            self.logger.error(f"Intent analysis failed: {e}")
            return {"intent": "help"}

    # ------------------------------------------------------------------
    # Main execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """Process a GitHub/Git command.

        Args:
            prompt: User's GitHub command.
            context: Execution context.

        Returns:
            AgentResponse with operation result.
        """
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
            self.logger.error(f"GitHub agent failed: {e}", exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao executar operação Git: {str(e)}",
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_create_repo(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle repository creation."""
        repo_name = analysis.get("repo_name")
        if not repo_name:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Por favor, especifique o nome do repositório.\n"
                    "Exemplo: 'crie um repositório chamado meu-projeto'"
                ),
            )

        project_path = f"./workspace/{repo_name}"
        result = git_svc.init_repo(project_path)

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=(
                f"✅ Repositório **{repo_name}** criado com sucesso!\n"
                f"📂 Caminho: `{result['path']}`"
            ),
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

        project_path = analysis.get("project_path", "./workspace/current")
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
        project_path = analysis.get("project_path", "./workspace/current")
        result = git_svc.get_status(project_path)

        status_text = result["status"] if result["status"] else "Nenhuma mudança"

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=(
                f"📊 **Status do Repositório**\n\n"
                f"🌿 Branch: `{result['branch']}`\n\n"
                f"```\n{status_text}\n```"
            ),
            data=result,
        )

    async def _handle_log(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle commit log viewing."""
        project_path = analysis.get("project_path", "./workspace/current")
        result = git_svc.get_log(project_path, limit=5)

        if not result["commits"]:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Nenhum commit encontrado.",
            )

        log_text = "📜 **Últimos Commits:**\n\n"
        for commit in result["commits"]:
            log_text += (
                f"• `{commit['hash'][:8]}` — {commit['message']}\n"
                f"  👤 {commit['author']} · 📅 {commit['date'][:10]}\n\n"
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=log_text.strip(),
            data=result,
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

        project_path = analysis.get("project_path", "./workspace/current")
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

        project_path = analysis.get("project_path", "./workspace/current")
        result = git_svc.checkout_branch(project_path, branch_name)

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"✅ Branch **{branch_name}** ativada!",
            data=result,
        )

    async def _handle_push(
        self, git_svc: Any, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle push to GitHub."""
        project_path = analysis.get("project_path", "./workspace/current")
        branch_name = analysis.get("branch_name")

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
        project_path = analysis.get("project_path", "./workspace/current")
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
        target_path = f"./workspace/{repo_name}"

        result = git_svc.clone_repo(repo_url, target_path)

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
