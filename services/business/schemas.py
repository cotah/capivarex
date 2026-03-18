# services/business/schemas.py

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, HttpUrl


# Schemas para validação de dados de serviços externos


class WeatherData(BaseModel):
    temp: float
    description: str
    city: str


class CalendarEvent(BaseModel):
    summary: str
    start: str
    end: str
    location: Optional[str] = None


class CarStatus(BaseModel):
    connected: bool
    vehicle_id: Optional[str] = None
    battery: Optional[Dict[str, Any]] = None
    location: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class NewsArticle(BaseModel):
    title: str
    url: HttpUrl
    source: str


class NewsData(BaseModel):
    articles: List[NewsArticle]


class FinanceData(BaseModel):
    symbol: str
    price: float
    change_percent: float


# Modelo unificado para o contexto, para validação final
class ProactivityContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    user: Dict[str, Any]
    calendar: Optional[CalendarEvent] = None
    weather: Optional[WeatherData] = None
    car_status: Optional[CarStatus] = None
    news: Optional[NewsData] = None
    finance_alerts: Optional[List[FinanceData]] = None
    traffic: Optional[Dict[str, Any]] = {}
