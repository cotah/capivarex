# services/registration.py

"""
Este módulo importa todos os serviços para garantir que eles sejam registrados
no ServiceRegistry através dos decorators @register_service.

Importe este módulo no início dos pontos de entrada da aplicação (main.py).
"""

# Serviços de IA
from .ai.anthropic_service import AnthropicService
from .ai.elevenlabs_service import ElevenLabsService
from .ai.openai_service import OpenAIService
from .ai.perplexity_service import PerplexityService

# Serviços de Negócio
from .business.proactivity_service import ProactivityService
from .business.prompt_cleaner import PromptCleanerService
from .business.research_service import ResearchService
from .business.vehicle_db_service import VehicleDbService

# Serviços de Infraestrutura
from .infrastructure.code_executor import CodeExecutorService
from .infrastructure.database import DatabaseService
from .infrastructure.file_manager import FileManagerService
from .infrastructure.git_service import GitService
from .infrastructure.redis_service import RedisService

# Serviços de Integrações
from .integrations.calendar_service import CalendarService
from .integrations.car_service import CarService
from .integrations.finance_service import FinanceService
from .integrations.smartthings_service import SmartThingsService
from .integrations.traffic_service import TrafficService
from .integrations.weather_service import WeatherService

# Serviços de Mídia
from .media.image_service import ImageService
from .media.video_service import VideoService
from .media.whisper_service import WhisperService
