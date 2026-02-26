"""
Capivarex i18n — Centralized string catalog.

All user-facing hardcoded strings live here.
English is the source of truth (English-first product).

Usage:
    from services.i18n.strings import t, get_user_lang

    lang = get_user_lang(context)
    t("error_processing", lang=lang)
    t("tts_error", lang=lang, error="timeout")

Adding a new language:
    1. Add the 2-letter code to SUPPORTED_LANGS
    2. Add translations to each entry in STRINGS
    3. That's it — the fallback chain handles the rest
"""

from typing import Any, Dict, Optional


# ─── Supported languages ──────────────────────────────────────────────────────
SUPPORTED_LANGS = {"en", "pt", "es"}
DEFAULT_LANG = "en"


# ─── String catalog ───────────────────────────────────────────────────────────
# Keys are descriptive English slugs.
# Values are dicts mapping language code → translated string.
# Use {placeholder} for dynamic values (filled via t(key, lang, **kwargs)).

STRINGS: Dict[str, Dict[str, str]] = {
    # ══════════════════════════════════════════════════════════════════════════
    # GENERIC / SHARED
    # ══════════════════════════════════════════════════════════════════════════
    "error_processing": {
        "en": "Sorry, I couldn't process your message right now.",
        "pt": "Desculpe, não consegui processar sua mensagem agora.",
        "es": "Lo siento, no pude procesar tu mensaje ahora.",
    },
    "error_unexpected": {
        "en": "Unexpected error. Please try again.",
        "pt": "Erro inesperado. Tenta novamente.",
        "es": "Error inesperado. Intenta de nuevo.",
    },
    "agent_unavailable": {
        "en": "Agent '{agent}' is not available.",
        "pt": "Agente '{agent}' não disponível.",
        "es": "Agente '{agent}' no disponible.",
    },
    "service_unavailable": {
        "en": "{service} service is unavailable.",
        "pt": "Serviço de {service} não disponível.",
        "es": "Servicio de {service} no disponible.",
    },
    "user_not_identified": {
        "en": "User not identified.",
        "pt": "Utilizador não identificado.",
        "es": "Usuario no identificado.",
    },
    "quota_exceeded_generic": {
        "en": "Quota exceeded for {feature}. Check your plan or wait for renewal.",
        "pt": "Quota esgotada para {feature}. Verifica o teu plano ou aguarda a renovação.",
        "es": "Cuota agotada para {feature}. Verifica tu plan o espera la renovación.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # VOICE AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "tts_empty_text": {
        "en": "Error: Empty text for audio conversion.",
        "pt": "Erro: Texto vazio para conversão em áudio.",
        "es": "Error: Texto vacío para conversión a audio.",
    },
    "tts_empty_after_strip": {
        "en": "Error: Text became empty after removing formatting.",
        "pt": "Erro: Texto ficou vazio após remoção de formatação.",
        "es": "Error: El texto quedó vacío después de eliminar el formato.",
    },
    "tts_success": {
        "en": "Audio generated successfully.",
        "pt": "Áudio gerado com sucesso.",
        "es": "Audio generado con éxito.",
    },
    "tts_quota_exceeded": {
        "en": "Voice quota reached. Try again later.",
        "pt": "Quota de voz atingida. Tenta mais tarde.",
        "es": "Cuota de voz alcanzada. Intenta más tarde.",
    },
    "tts_invalid_key": {
        "en": "ElevenLabs key is invalid or expired.",
        "pt": "Chave ElevenLabs inválida ou expirada.",
        "es": "Clave de ElevenLabs inválida o expirada.",
    },
    "tts_error": {
        "en": "Error generating audio: {error}",
        "pt": "Erro ao gerar áudio: {error}",
        "es": "Error al generar audio: {error}",
    },
    "stt_no_audio": {
        "en": "No audio file provided.",
        "pt": "Nenhum ficheiro de áudio fornecido.",
        "es": "No se proporcionó archivo de audio.",
    },
    "stt_error": {
        "en": "Transcription error: {error}",
        "pt": "Erro na transcrição: {error}",
        "es": "Error en la transcripción: {error}",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # TWILIO AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "twilio_quota_exceeded": {
        "en": "📞 Call quota exhausted. Check your plan or wait for renewal.",
        "pt": "📞 Quota de chamadas esgotada. Verifica o teu plano ou aguarda a renovação.",
        "es": "📞 Cuota de llamadas agotada. Verifica tu plan o espera la renovación.",
    },
    "twilio_call_success": {
        "en": "📞 Call initiated!\n• To: {to}\n• From: {from_num}\n• Status: {status}",
        "pt": "📞 Chamada iniciada!\n• Para: {to}\n• De: {from_num}\n• Status: {status}",
        "es": "📞 Llamada iniciada!\n• Para: {to}\n• Desde: {from_num}\n• Estado: {status}",
    },
    "twilio_no_phone": {
        "en": "I didn't detect a phone number. Try: 'call +1234567890'",
        "pt": "Não detectei um número de telefone. Tenta: 'liga para +351912345678'",
        "es": "No detecté un número de teléfono. Intenta: 'llama al +34612345678'",
    },
    "twilio_error": {
        "en": "Error making call: {error}",
        "pt": "Erro ao fazer chamada: {error}",
        "es": "Error al hacer la llamada: {error}",
    },
    "twilio_default_message": {
        "en": "Hello! This is an automated call from Capivarex, your intelligent personal assistant.",
        "pt": "Olá! Esta é uma chamada automática do Capivarex, o seu assistente pessoal inteligente.",
        "es": "¡Hola! Esta es una llamada automática de Capivarex, tu asistente personal inteligente.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # CALENDAR AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "calendar_service_unavailable": {
        "en": "Calendar service unavailable. Check your authorization.",
        "pt": "Serviço de calendário não disponível. Verifique a autorização.",
        "es": "Servicio de calendario no disponible. Verifica la autorización.",
    },
    "calendar_connect_failed": {
        "en": "Could not connect to your calendar. Check the authorization.",
        "pt": "Não consegui conectar ao seu calendário. Verifique a autorização.",
        "es": "No pude conectar con tu calendario. Verifica la autorización.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # WEATHER AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "weather_service_unavailable": {
        "en": "Weather service unavailable.",
        "pt": "Serviço de clima não disponível.",
        "es": "Servicio de clima no disponible.",
    },
    "weather_location_not_found": {
        "en": "Could not identify the city. Try:\n'Weather in Dublin' or 'Weather in São Paulo'",
        "pt": "Não consegui identificar a cidade. Tente:\n'Clima em Dublin' ou 'Clima em São Paulo'",
        "es": "No pude identificar la ciudad. Intenta:\n'Clima en Dublín' o 'Clima en São Paulo'",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # FINANCE AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "finance_service_unavailable": {
        "en": "Financial service unavailable.",
        "pt": "Serviço financeiro não disponível.",
        "es": "Servicio financiero no disponible.",
    },
    "finance_no_ticker": {
        "en": "Could not identify the ticker for financial query.",
        "pt": "Não foi possível identificar o ticker para consulta financeira.",
        "es": "No fue posible identificar el ticker para la consulta financiera.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # CRYPTO AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "crypto_service_unavailable": {
        "en": "Cryptocurrency service unavailable.",
        "pt": "Serviço de criptomoedas não disponível.",
        "es": "Servicio de criptomonedas no disponible.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # IMAGE AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "image_service_unavailable": {
        "en": "Image generation service unavailable.",
        "pt": "Serviço de geração de imagem não disponível.",
        "es": "Servicio de generación de imagen no disponible.",
    },
    "image_empty_prompt": {
        "en": "Empty image prompt.",
        "pt": "Prompt de imagem vazio.",
        "es": "Prompt de imagen vacío.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # VIDEO AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "video_service_unavailable": {
        "en": "Video generation service unavailable.",
        "pt": "Serviço de geração de vídeo não disponível.",
        "es": "Servicio de generación de video no disponible.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # TRAFFIC AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "traffic_service_unavailable": {
        "en": "Traffic service unavailable.",
        "pt": "Serviço de tráfego não disponível.",
        "es": "Servicio de tráfico no disponible.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # CAR AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "car_service_unavailable": {
        "en": "Vehicle service unavailable.",
        "pt": "Serviço de veículo não disponível.",
        "es": "Servicio de vehículo no disponible.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # SMARTHOME AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "smarthome_service_unavailable": {
        "en": "Smart home service unavailable.",
        "pt": "Serviço de casa inteligente não disponível.",
        "es": "Servicio de casa inteligente no disponible.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # RESEARCH AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "research_empty_query": {
        "en": "I didn't receive a query to research.",
        "pt": "Não recebi uma consulta para pesquisa.",
        "es": "No recibí una consulta para investigar.",
    },
    "research_service_unavailable": {
        "en": "Research service unavailable.",
        "pt": "Serviço de pesquisa não disponível.",
        "es": "Servicio de investigación no disponible.",
    },
    "research_error": {
        "en": "Could not complete the research at this time.",
        "pt": "Não foi possível concluir a pesquisa no momento.",
        "es": "No fue posible completar la investigación en este momento.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # SEARCH AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "search_empty_query": {
        "en": "What should I search for? Try: *Search Italian restaurants in Dublin*",
        "pt": "O que devo buscar? Tente: *Busca restaurantes italianos em Dublin*",
        "es": "¿Qué debo buscar? Intenta: *Busca restaurantes italianos en Dublín*",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # RESTAURANT AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "restaurant_service_unavailable": {
        "en": "Restaurant service unavailable.",
        "pt": "Serviço de restaurantes não disponível.",
        "es": "Servicio de restaurantes no disponible.",
    },
    "restaurant_not_understood": {
        "en": "I didn't understand the request. Examples:\n"
        "• 'Find Italian restaurants near me'\n"
        "• 'Restaurant details #2'\n"
        "• 'Save restaurant #1 as favorite'\n"
        "• 'Show my favorite restaurants'",
        "pt": "Não percebi o pedido. Exemplos:\n"
        "• 'Busca restaurantes italianos perto de mim'\n"
        "• 'Detalhes do restaurante #2'\n"
        "• 'Guardar restaurante #1 como favorito'\n"
        "• 'Mostra os meus restaurantes favoritos'",
        "es": "No entendí la solicitud. Ejemplos:\n"
        "• 'Busca restaurantes italianos cerca de mí'\n"
        "• 'Detalles del restaurante #2'\n"
        "• 'Guardar restaurante #1 como favorito'\n"
        "• 'Muestra mis restaurantes favoritos'",
    },
    "restaurant_search_error": {
        "en": "Error searching restaurants: {error}",
        "pt": "Erro ao pesquisar restaurantes: {error}",
        "es": "Error al buscar restaurantes: {error}",
    },
    "restaurant_only_n_results": {
        "en": "I only have {count} restaurant(s) in the list.",
        "pt": "Só tenho {count} restaurante(s) na lista.",
        "es": "Solo tengo {count} restaurante(s) en la lista.",
    },
    "restaurant_details_error": {
        "en": "Could not get details for this restaurant.",
        "pt": "Não foi possível obter detalhes deste restaurante.",
        "es": "No fue posible obtener detalles de este restaurante.",
    },
    "restaurant_search_first": {
        "en": "Search for restaurants first so I can save one.",
        "pt": "Faz primeiro uma pesquisa para eu poder guardar.",
        "es": "Haz primero una búsqueda para que pueda guardar.",
    },
    "restaurant_no_favorites": {
        "en": "You don't have any favorite restaurants yet.",
        "pt": "Ainda não tens restaurantes favoritos.",
        "es": "Aún no tienes restaurantes favoritos.",
    },
    "restaurant_saved_favorite": {
        "en": "⭐ '{name}' saved as favorite!",
        "pt": "⭐ '{name}' guardado como favorito!",
        "es": "⭐ '{name}' guardado como favorito!",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # NOTES AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "notes_not_understood": {
        "en": "I didn't understand what you want to do with notes. Examples:\n"
        "• 'Write a note: buy milk'\n"
        "• 'Show my notes'\n"
        "• 'Search notes about project'\n"
        "• 'Delete note #3'",
        "pt": "Não percebi o que queres fazer. Exemplos:\n"
        "• 'Anota: comprar leite'\n"
        "• 'Mostra as minhas notas'\n"
        "• 'Busca notas sobre projeto'\n"
        "• 'Apaga a nota #3'",
        "es": "No entendí qué quieres hacer con las notas. Ejemplos:\n"
        "• 'Anota: comprar leche'\n"
        "• 'Muestra mis notas'\n"
        "• 'Busca notas sobre proyecto'\n"
        "• 'Borrar nota #3'",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # YOUTUBE AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "youtube_service_unavailable": {
        "en": "YouTube service unavailable.",
        "pt": "Serviço do YouTube não disponível.",
        "es": "Servicio de YouTube no disponible.",
    },
    "youtube_quota_exceeded": {
        "en": "⚠ YouTube API quota exceeded. Try again tomorrow.",
        "pt": "⚠ Quota da YouTube API excedida. Tente novamente amanhã.",
        "es": "⚠ Cuota de la API de YouTube excedida. Intenta mañana.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # TRACKING AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "tracking_service_unavailable": {
        "en": "Tracking service unavailable.",
        "pt": "Serviço de rastreamento não disponível.",
        "es": "Servicio de rastreo no disponible.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # MERCADO AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "mercado_service_unavailable": {
        "en": "Shopping list service unavailable.",
        "pt": "Serviço de mercado não disponível.",
        "es": "Servicio de lista de compras no disponible.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # TRANSPORT AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "transport_service_unavailable": {
        "en": "Public transport service unavailable.",
        "pt": "Serviço de transporte público não disponível.",
        "es": "Servicio de transporte público no disponible.",
    },
    "transport_no_origin": {
        "en": "I need your origin location. Where are you?",
        "pt": "Preciso da sua localização de origem. Onde você está?",
        "es": "Necesito tu ubicación de origen. ¿Dónde estás?",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # EMAIL AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "email_service_unavailable": {
        "en": "Email service unavailable.",
        "pt": "Serviço de email não disponível.",
        "es": "Servicio de email no disponible.",
    },
    "email_sent_success": {
        "en": "✅ Email sent to {to}.",
        "pt": "✅ Email enviado para {to}.",
        "es": "✅ Email enviado a {to}.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # REMINDER AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "reminder_created": {
        "en": "⏰ Reminder set: {text}",
        "pt": "⏰ Lembrete criado: {text}",
        "es": "⏰ Recordatorio creado: {text}",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # TIMER AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "timer_created": {
        "en": "⏱ Timer set for {duration}.",
        "pt": "⏱ Temporizador definido para {duration}.",
        "es": "⏱ Temporizador establecido para {duration}.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # TRANSLATE AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "translate_service_unavailable": {
        "en": "Translation service unavailable.",
        "pt": "Serviço de tradução não disponível.",
        "es": "Servicio de traducción no disponible.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # GITHUB AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "github_service_unavailable": {
        "en": "GitHub service unavailable.",
        "pt": "Serviço GitHub não disponível.",
        "es": "Servicio de GitHub no disponible.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # DEV AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "dev_service_unavailable": {
        "en": "Developer service unavailable.",
        "pt": "Serviço de desenvolvimento não disponível.",
        "es": "Servicio de desarrollo no disponible.",
    },
}


# ─── Translation function ─────────────────────────────────────────────────────


def t(key: str, lang: str = DEFAULT_LANG, **kwargs: Any) -> str:
    """
    Translate a string key to the given language.

    Args:
        key: String identifier (e.g., "error_processing")
        lang: 2-letter language code (e.g., "en", "pt", "es")
        **kwargs: Format placeholders (e.g., error="timeout")

    Returns:
        Translated string with placeholders filled

    Examples:
        t("error_processing", lang="pt")
        → "Desculpe, não consegui processar sua mensagem agora."

        t("tts_error", lang="en", error="timeout")
        → "Error generating audio: timeout"

        t("twilio_call_success", lang="es", to="+34...", from_num="+1...")
        → "📞 Llamada iniciada!\\n• Para: +34...\\n• Desde: +1...\\n• Estado: ..."
    """
    # Normalize language code
    lang = (lang or DEFAULT_LANG)[:2].lower()
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG

    entry = STRINGS.get(key, {})

    # Fallback chain: requested lang → English → raw key
    text = entry.get(lang, entry.get(DEFAULT_LANG, key))

    # Fill placeholders
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass  # Return unformatted if placeholders don't match

    return text


# ─── User language detection ──────────────────────────────────────────────────


def get_user_lang(context: Optional[Dict[str, Any]] = None) -> str:
    """
    Detect user language from context.

    Priority:
    1. context["lang"] — explicitly set (e.g., by bot handler)
    2. user_preferences.language — saved preference from DB
    3. context["language_code"] — Telegram language_code
    4. DEFAULT_LANG ("en")

    Args:
        context: Agent execution context dict

    Returns:
        2-letter language code ("en", "pt", or "es")
    """
    if not context:
        return DEFAULT_LANG

    # 1. Explicitly set lang in context (highest priority)
    explicit = context.get("lang", "")
    if explicit:
        code = explicit[:2].lower()
        if code in SUPPORTED_LANGS:
            return code

    # 2. User preference from DB (check both column names)
    prefs = context.get("user_preferences", {})
    if isinstance(prefs, dict):
        pref_lang = prefs.get("preferred_language") or prefs.get("language", "")
        if pref_lang:
            code = pref_lang[:2].lower()
            if code in SUPPORTED_LANGS:
                return code

    # 3. Telegram language_code
    tg_lang = context.get("language_code", "")
    if tg_lang:
        code = tg_lang[:2].lower()
        if code in SUPPORTED_LANGS:
            return code

    return DEFAULT_LANG
