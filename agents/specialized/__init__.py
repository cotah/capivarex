"""
Specialized agents for CapivaraX Bot.

All agents are automatically registered via decorators.
"""

# Import all agents to trigger registration
from .orchestrator_agent import OrchestratorAgent
from .chat_agent import ChatAgent
from .weather_agent import WeatherAgent
from .research_agent import ResearchAgent
from .finance_agent import FinanceAgent
from .dev_agent import DevAgent
from .image_agent import ImageAgent
from .video_agent import VideoAgent
from .voice_agent import VoiceAgent
from .calendar_agent import CalendarAgent
from .traffic_agent import TrafficAgent
from .car_agent import CarAgent
from .smarthome_agent import SmartHomeAgent
from .github_agent import GitHubAgent
from .time_agent import TimeAgent
from .translate_agent import TranslateAgent
from .crypto_agent import CryptoAgent
from .timer_agent import TimerAgent
from .reminder_agent import ReminderAgent
from .youtube_agent import YouTubeAgent
from .tracking_agent import TrackingAgent
from .meeting_agent import MeetingAgent
from .search_agent import SearchAgent
from .leaving_now_agent import LeavingNowAgent
from .mercado_agent import MercadoAgent

__all__ = [
    "OrchestratorAgent",
    "ChatAgent",
    "WeatherAgent",
    "ResearchAgent",
    "FinanceAgent",
    "DevAgent",
    "ImageAgent",
    "VideoAgent",
    "VoiceAgent",
    "CalendarAgent",
    "TrafficAgent",
    "CarAgent",
    "SmartHomeAgent",
    "GitHubAgent",
    "TimeAgent",
    "TranslateAgent",
    "CryptoAgent",
    "TimerAgent",
    "ReminderAgent",
    "YouTubeAgent",
    "TrackingAgent",
    "MeetingAgent",
    "SearchAgent",
    "LeavingNowAgent",
    "MercadoAgent",
]
