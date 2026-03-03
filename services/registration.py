# services/registration.py

"""
Service registration module.

Provides register_all_services() for explicit initialization,
replacing the old import-side-effect pattern.
"""

_registered = False


def register_all_services() -> None:
    """Import all service modules to trigger @register_service decorators."""
    global _registered
    if _registered:
        return
    _registered = True

    # Serviços de IA
    from .ai.anthropic_service import AnthropicService  # noqa: F401
    from .ai.elevenlabs_service import ElevenLabsService  # noqa: F401
    from .ai.openai_service import OpenAIService  # noqa: F401
    from .ai.perplexity_service import PerplexityService  # noqa: F401

    # Serviços de Negócio
    from .business.proactivity_service import ProactivityService  # noqa: F401
    from .business.prompt_cleaner import PromptCleanerService  # noqa: F401
    from .business.research_service import ResearchService  # noqa: F401
    from .business.vehicle_db_service import VehicleDbService  # noqa: F401
    from .business.translate_service import TranslateService  # noqa: F401
    from .business.crypto_service import CryptoService  # noqa: F401
    from .business.timer_service import TimerService  # noqa: F401
    from .business.reminder_service import ReminderService  # noqa: F401
    from .business.search_service import SearchService  # noqa: F401
    from .business.leaving_now_service import LeavingNowService  # noqa: F401
    from .business.mercado_service import MercadoService  # noqa: F401
    from .business.notes_service import NotesService  # noqa: F401
    from .business.quota_service import QuotaService  # noqa: F401
    from .business.email_polling_service import EmailPollingService  # noqa: F401

    # Serviços de Infraestrutura
    from .infrastructure.code_executor import CodeExecutorService  # noqa: F401
    from .infrastructure.database import DatabaseService  # noqa: F401
    from .infrastructure.file_manager import FileManagerService  # noqa: F401
    from .infrastructure.git_service import GitService  # noqa: F401
    from .infrastructure.notification_service import NotificationService  # noqa: F401
    from .infrastructure.redis_service import RedisService  # noqa: F401

    # Serviços de Integrações
    from .integrations.calendar_service import CalendarService  # noqa: F401
    from .integrations.car_service import CarService  # noqa: F401
    from .integrations.finance_service import FinanceService  # noqa: F401
    from .integrations.smartthings_service import SmartThingsService  # noqa: F401
    from .integrations.traffic_service import TrafficService  # noqa: F401
    from .integrations.weather_service import WeatherService  # noqa: F401
    from .integrations.youtube_service import YouTubeService  # noqa: F401
    from .integrations.tracking_service import TrackingService  # noqa: F401
    from .integrations.transit_service import TransitService  # noqa: F401
    from .integrations.twilio_service import TwilioService  # noqa: F401
    from .integrations.restaurant_service import RestaurantService  # noqa: F401
    from .integrations.spotify_service import SpotifyService  # noqa: F401
    from .integrations.gmail_service import GmailService  # noqa: F401

    # Serviços de Mídia
    from .media.image_service import ImageService  # noqa: F401
    from .media.video_service import VideoService  # noqa: F401
    from .media.whisper_service import WhisperService  # noqa: F401

    # Pipeline de Voz (STT + LLM + TTS)
    from .voice_pipeline_service import VoicePipelineService  # noqa: F401


# Backward compatibility: importing this module still triggers registration
register_all_services()
