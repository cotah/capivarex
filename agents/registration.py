# agents/registration.py

"""
Agent registration module.

Provides register_all_agents() for explicit initialization,
replacing the old import-side-effect pattern.
"""

_registered = False


def register_all_agents() -> None:
    """Import all agent modules to trigger @register_agent decorators."""
    global _registered
    if _registered:
        return
    _registered = True

    from .specialized.calendar_agent import CalendarAgent  # noqa: F401
    from .specialized.car_agent import CarAgent  # noqa: F401
    from .specialized.chat_agent import ChatAgent  # noqa: F401
    from .specialized.crypto_agent import CryptoAgent  # noqa: F401
    from .specialized.dev_agent import DevAgent  # noqa: F401
    from .specialized.finance_agent import FinanceAgent  # noqa: F401
    from .specialized.github_agent import GitHubAgent  # noqa: F401
    from .specialized.image_agent import ImageAgent  # noqa: F401
    from .specialized.leaving_now_agent import LeavingNowAgent  # noqa: F401
    from .specialized.meeting_agent import MeetingAgent  # noqa: F401
    from .specialized.mercado_agent import MercadoAgent  # noqa: F401
    from .specialized.notes_agent import NotesAgent  # noqa: F401
    from .specialized.orchestrator_agent import OrchestratorAgent  # noqa: F401
    from .specialized.reminder_agent import ReminderAgent  # noqa: F401
    from .specialized.research_agent import ResearchAgent  # noqa: F401
    from .specialized.search_agent import SearchAgent  # noqa: F401
    from .specialized.smarthome_agent import SmartHomeAgent  # noqa: F401
    from .specialized.time_agent import TimeAgent  # noqa: F401
    from .specialized.timer_agent import TimerAgent  # noqa: F401
    from .specialized.tracking_agent import TrackingAgent  # noqa: F401
    from .specialized.traffic_agent import TrafficAgent  # noqa: F401
    from .specialized.translate_agent import TranslateAgent  # noqa: F401
    from .specialized.transport_agent import TransportAgent  # noqa: F401
    from .specialized.travel_agent import TravelAgent  # noqa: F401
    from .specialized.twilio_agent import TwilioAgent  # noqa: F401
    from .specialized.video_agent import VideoAgent  # noqa: F401
    from .specialized.voice_agent import VoiceAgent  # noqa: F401
    from .specialized.weather_agent import WeatherAgent  # noqa: F401
    from .specialized.youtube_agent import YouTubeAgent  # noqa: F401
    from .specialized.restaurant_agent import RestaurantAgent  # noqa: F401
    from .specialized.email_agent import EmailAgent  # noqa: F401
    from .specialized.music_agent import MusicAgent  # noqa: F401


# Backward compatibility: importing this module still triggers registration
register_all_agents()
