# -*- coding: utf-8 -*-
"""
services/integrations/transit_service.py
==========================================
TransitService — transporte público em tempo real.

Duas camadas complementares:
  1. Google Maps Transit   → qual linha apanhar, horários, duração da viagem
  2. TFI GTFS-Realtime     → atrasos reais, cancelamentos, posição GPS do veículo

APIs:
  - Google Maps Routes API  (GOOGLE_MAPS_API_KEY — já tens)
  - NTA Ireland GTFS-RT     (NTA_API_KEY — gratuito em developer.nationaltransport.ie)

Autenticação NTA (Azure API Management):
  Header: Ocp-Apim-Subscription-Key: <chave>
  Primary key vs Secondary key → AMBAS FUNCIONAM IGUAL.
  - Primary key  → chave principal (usa esta por default)
  - Secondary key → backup para rotação sem downtime (guarda como reserva)
  Recomendação: usa a Primary key no .env e guarda a Secondary num local seguro.

Dependências:
  pip install gtfs-realtime-bindings protobuf

Endpoints TFI:
  https://api.nationaltransport.ie/gtfsr/v2/TripUpdates     → atrasos por viagem
  https://api.nationaltransport.ie/gtfsr/v2/Alerts          → alertas de serviço
  https://api.nationaltransport.ie/gtfsr/v2/VehiclePositions → posição GPS

Cobertura:
  - Dublin Bus (DB)
  - Bus Éireann (BE)
  - Luas (tram)
  - DART / Irish Rail
  - Go-Ahead Ireland
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

from services.core import BaseService, register_service, ServiceUnavailableError

load_dotenv()

# Base URLs
_GMAPS_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
_NTA_BASE = "https://api.nationaltransport.ie/gtfsr/v2"

# Delay threshold acima do qual avisamos o utilizador (segundos)
_DELAY_WARN_THRESHOLD_SEC = 120  # 2 minutos


@register_service("transit")
class TransitService(BaseService):
    """
    Serviço de transporte público em tempo real.

    Combina:
      - Google Maps Transit   → qual linha, quando sair, duração estimada
      - TFI GTFS-Realtime     → atrasos reais por viagem (Irlanda)

    Uso típico (LeavingNowService):
      step 1: get_transit_route()          → saber qual linha e horário
      step 2: get_realtime_delays()        → verificar se essa linha está atrasada
      step 3: get_transit_with_delays()    → combinado (recomendado)
    """

    def __init__(self) -> None:
        super().__init__(name="transit")
        self._gmaps_key: Optional[str] = None
        self._nta_key: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._gtfs_available: bool = False

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    async def _initialize(self) -> None:
        self._gmaps_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not self._gmaps_key:
            raise ServiceUnavailableError(
                "GOOGLE_MAPS_API_KEY não encontrada. "
                "O TransitService precisa da mesma key do TrafficService."
            )

        self._nta_key = os.getenv("NTA_API_KEY")
        if not self._nta_key:
            self.logger.warning(
                "NTA_API_KEY não configurada — TFI GTFS-Realtime desativado. "
                "Regista-te em developer.nationaltransport.ie (gratuito) "
                "e adiciona NTA_API_KEY ao .env para atrasos em tempo real."
            )

        self._client = httpx.AsyncClient(timeout=15.0)

        # Verifica disponibilidade do gtfs-realtime-bindings
        try:
            from google.transit import gtfs_realtime_pb2  # noqa: F401

            self._gtfs_available = True
            self.logger.info("gtfs-realtime-bindings disponível ✓")
        except ImportError:
            self._gtfs_available = False
            self.logger.warning(
                "gtfs-realtime-bindings não instalado. "
                "Instala com: pip install gtfs-realtime-bindings protobuf\n"
                "TFI GTFS-Realtime ficará limitado ao modo JSON-only."
            )

        self.logger.info(
            f"TransitService inicializado "
            f"(Google Maps ✓, TFI GTFS-RT: {'✓' if self._nta_key else '✗'})"
        )

    async def _health_check(self) -> bool:
        return self._gmaps_key is not None

    async def _cleanup(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ──────────────────────────────────────────────────────────────────────────
    # LAYER 1 — Google Maps Transit
    # ──────────────────────────────────────────────────────────────────────────

    async def get_transit_route(
        self,
        origin: str,
        destination: str,
        departure_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Calcula rota de transporte público via Google Maps Transit.

        Retorna qual linha/serviço apanhar, horário de partida/chegada
        e duração estimada da viagem.

        Args:
            origin:         Endereço ou coordenadas de origem
            destination:    Endereço ou coordenadas de destino
            departure_time: Quando sair (default: agora)

        Returns:
            Dict com:
              - success: bool
              - duration_minutes: duração total da viagem
              - departure_time: quando sair
              - arrival_time: chegada estimada
              - steps: lista de passos (andar, apanhar linha X, etc.)
              - lines: linhas de transporte envolvidas
              - walking_minutes: tempo total a pé
        """
        if not self.is_initialized():
            await self.initialize()

        if departure_time is None:
            departure_time = datetime.now()

        start = time.time()
        try:
            # Geocode origem e destino
            origin_coords = await self._geocode(origin)
            dest_coords = await self._geocode(destination)

            if not origin_coords or not dest_coords:
                return {
                    "success": False,
                    "error": "Não foi possível geocodificar os endereços",
                }

            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self._gmaps_key,
                "X-Goog-FieldMask": (
                    "routes.duration,routes.distanceMeters,"
                    "routes.legs.steps,routes.legs.duration,"
                    "routes.legs.distanceMeters"
                ),
            }

            payload = {
                "origin": {
                    "location": {
                        "latLng": {
                            "latitude": origin_coords["lat"],
                            "longitude": origin_coords["lng"],
                        }
                    }
                },
                "destination": {
                    "location": {
                        "latLng": {
                            "latitude": dest_coords["lat"],
                            "longitude": dest_coords["lng"],
                        }
                    }
                },
                "travelMode": "TRANSIT",
                "computeAlternativeRoutes": True,
                "transitPreferences": {
                    "routingPreference": "FEWER_TRANSFERS",
                    "allowedTravelModes": [
                        "BUS",
                        "SUBWAY",
                        "TRAIN",
                        "LIGHT_RAIL",
                        "RAIL",
                    ],
                },
                "languageCode": "pt-PT",
                "units": "METRIC",
            }

            resp = await self._client.post(
                _GMAPS_ROUTES_URL, headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("routes"):
                return {
                    "success": False,
                    "error": "Nenhuma rota de transporte encontrada",
                }

            # Rankear rotas: menos transfers primeiro, depois menor duração
            all_routes = data["routes"]
            ranked = []
            for r in all_routes:
                steps_r, lines_r, _ = self._parse_transit_steps(r)
                num_transfers = len(lines_r)
                dur = int(r.get("duration", "0s").replace("s", ""))
                ranked.append((num_transfers, dur, r, steps_r, lines_r))
            ranked.sort(key=lambda x: (x[0], x[1]))

            # Melhor rota (menos transfers, depois mais rápida)
            _, _, route, best_steps, best_lines = ranked[0]

            # Guardar rotas alternativas para mostrar ao utilizador
            alternatives = []
            for num_t, dur, alt_route, alt_steps, alt_lines in ranked[1:3]:
                alt_duration = round(dur / 60, 1)
                alt_line_names = [ln.get("short_name", "?") for ln in alt_lines]
                alternatives.append(
                    {
                        "duration_minutes": alt_duration,
                        "num_transfers": num_t,
                        "lines": alt_line_names,
                    }
                )

            duration_sec = int(route.get("duration", "0s").replace("s", ""))
            duration_min = round(duration_sec / 60, 1)

            arrival = departure_time + timedelta(seconds=duration_sec)

            # Já parseámos na fase de ranking
            steps = best_steps
            lines = best_lines
            walking_sec = sum(
                int(s.get("duration_minutes", 0) * 60)
                for s in steps
                if s.get("mode") == "WALK"
            )

            self._track_call(time.time() - start)
            return {
                "success": True,
                "origin": origin,
                "destination": destination,
                "duration_minutes": duration_min,
                "departure_time": departure_time.isoformat(),
                "arrival_time": arrival.isoformat(),
                "steps": steps,
                "lines": lines,
                "walking_minutes": round(walking_sec / 60, 1),
                "distance_meters": route.get("distanceMeters", 0),
                "num_transfers": len(lines),
                "alternatives": alternatives,
                "total_routes_found": len(all_routes),
            }

        except Exception as e:
            self._track_call(time.time() - start, error=True)
            self.logger.error("Transit route error: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────────
    # LAYER 2 — TFI GTFS-Realtime (Ireland)
    # ──────────────────────────────────────────────────────────────────────────

    async def get_realtime_delays(
        self, route_short_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Obtém atrasos em tempo real via TFI GTFS-Realtime (Irlanda).

        Args:
            route_short_name: Filtrar por linha específica (ex: "46A", "DART", "Luas Red")
                              Se None, retorna todos os atrasos activos.

        Returns:
            Dict com:
              - delays: lista de {trip_id, route_id, delay_seconds, delay_minutes,
                                   stop_sequence, stop_id, is_cancelled}
              - alerts: alertas de serviço activos
              - has_delays: bool
              - max_delay_minutes: pior atraso em minutos
        """
        if not self._nta_key:
            return {
                "delays": [],
                "alerts": [],
                "has_delays": False,
                "max_delay_minutes": 0,
                "error": "NTA_API_KEY não configurada",
                "note": "Regista-te em developer.nationaltransport.ie (gratuito)",
            }

        if not self.is_initialized():
            await self.initialize()

        delays = await self._fetch_trip_updates(route_short_name)
        alerts = await self._fetch_service_alerts()

        max_delay = max(
            (d["delay_seconds"] for d in delays if d["delay_seconds"] > 0),
            default=0,
        )

        return {
            "delays": delays,
            "alerts": alerts,
            "has_delays": any(
                d["delay_seconds"] >= _DELAY_WARN_THRESHOLD_SEC for d in delays
            ),
            "max_delay_minutes": round(max_delay / 60, 1),
            "total_delays": len(delays),
            "total_alerts": len(alerts),
        }

    async def get_vehicle_positions(
        self, route_short_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtém posições GPS em tempo real dos veículos (TFI).

        Args:
            route_short_name: Filtrar por linha (ex: "46A")

        Returns:
            Lista de {vehicle_id, trip_id, route_id, lat, lng,
                      bearing, speed_kmh, timestamp}
        """
        if not self._nta_key:
            return []

        start = time.time()
        try:
            resp = await self._client.get(
                f"{_NTA_BASE}/VehiclePositions",
                headers={
                    "Ocp-Apim-Subscription-Key": self._nta_key,
                    "Cache-Control": "no-cache",
                },
                params={"format": "json"},
            )
            resp.raise_for_status()

            # Tenta JSON primeiro (se disponível), senão protobuf
            positions = await self._parse_vehicle_positions(resp)

            if route_short_name:
                positions = [
                    p
                    for p in positions
                    if route_short_name.upper() in p.get("route_id", "").upper()
                ]

            self._track_call(time.time() - start)
            return positions

        except Exception as e:
            self._track_call(time.time() - start, error=True)
            self.logger.error("Vehicle positions error: %s", e)
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # LAYER 3 — Combinado (recomendado para LeavingNowService)
    # ──────────────────────────────────────────────────────────────────────────

    async def get_transit_with_delays(
        self,
        origin: str,
        destination: str,
        departure_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Rota de transporte público + atrasos em tempo real combinados.

        Fluxo:
          1. Google Maps Transit → qual linha, horário base
          2. TFI GTFS-RT        → está a linha atrasada?
          3. Combina            → tempo real total + recomendação

        Returns:
            Dict com tudo de get_transit_route() mais:
              - realtime_delay_minutes: atraso real da linha
              - adjusted_duration_minutes: duração ajustada com atraso
              - adjusted_arrival_time: chegada real estimada
              - has_disruption: bool
              - disruption_message: mensagem amigável se houver atraso
              - recommendation: "on_time" | "slight_delay" | "major_delay" | "cancelled"
        """
        if not self.is_initialized():
            await self.initialize()

        # Step 1: Rota base (Google Maps Transit)
        route = await self.get_transit_route(origin, destination, departure_time)

        if not route.get("success"):
            return route

        # Step 2: Verificar atrasos em tempo real (TFI)
        delay_data = {
            "delays": [],
            "alerts": [],
            "has_delays": False,
            "max_delay_minutes": 0,
        }

        if self._nta_key:
            # Tenta obter atrasos para as linhas da rota
            lines = route.get("lines", [])
            for line in lines[:2]:  # verifica as primeiras 2 linhas
                line_name = line.get("short_name", "")
                if line_name:
                    line_delays = await self.get_realtime_delays(line_name)
                    if line_delays.get("has_delays"):
                        delay_data = line_delays
                        break

            # Alertas gerais
            if not delay_data.get("alerts"):
                alerts = await self._fetch_service_alerts()
                delay_data["alerts"] = alerts

        # Step 3: Combina
        base_duration = route["duration_minutes"]
        delay_min = delay_data.get("max_delay_minutes", 0)
        adjusted_duration = base_duration + delay_min

        base_arrival = datetime.fromisoformat(route["arrival_time"])
        adjusted_arrival = base_arrival + timedelta(minutes=delay_min)

        # Determina recomendação
        if any(a.get("is_cancelled") for a in delay_data.get("delays", [])):
            recommendation = "cancelled"
            disruption_msg = "⛔ Serviço cancelado. Verifica alternativas."
        elif delay_min >= 10:
            recommendation = "major_delay"
            disruption_msg = f"⚠️ Atraso de {delay_min:.0f} minutos. Sai mais cedo."
        elif delay_min >= 3:
            recommendation = "slight_delay"
            disruption_msg = f"🟡 Atraso ligeiro de {delay_min:.0f} min."
        else:
            recommendation = "on_time"
            disruption_msg = ""

        # Alertas de serviço em texto
        active_alerts = [
            a.get("header_text", "") or a.get("description_text", "")
            for a in delay_data.get("alerts", [])
            if a.get("header_text") or a.get("description_text")
        ]

        return {
            **route,
            "realtime_delay_minutes": delay_min,
            "adjusted_duration_minutes": adjusted_duration,
            "adjusted_arrival_time": adjusted_arrival.isoformat(),
            "has_disruption": delay_min >= 3 or bool(active_alerts),
            "disruption_message": disruption_msg,
            "recommendation": recommendation,
            "service_alerts": active_alerts[:3],  # máx 3 alertas
            "gtfs_realtime_available": bool(self._nta_key),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Private — geocoding
    # ──────────────────────────────────────────────────────────────────────────

    async def _geocode(self, address: str) -> Optional[Dict[str, float]]:
        """Converte endereço em coordenadas via Google Geocoding API."""
        try:
            resp = await self._client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": address, "key": self._gmaps_key},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "OK" and data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                return {"lat": loc["lat"], "lng": loc["lng"]}
            return None
        except Exception as e:
            self.logger.error("Geocoding error for '%s': %s", address, e)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Private — TFI GTFS-RT parsers
    # ──────────────────────────────────────────────────────────────────────────

    async def _fetch_trip_updates(
        self, route_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Obtém TripUpdates do feed GTFS-RT da TFI."""
        start = time.time()
        try:
            resp = await self._client.get(
                f"{_NTA_BASE}/TripUpdates",
                headers={
                    "Ocp-Apim-Subscription-Key": self._nta_key,
                    "Cache-Control": "no-cache",
                },
            )
            resp.raise_for_status()

            if self._gtfs_available:
                delays = self._parse_trip_updates_proto(resp.content, route_filter)
            else:
                delays = self._parse_trip_updates_json(resp, route_filter)

            self._track_call(time.time() - start)
            return delays

        except Exception as e:
            self._track_call(time.time() - start, error=True)
            self.logger.error("TripUpdates fetch error: %s", e)
            return []

    async def _fetch_service_alerts(self) -> List[Dict[str, Any]]:
        """Obtém alertas de serviço activos do feed GTFS-RT da TFI."""
        if not self._nta_key:
            return []
        start = time.time()
        try:
            resp = await self._client.get(
                f"{_NTA_BASE}/Alerts",
                headers={
                    "Ocp-Apim-Subscription-Key": self._nta_key,
                    "Cache-Control": "no-cache",
                },
            )
            resp.raise_for_status()

            if self._gtfs_available:
                return self._parse_alerts_proto(resp.content)
            return self._parse_alerts_json(resp)

        except Exception as e:
            self._track_call(time.time() - start, error=True)
            self.logger.error("Alerts fetch error: %s", e)
            return []

    @staticmethod
    def _parse_trip_updates_proto(
        content: bytes, route_filter: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Parseia TripUpdates via protobuf (gtfs-realtime-bindings)."""
        try:
            from google.transit import gtfs_realtime_pb2  # type: ignore

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(content)

            delays = []
            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue
                tu = entity.trip_update
                route_id = tu.trip.route_id

                if route_filter and route_filter.upper() not in route_id.upper():
                    continue

                for stu in tu.stop_time_update:
                    delay = 0
                    is_cancelled = False

                    if stu.HasField("departure"):
                        delay = stu.departure.delay or 0
                    elif stu.HasField("arrival"):
                        delay = stu.arrival.delay or 0

                    # schedule_relationship 1 = SKIPPED (cancelado)
                    if stu.schedule_relationship == 1:
                        is_cancelled = True

                    if abs(delay) >= _DELAY_WARN_THRESHOLD_SEC or is_cancelled:
                        delays.append(
                            {
                                "trip_id": tu.trip.trip_id,
                                "route_id": route_id,
                                "stop_sequence": stu.stop_sequence,
                                "stop_id": stu.stop_id,
                                "delay_seconds": delay,
                                "delay_minutes": round(delay / 60, 1),
                                "is_cancelled": is_cancelled,
                            }
                        )

            return delays
        except Exception as e:
            return [{"error": str(e)}]

    @staticmethod
    def _parse_trip_updates_json(
        resp: httpx.Response, route_filter: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Fallback: tenta parsear como JSON se protobuf não disponível."""
        try:
            data = resp.json()
            entities = data.get("entity", [])
            delays = []
            for entity in entities:
                tu = entity.get("tripUpdate", {})
                route_id = tu.get("trip", {}).get("routeId", "")

                if route_filter and route_filter.upper() not in route_id.upper():
                    continue

                for stu in tu.get("stopTimeUpdate", []):
                    delay = (
                        stu.get("departure", {}).get("delay", 0)
                        or stu.get("arrival", {}).get("delay", 0)
                        or 0
                    )
                    is_cancelled = stu.get("scheduleRelationship") == "SKIPPED"

                    if abs(delay) >= _DELAY_WARN_THRESHOLD_SEC or is_cancelled:
                        delays.append(
                            {
                                "trip_id": tu.get("trip", {}).get("tripId", ""),
                                "route_id": route_id,
                                "stop_sequence": stu.get("stopSequence", 0),
                                "stop_id": stu.get("stopId", ""),
                                "delay_seconds": delay,
                                "delay_minutes": round(delay / 60, 1),
                                "is_cancelled": is_cancelled,
                            }
                        )
            return delays
        except Exception:
            return []

    @staticmethod
    def _parse_alerts_proto(content: bytes) -> List[Dict[str, Any]]:
        """Parseia alertas de serviço via protobuf."""
        try:
            from google.transit import gtfs_realtime_pb2  # type: ignore

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(content)

            alerts = []
            for entity in feed.entity:
                if not entity.HasField("alert"):
                    continue
                alert = entity.alert

                header = ""
                if alert.header_text.translation:
                    header = alert.header_text.translation[0].text

                description = ""
                if alert.description_text.translation:
                    description = alert.description_text.translation[0].text

                cause_map = {
                    0: "UNKNOWN",
                    1: "OTHER",
                    2: "TECHNICAL_PROBLEM",
                    3: "STRIKE",
                    4: "DEMONSTRATION",
                    5: "ACCIDENT",
                    6: "HOLIDAY",
                    7: "WEATHER",
                    8: "MAINTENANCE",
                    9: "CONSTRUCTION",
                    10: "POLICE_ACTIVITY",
                    11: "MEDICAL_EMERGENCY",
                }

                alerts.append(
                    {
                        "header_text": header,
                        "description_text": description[:200] if description else "",
                        "cause": cause_map.get(alert.cause, "UNKNOWN"),
                        "severity": alert.effect,
                        "informed_entities": [
                            {"route_id": ie.route_id, "stop_id": ie.stop_id}
                            for ie in alert.informed_entity
                            if ie.route_id or ie.stop_id
                        ][:5],
                    }
                )
            return alerts
        except Exception as e:
            return [{"error": str(e)}]

    @staticmethod
    def _parse_alerts_json(resp: httpx.Response) -> List[Dict[str, Any]]:
        """Fallback: tenta parsear alertas como JSON."""
        try:
            data = resp.json()
            alerts = []
            for entity in data.get("entity", []):
                alert = entity.get("alert", {})
                header = (
                    alert.get("headerText", {})
                    .get("translation", [{}])[0]
                    .get("text", "")
                )
                description = (
                    alert.get("descriptionText", {})
                    .get("translation", [{}])[0]
                    .get("text", "")
                )
                alerts.append(
                    {
                        "header_text": header,
                        "description_text": description[:200],
                        "cause": alert.get("cause", "UNKNOWN"),
                        "severity": alert.get("effect", ""),
                        "informed_entities": [],
                    }
                )
            return alerts
        except Exception:
            return []

    @staticmethod
    async def _parse_vehicle_positions(
        resp: httpx.Response,
    ) -> List[Dict[str, Any]]:
        """Parseia posições de veículos (protobuf ou JSON)."""
        positions = []
        try:
            try:
                from google.transit import gtfs_realtime_pb2  # type: ignore

                feed = gtfs_realtime_pb2.FeedMessage()
                feed.ParseFromString(resp.content)
                for entity in feed.entity:
                    if not entity.HasField("vehicle"):
                        continue
                    vp = entity.vehicle
                    positions.append(
                        {
                            "vehicle_id": vp.vehicle.id,
                            "trip_id": vp.trip.trip_id,
                            "route_id": vp.trip.route_id,
                            "lat": vp.position.latitude,
                            "lng": vp.position.longitude,
                            "bearing": vp.position.bearing,
                            "speed_kmh": round((vp.position.speed or 0) * 3.6, 1),
                            "timestamp": vp.timestamp,
                        }
                    )
            except ImportError:
                # JSON fallback
                data = resp.json()
                for entity in data.get("entity", []):
                    vp = entity.get("vehicle", {})
                    pos = vp.get("position", {})
                    positions.append(
                        {
                            "vehicle_id": vp.get("vehicle", {}).get("id", ""),
                            "trip_id": vp.get("trip", {}).get("tripId", ""),
                            "route_id": vp.get("trip", {}).get("routeId", ""),
                            "lat": pos.get("latitude", 0),
                            "lng": pos.get("longitude", 0),
                            "bearing": pos.get("bearing", 0),
                            "speed_kmh": round((pos.get("speed", 0) or 0) * 3.6, 1),
                            "timestamp": vp.get("timestamp", 0),
                        }
                    )
        except Exception:
            pass
        return positions

    @staticmethod
    def _parse_transit_steps(route: Dict) -> tuple:
        """
        Parseia os passos de uma rota de transporte do Google Maps.

        Returns:
            (steps, lines, total_walking_seconds)
        """
        steps = []
        lines = []
        walking_sec = 0

        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                travel_mode = step.get("travelMode", "")
                nav_instruction = step.get("navigationInstruction", {})
                instruction = nav_instruction.get("instructions", "")
                duration_sec = int(step.get("staticDuration", "0s").replace("s", ""))

                step_data = {
                    "mode": travel_mode,
                    "instruction": instruction,
                    "duration_minutes": round(duration_sec / 60, 1),
                }

                # Detalhes de transporte
                transit_details = step.get("transitDetails", {})
                if transit_details:
                    stop_details = transit_details.get("stopDetails", {})
                    transit_line = transit_details.get("transitLine", {})
                    vehicle = transit_line.get("vehicle", {})

                    line_info = {
                        "short_name": transit_line.get("nameShort", ""),
                        "long_name": transit_line.get("name", ""),
                        "vehicle_type": vehicle.get("type", ""),
                        "vehicle_name": vehicle.get("name", {}).get("text", ""),
                        "color": transit_line.get("color", ""),
                        "agency": (
                            transit_line.get("agencies", [{}])[0].get("name", "")
                            if transit_line.get("agencies")
                            else ""
                        ),
                        "departure_stop": (
                            stop_details.get("departureStop", {}).get("name", "")
                        ),
                        "arrival_stop": (
                            stop_details.get("arrivalStop", {}).get("name", "")
                        ),
                        "departure_time": (
                            transit_details.get("localizedValues", {})
                            .get("departureTime", {})
                            .get("time", {})
                            .get("text", "")
                        ),
                        "arrival_time": (
                            transit_details.get("localizedValues", {})
                            .get("arrivalTime", {})
                            .get("time", {})
                            .get("text", "")
                        ),
                        "num_stops": transit_details.get("stopCount", 0),
                        "headsign": transit_details.get("headsign", ""),
                    }
                    step_data["transit"] = line_info
                    if line_info["short_name"]:
                        lines.append(line_info)

                if travel_mode == "WALK":
                    walking_sec += duration_sec

                steps.append(step_data)

        return steps, lines, walking_sec
