# agents/registration.py

"""
Este módulo importa todos os agentes para garantir que eles sejam registrados
no AgentRegistry através dos decorators @register_agent.

Importe este módulo no início dos pontos de entrada da aplicação (main.py).
"""

from .specialized.calendar_agent import CalendarAgent
from .specialized.car_agent import CarAgent
from .specialized.chat_agent import ChatAgent
from .specialized.dev_agent import DevAgent
from .specialized.finance_agent import FinanceAgent
from .specialized.github_agent import GitHubAgent
from .specialized.image_agent import ImageAgent
from .specialized.orchestrator_agent import OrchestratorAgent
from .specialized.research_agent import ResearchAgent
from .specialized.traffic_agent import TrafficAgent
from .specialized.video_agent import VideoAgent
from .specialized.voice_agent import VoiceAgent
from .specialized.weather_agent import WeatherAgent
