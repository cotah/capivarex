"""
Orchestrator Agent - Routes requests to specialized agents.

Refactored to use new BaseAgent architecture.
"""

import json
import logging
from typing import Any, Dict, List

from pydantic import ValidationError

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from schemas.orchestrator import OrchestratorDecision
from services import get_service


logger = logging.getLogger(__name__)

# Allowed agent types (kept for quick membership checks)
ALLOWED_AGENTS = {
    "chat", "research", "dev", "weather", "finance",
    "image", "video", "voice", "calendar", "traffic",
    "car", "smarthome", "github"
}


@register_agent("orchestrator", lazy=False)
class OrchestratorAgent(BaseAgent):
    """
    Orchestrator agent that routes requests to specialized agents.

    Uses OpenAI to analyze the user's prompt and determine which
    specialized agent should handle the request.
    """

    def __init__(self):
        super().__init__(
            name="orchestrator",
            description="Routes requests to specialized agents"
        )

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Analyze prompt and route to appropriate agent.

        Args:
            prompt: User's input prompt
            context: Execution context

        Returns:
            AgentResponse with routing decision
        """
        openai_service = get_service("openai")

        # Only initialize if not already initialized (avoid redundant calls)
        if not openai_service or not openai_service.is_initialized():
            try:
                await openai_service.initialize()
            except Exception as e:
                self.logger.error("Failed to initialize OpenAI service: %s", e)
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="chat",
                    data={"agent": "chat", "reason": "Service initialization failed"},
                    error=str(e),
                )

        client = openai_service.client
        if not client:
            self.logger.warning("OpenAI client not available, defaulting to chat")
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="chat",
                data={"agent": "chat", "reason": "OpenAI client not available"}
            )

        system_prompt = """
Você é um orquestrador de IA. Sua função é analisar o prompt do usuário e decidir qual especialista é o mais adequado.

Agentes disponíveis:
- 'chat': Conversas gerais, saudações, perguntas de conhecimento comum, piadas, curiosidades.
- 'research': Notícias, informações atuais, pesquisa web, fatos recentes.
- 'dev': Criar, analisar, corrigir ou explicar código de programação.
- 'github': Operações Git e GitHub: criar repositórios, commits, branches, push, pull, clone, status.
- 'weather': Perguntas sobre clima, previsão do TEMPO ATMOSFÉRICO, temperatura EXTERNA.
- 'finance': Cotações de ações, dados financeiros, mercado, investimentos.
- 'image': Criar, gerar ou desenhar uma IMAGEM VISUAL (foto, ilustração, desenho).
- 'video': Criar, gerar ou produzir um VÍDEO.
- 'voice': Converter texto em AUDIO/VOZ (falar, narrar, ler em voz alta), ou transcrever áudio em texto.
- 'calendar': Perguntas sobre agenda, calendário, reuniões, compromissos, eventos, horários.
- 'traffic': Perguntas sobre tráfego, rotas, tempo de viagem, condições de trânsito, navegação.
- 'car': Controle de veículo elétrico: bateria, carregamento, localização do carro, trancar/destrancar portas, odômetro, status do veículo.
- 'smarthome': Controle de casa inteligente: luzes, interruptores, dispositivos IoT, termostato da casa, sensores, SmartThings.

EXEMPLOS (use como referência):
"como está a bateria do meu carro?" → car
"onde está meu carro?" → car
"tranque o carro" → car
"destranque o veículo" → car
"status do veículo" → car
"comece a carregar o carro" → car
"acenda as luzes da sala" → smarthome
"apague as luzes" → smarthome
"qual a temperatura da casa?" → smarthome
"ligue o ar condicionado" → smarthome
"desligue a TV" → smarthome
"quais dispositivos estão ligados?" → smarthome
"status dos dispositivos" → smarthome
"quais meus compromissos hoje?" → calendar
"agende uma reunião" → calendar
"como está o tempo em São Paulo?" → weather
"quanto está a ação da Apple?" → finance
"gere uma imagem de um gato" → image
"crie um vídeo de ondas" → video
"leia esse texto em voz alta" → voice
"pesquise sobre inteligência artificial" → research
"me ajude com código Python" → dev
"crie um repositório chamado meu-projeto" → github
"faça um commit" → github
"mostre o status do git" → github
"faça push para o GitHub" → github
"clone este repositório" → github
"crie uma branch feature/login" → github
"olá, tudo bem?" → chat

REGRAS:
- Se mencionar git, github, repositório, commit, branch, push, pull, clone → 'github'
- Se mencionar carro, veículo, bateria (do carro), carregar (veículo), trancar, destrancar → 'car'
- Se mencionar luzes, dispositivos, casa inteligente, ligar/desligar aparelhos, SmartThings → 'smarthome'
- Se mencionar agenda, reunião, evento, compromisso → 'calendar'
- Se pedir para gerar áudio, falar, narrar, ler em voz alta → 'voice'
- Se pedir para gerar imagem, desenhar, criar foto, ilustrar → 'image'
- Se pedir para gerar vídeo → 'video'
- Na dúvida entre dois agentes, prefira o mais específico (ex: smarthome > chat).

Responda SEMPRE em formato JSON, seguindo este schema:
{"agent": "<nome_do_agente>", "reason": "<justificativa>"}
""".strip()

        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=150,
                temperature=0.0,
            )

            response_text = response.choices[0].message.content or ""
            decision_data = json.loads(response_text)

            # Validate with Pydantic
            validated_decision = OrchestratorDecision.model_validate(decision_data)
            decision = validated_decision.agent

            self.logger.info(
                f"Routed to agent: {decision} (Reason: {validated_decision.reason})",
                extra={"prompt": prompt[:100]}
            )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=decision,
                data={
                    "agent": decision,
                    "prompt": prompt
                }
            )

        except (json.JSONDecodeError, ValidationError) as e:
            self.logger.warning(
                f"Failed to parse or validate LLM decision: {e}. Falling back to chat.",
                extra={"prompt": prompt[:100]}
            )
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="chat",
                data={"agent": "chat", "reason": "JSON validation fallback"},
            )

        except Exception as e:
            self.logger.error(
                f"Orchestration failed: {e}",
                exc_info=True
            )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response="chat",
                data={"agent": "chat", "reason": "Orchestration failed"},
                error=str(e)
            )

    def get_capabilities(self) -> List[str]:
        """Get orchestrator capabilities."""
        return ["routing", "agent_selection", "intent_classification"]
