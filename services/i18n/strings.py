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
        "pt": "Erro inesperado. Tente novamente.",
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
        "pt": "Usuário não identificado.",
        "es": "Usuario no identificado.",
    },
    "quota_exceeded_generic": {
        "en": "Quota exceeded for {feature}. Check your plan or wait for renewal.",
        "pt": "Quota esgotada para {feature}. Verifique seu plano ou aguarde a renovação.",
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
        "pt": "Quota de voz atingida. Tente mais tarde.",
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
        "pt": "Nenhum arquivo de áudio fornecido.",
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
        "pt": "📞 Quota de chamadas esgotada. Verifique seu plano ou aguarde a renovação.",
        "es": "📞 Cuota de llamadas agotada. Verifica tu plan o espera la renovación.",
    },
    "twilio_call_success": {
        "en": "📞 Call initiated!\n• To: {to}\n• From: {from_num}\n• Status: {status}",
        "pt": "📞 Chamada iniciada!\n• Para: {to}\n• De: {from_num}\n• Status: {status}",
        "es": "📞 Llamada iniciada!\n• Para: {to}\n• Desde: {from_num}\n• Estado: {status}",
    },
    "twilio_no_phone": {
        "en": "I didn't detect a phone number. Try: 'call +1234567890'",
        "pt": "Não detectei um número de telefone. Tente: 'liga para +351912345678'",
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
        "en": "Smart home service unavailable. Check the configuration.",
        "pt": "Serviço SmartThings não disponível. Verifique a configuração.",
        "es": "Servicio de casa inteligente no disponible. Verifica la configuración.",
    },
    "smarthome_not_connected": {
        "en": "🏠 SmartThings not connected\n\n"
        "Click the link below to connect your Samsung/SmartThings account:\n\n"
        "🔗 {url}\n\n"
        "After authorizing, your devices will become available.",
        "pt": "🏠 SmartThings não conectado\n\n"
        "Clique no link abaixo para conectar sua conta Samsung/SmartThings:\n\n"
        "🔗 {url}\n\n"
        "Após autorizar, seus dispositivos ficarão disponíveis.",
        "es": "🏠 SmartThings no conectado\n\n"
        "Haz clic en el enlace para conectar tu cuenta Samsung/SmartThings:\n\n"
        "🔗 {url}\n\n"
        "Después de autorizar, tus dispositivos estarán disponibles.",
    },
    "smarthome_not_connected_no_config": {
        "en": "🏠 SmartThings not connected\n\n"
        "Configure SMARTTHINGS_CLIENT_ID and SMARTTHINGS_REDIRECT_URI on Railway.",
        "pt": "🏠 SmartThings não conectado\n\n"
        "Configure SMARTTHINGS_CLIENT_ID e SMARTTHINGS_REDIRECT_URI no Railway.",
        "es": "🏠 SmartThings no conectado\n\n"
        "Configura SMARTTHINGS_CLIENT_ID y SMARTTHINGS_REDIRECT_URI en Railway.",
    },
    "smarthome_no_devices": {
        "en": "No devices found on your SmartThings account.",
        "pt": "Nenhum dispositivo encontrado na sua conta SmartThings.",
        "es": "No se encontraron dispositivos en tu cuenta SmartThings.",
    },
    "smarthome_devices_header": {
        "en": "🏠 Your SmartThings Devices\n",
        "pt": "🏠 Seus Dispositivos SmartThings\n",
        "es": "🏠 Tus Dispositivos SmartThings\n",
    },
    "smarthome_devices_total": {
        "en": "\nTotal: {count} devices",
        "pt": "\nTotal: {count} dispositivos",
        "es": "\nTotal: {count} dispositivos",
    },
    "smarthome_device_unnamed": {
        "en": "Unnamed",
        "pt": "Sem nome",
        "es": "Sin nombre",
    },
    "smarthome_device_unknown_type": {
        "en": "Unknown",
        "pt": "Desconhecido",
        "es": "Desconocido",
    },
    "smarthome_device_not_found": {
        "en": "Device '{name}' not found.\nSay 'list devices' to see all available.",
        "pt": "Não encontrei o dispositivo '{name}'.\nDiga 'listar dispositivos' para ver todos os disponíveis.",
        "es": "No encontré el dispositivo '{name}'.\nDi 'listar dispositivos' para ver todos los disponibles.",
    },
    "smarthome_lock_not_found": {
        "en": "Lock not found. Say 'list devices' to see all available.",
        "pt": "Não encontrei a fechadura. Diga 'listar dispositivos' para ver todos.",
        "es": "No encontré la cerradura. Di 'listar dispositivos' para ver todos.",
    },
    "smarthome_thermostat_not_found": {
        "en": "Thermostat not found. Say 'list devices' to see all available.",
        "pt": "Não encontrei o termostato. Diga 'listar dispositivos' para ver todos.",
        "es": "No encontré el termostato. Di 'listar dispositivos' para ver todos.",
    },
    "smarthome_turned_on": {
        "en": "✅ {label} turned on!",
        "pt": "✅ {label} ligado!",
        "es": "✅ {label} encendido!",
    },
    "smarthome_turned_on_brightness": {
        "en": "💡 {label} turned on with brightness at {brightness}%!",
        "pt": "💡 {label} ligado com brilho em {brightness}%!",
        "es": "💡 {label} encendido con brillo al {brightness}%!",
    },
    "smarthome_turn_on_error": {
        "en": "❌ Error turning on {label}.",
        "pt": "❌ Erro ao ligar {label}.",
        "es": "❌ Error al encender {label}.",
    },
    "smarthome_turned_off": {
        "en": "⭕ {label} turned off!",
        "pt": "⭕ {label} desligado!",
        "es": "⭕ {label} apagado!",
    },
    "smarthome_turn_off_error": {
        "en": "❌ Error turning off {label}.",
        "pt": "❌ Erro ao desligar {label}.",
        "es": "❌ Error al apagar {label}.",
    },
    "smarthome_brightness_set": {
        "en": "💡 {label} brightness set to {brightness}%!",
        "pt": "💡 Brilho de {label} ajustado para {brightness}%!",
        "es": "💡 Brillo de {label} ajustado al {brightness}%!",
    },
    "smarthome_brightness_error": {
        "en": "❌ Error adjusting brightness of {label}.",
        "pt": "❌ Erro ao ajustar brilho de {label}.",
        "es": "❌ Error al ajustar brillo de {label}.",
    },
    "smarthome_locked": {
        "en": "🔒 {label} locked!",
        "pt": "🔒 {label} trancado!",
        "es": "🔒 {label} bloqueado!",
    },
    "smarthome_lock_error": {
        "en": "❌ Error locking {label}.",
        "pt": "❌ Erro ao trancar {label}.",
        "es": "❌ Error al bloquear {label}.",
    },
    "smarthome_unlocked": {
        "en": "🔓 {label} unlocked!",
        "pt": "🔓 {label} destrancado!",
        "es": "🔓 {label} desbloqueado!",
    },
    "smarthome_unlock_error": {
        "en": "❌ Error unlocking {label}.",
        "pt": "❌ Erro ao destrancar {label}.",
        "es": "❌ Error al desbloquear {label}.",
    },
    "smarthome_thermostat_set": {
        "en": "🌡️ {label} set to {temperature}°C!",
        "pt": "🌡️ {label} ajustado para {temperature}°C!",
        "es": "🌡️ {label} ajustado a {temperature}°C!",
    },
    "smarthome_thermostat_error": {
        "en": "❌ Error adjusting temperature of {label}.",
        "pt": "❌ Erro ao ajustar temperatura de {label}.",
        "es": "❌ Error al ajustar temperatura de {label}.",
    },
    "smarthome_status_label": {
        "en": "📊 Status: {label}\n\nState: {state}",
        "pt": "📊 Status: {label}\n\nEstado: {state}",
        "es": "📊 Estado: {label}\n\nEstado: {state}",
    },
    "smarthome_status_on": {
        "en": "On ✅",
        "pt": "Ligado ✅",
        "es": "Encendido ✅",
    },
    "smarthome_status_off": {
        "en": "Off ⭕",
        "pt": "Desligado ⭕",
        "es": "Apagado ⭕",
    },
    "smarthome_temperature_label": {
        "en": "\nTemperature: {value}°C",
        "pt": "\nTemperatura: {value}°C",
        "es": "\nTemperatura: {value}°C",
    },
    "smarthome_humidity_label": {
        "en": "\nHumidity: {value}%",
        "pt": "\nUmidade: {value}%",
        "es": "\nHumedad: {value}%",
    },
    "smarthome_brightness_label": {
        "en": "\nBrightness: {value}%",
        "pt": "\nBrilho: {value}%",
        "es": "\nBrillo: {value}%",
    },
    "smarthome_ai_unavailable": {
        "en": "AI service unavailable to answer your question.",
        "pt": "Serviço de IA não disponível para responder sua pergunta.",
        "es": "Servicio de IA no disponible para responder tu pregunta.",
    },
    "smarthome_general_error": {
        "en": "Error processing your question: {error}",
        "pt": "Erro ao processar sua pergunta: {error}",
        "es": "Error al procesar tu pregunta: {error}",
    },
    "smarthome_command_error": {
        "en": "Error processing smart home command: {error}",
        "pt": "Erro ao processar comando de casa inteligente: {error}",
        "es": "Error al procesar comando de casa inteligente: {error}",
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
    "search_places_header": {
        "en": "📍 **Places found for: _{query}_**",
        "pt": "📍 **Lugares encontrados para: _{query}_**",
        "es": "📍 **Lugares encontrados para: _{query}_**",
    },
    "search_shopping_header": {
        "en": "🛍️ **Products found for: _{query}_**",
        "pt": "🛍️ **Produtos encontrados para: _{query}_**",
        "es": "🛍️ **Productos encontrados para: _{query}_**",
    },
    "search_news_header": {
        "en": "📰 **News about: _{query}_**",
        "pt": "📰 **Notícias sobre: _{query}_**",
        "es": "📰 **Noticias sobre: _{query}_**",
    },
    "search_general_header": {
        "en": "🔍 **Results for: _{query}_**",
        "pt": "🔍 **Resultados para: _{query}_**",
        "es": "🔍 **Resultados para: _{query}_**",
    },
    "search_images_header": {
        "en": "🖼️ **Images found for: _{query}_**",
        "pt": "🖼️ **Imagens encontradas para: _{query}_**",
        "es": "🖼️ **Imágenes encontradas para: _{query}_**",
    },
    "search_no_places": {
        "en": "No places found for: *{query}*",
        "pt": "Não encontrei nenhum lugar para: *{query}*",
        "es": "No encontré ningún lugar para: *{query}*",
    },
    "search_no_products": {
        "en": "No products found for: *{query}*",
        "pt": "Não encontrei produtos para: *{query}*",
        "es": "No encontré productos para: *{query}*",
    },
    "search_no_news": {
        "en": "No recent news found about: *{query}*",
        "pt": "Não encontrei notícias recentes sobre: *{query}*",
        "es": "No encontré noticias recientes sobre: *{query}*",
    },
    "search_no_results": {
        "en": "No results found for: *{query}*",
        "pt": "Não encontrei resultados para: *{query}*",
        "es": "No encontré resultados para: *{query}*",
    },
    "search_no_images": {
        "en": "No images found for: *{query}*",
        "pt": "Não encontrei imagens para: *{query}*",
        "es": "No encontré imágenes para: *{query}*",
    },
    "search_service_unavailable": {
        "en": "Search service not available.\nSet the `SERPER_API_KEY` in `.env`.\nFree signup: https://serper.dev",
        "pt": "Serviço de busca não disponível.\nConfigure a `SERPER_API_KEY` no `.env`.\nCadastro gratuito: https://serper.dev",
        "es": "Servicio de búsqueda no disponible.\nConfigure la `SERPER_API_KEY` en `.env`.\nRegistro gratuito: https://serper.dev",
    },
    "search_not_configured": {
        "en": "⚙️ Search service not configured.\nAdd the `SERPER_API_KEY` to `.env`.\nFree signup: https://serper.dev",
        "pt": "⚙️ Serviço de busca não configurado.\nAdicione a `SERPER_API_KEY` no `.env`.\nCadastro gratuito: https://serper.dev",
        "es": "⚙️ Servicio de búsqueda no configurado.\nAñada la `SERPER_API_KEY` al `.env`.\nRegistro gratuito: https://serper.dev",
    },
    "search_quota_exceeded": {
        "en": "⚠️ Serper search quota reached (2,500/month on free plan).\nCheck at serper.dev → Usage.",
        "pt": "⚠️ Limite de buscas Serper atingido (2.500/mês no plano free).\nVerifique em serper.dev → Usage.",
        "es": "⚠️ Cuota de búsquedas Serper agotada (2.500/mes en plan gratuito).\nVerifique en serper.dev → Usage.",
    },
    "search_error": {
        "en": "Search error: {error}",
        "pt": "Erro na busca: {error}",
        "es": "Error en la búsqueda: {error}",
    },
    "search_unexpected_error": {
        "en": "Unexpected search error. Please try again.",
        "pt": "Erro inesperado na busca. Tente novamente.",
        "es": "Error inesperado en la búsqueda. Intente de nuevo.",
    },
    "search_reviews": {
        "en": "{count} reviews",
        "pt": "{count} avaliações",
        "es": "{count} reseñas",
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
        "pt": "Não entendi o pedido. Exemplos:\n"
        "• 'Busca restaurantes italianos perto de mim'\n"
        "• 'Detalhes do restaurante #2'\n"
        "• 'Salvar restaurante #1 como favorito'\n"
        "• 'Mostre meus restaurantes favoritos'",
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
        "pt": "Faça primeiro uma pesquisa para eu poder salvar.",
        "es": "Haz primero una búsqueda para que pueda guardar.",
    },
    "restaurant_no_favorites": {
        "en": "You don't have any favorite restaurants yet.",
        "pt": "Você ainda não tem restaurantes favoritos.",
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
        "pt": "Não entendi o que você quer fazer. Exemplos:\n"
        "• 'Anota: comprar leite'\n"
        "• 'Mostre minhas notas'\n"
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
    # TRAVEL AGENT (hotel/stay search)
    # ══════════════════════════════════════════════════════════════════════════
    "hotel_need_location": {
        "en": "🏨 I need a city or location to search for hotels.\n\n"
        'Example: "Hotel in Paris from April 15 to April 18"',
        "pt": "🏨 Preciso de uma cidade ou localização para buscar hotéis.\n\n"
        'Exemplo: "Hotel em Paris de 15 a 18 de abril"',
        "es": "🏨 Necesito una ciudad o ubicación para buscar hoteles.\n\n"
        'Ejemplo: "Hotel en París del 15 al 18 de abril"',
    },
    "hotel_need_dates": {
        "en": "🏨 I need check-in and check-out dates to search for hotels.\n\n"
        'Example: "Hotel in Dublin from March 20 for 3 nights"',
        "pt": "🏨 Preciso das datas de check-in e check-out para buscar hotéis.\n\n"
        'Exemplo: "Hotel em Dublin a partir de 20 de março por 3 noites"',
        "es": "🏨 Necesito las fechas de check-in y check-out para buscar hoteles.\n\n"
        'Ejemplo: "Hotel en Dublín desde el 20 de marzo por 3 noches"',
    },
    "hotel_search_result": {
        "en": "🏨 **Hotels in {city}**\n"
        "📅 {checkin} → {checkout} | 👥 {adults} adult(s) | 🛏️ {rooms} room(s)\n\n"
        "🔗 [Search on Booking.com]({url})\n\n"
        "Click the link above to see available hotels with prices and reviews. "
        "You can filter by stars, price range, and amenities on Booking.com.",
        "pt": "🏨 **Hotéis em {city}**\n"
        "📅 {checkin} → {checkout} | 👥 {adults} adulto(s) | 🛏️ {rooms} quarto(s)\n\n"
        "🔗 [Pesquisar no Booking.com]({url})\n\n"
        "Clique no link acima para ver hotéis disponíveis com preços e avaliações. "
        "Pode filtrar por estrelas, faixa de preço e comodidades no Booking.com.",
        "es": "🏨 **Hoteles en {city}**\n"
        "📅 {checkin} → {checkout} | 👥 {adults} adulto(s) | 🛏️ {rooms} habitación(es)\n\n"
        "🔗 [Buscar en Booking.com]({url})\n\n"
        "Haz clic en el enlace para ver hoteles disponibles con precios y reseñas. "
        "Puedes filtrar por estrellas, rango de precios y comodidades en Booking.com.",
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
    # ══════════════════════════════════════════════════════════════════════════
    # MUSIC AGENT
    # ══════════════════════════════════════════════════════════════════════════
    "music_no_results": {
        "en": "🎵 No music found.",
        "pt": "🎵 Nenhuma música encontrada.",
        "es": "🎵 No se encontró música.",
    },
    "music_no_results_for": {
        "en": '🎵 No music found for "{query}".',
        "pt": '🎵 Nenhuma música encontrada para "{query}".',
        "es": '🎵 No se encontró música para "{query}".',
    },
    "music_artist_not_found": {
        "en": '🎤 Artist "{query}" not found.',
        "pt": '🎤 Artista "{query}" não encontrado.',
        "es": '🎤 Artista "{query}" no encontrado.',
    },
    "music_album_not_found": {
        "en": '💿 Album "{query}" not found.',
        "pt": '💿 Álbum "{query}" não encontrado.',
        "es": '💿 Álbum "{query}" no encontrado.',
    },
    "music_listen_on_spotify": {
        "en": "Listen on Spotify",
        "pt": "Ouvir no Spotify",
        "es": "Escuchar en Spotify",
    },
    "music_view_on_spotify": {
        "en": "View on Spotify",
        "pt": "Ver no Spotify",
        "es": "Ver en Spotify",
    },
    "music_popularity": {
        "en": "Popularity",
        "pt": "Popularidade",
        "es": "Popularidad",
    },
    "music_followers": {
        "en": "followers",
        "pt": "seguidores",
        "es": "seguidores",
    },
    "music_tracks_count": {
        "en": "tracks",
        "pt": "faixas",
        "es": "canciones",
    },
    "music_top_tracks_header": {
        "en": "🔝 *Top tracks by {artist}:*\n\n",
        "pt": "🔝 *Top músicas de {artist}:*\n\n",
        "es": "🔝 *Top canciones de {artist}:*\n\n",
    },
    "music_recommendations_header": {
        "en": "🎶 *Recommendations for you:*\n\n",
        "pt": "🎶 *Recomendações para você:*\n\n",
        "es": "🎶 *Recomendaciones para ti:*\n\n",
    },
    "music_no_recommendations": {
        "en": "🎶 No recommendations available.",
        "pt": "🎶 Sem recomendações disponíveis.",
        "es": "🎶 No hay recomendaciones disponibles.",
    },
    "music_genres_header": {
        "en": "🎵 *Available genres on Spotify:*\n\n",
        "pt": "🎵 *Gêneros disponíveis no Spotify:*\n\n",
        "es": "🎵 *Géneros disponibles en Spotify:*\n\n",
    },
    "music_spotify_unavailable": {
        "en": "🎵 Spotify service is not available right now.",
        "pt": "🎵 O serviço Spotify não está disponível de momento.",
        "es": "🎵 El servicio de Spotify no está disponible ahora.",
    },
    "music_error": {
        "en": "An error occurred while searching for music. Please try again.",
        "pt": "Ocorreu um erro ao buscar música. Tente novamente.",
        "es": "Ocurrió un error al buscar música. Inténtalo de nuevo.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # GMAIL SERVICE
    # ══════════════════════════════════════════════════════════════════════════
    "gmail_not_connected": {
        "en": "Gmail not connected. Use 'connect gmail' to authorize.",
        "pt": "Gmail não conectado. Usa 'conectar gmail' para autorizar.",
        "es": "Gmail no conectado. Usa 'conectar gmail' para autorizar.",
    },
    "gmail_token_expired": {
        "en": "Gmail token expired or revoked. Reconnect with 'connect gmail'.",
        "pt": "Token Gmail expirado ou revogado. Reconecta com 'conectar gmail'.",
        "es": "Token de Gmail expirado o revocado. Reconecta con 'conectar gmail'.",
    },
    "gmail_no_subject": {
        "en": "(no subject)",
        "pt": "(sem assunto)",
        "es": "(sin asunto)",
    },
    "gmail_oauth_not_configured": {
        "en": "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET "
        "not configured. Gmail OAuth2 not available.",
        "pt": "GOOGLE_OAUTH_CLIENT_ID e GOOGLE_OAUTH_CLIENT_SECRET "
        "não configurados. Gmail OAuth2 não disponível.",
        "es": "GOOGLE_OAUTH_CLIENT_ID y GOOGLE_OAUTH_CLIENT_SECRET "
        "no configurados. Gmail OAuth2 no disponible.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # GOOGLE OAUTH SERVICE
    # ══════════════════════════════════════════════════════════════════════════
    "oauth_state_invalid": {
        "en": "Invalid state in callback: {error}",
        "pt": "State inválido no callback: {error}",
        "es": "Estado inválido en callback: {error}",
    },
    "oauth_token_exchange_failed": {
        "en": "Google token exchange failed ({status}): {detail}",
        "pt": "Falha na troca de token Google ({status}): {detail}",
        "es": "Fallo en intercambio de token Google ({status}): {detail}",
    },
    "oauth_profile_failed": {
        "en": "Failed to get Google profile: {detail}",
        "pt": "Falha ao obter perfil Google: {detail}",
        "es": "Fallo al obtener perfil de Google: {detail}",
    },
    "oauth_supabase_unavailable": {
        "en": "Supabase not available for token storage",
        "pt": "Supabase não disponível para guardar tokens",
        "es": "Supabase no disponible para almacenar tokens",
    },
    "oauth_token_refresh_failed": {
        "en": "Token refresh failed: {detail}",
        "pt": "Falha ao renovar token: {detail}",
        "es": "Fallo al renovar token: {detail}",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # AUTH ROUTES — Google OAuth HTML pages & messages
    # ══════════════════════════════════════════════════════════════════════════
    "oauth_not_configured": {
        "en": "Google OAuth2 not configured. "
        "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET.",
        "pt": "Google OAuth2 não configurado. "
        "Defina GOOGLE_OAUTH_CLIENT_ID e GOOGLE_OAUTH_CLIENT_SECRET.",
        "es": "Google OAuth2 no configurado. "
        "Configure GOOGLE_OAUTH_CLIENT_ID y GOOGLE_OAUTH_CLIENT_SECRET.",
    },
    "oauth_google_error": {
        "en": "Google returned an error: {error}",
        "pt": "Google retornou erro: {error}",
        "es": "Google devolvió un error: {error}",
    },
    "oauth_missing_params": {
        "en": "Missing parameters (code or state).",
        "pt": "Parâmetros em falta (code ou state).",
        "es": "Parámetros faltantes (code o state).",
    },
    "oauth_invalid_state": {
        "en": "Invalid state: {error}",
        "pt": "State inválido: {error}",
        "es": "Estado inválido: {error}",
    },
    "oauth_connect_error": {
        "en": "Error connecting: {error}",
        "pt": "Erro ao conectar: {error}",
        "es": "Error al conectar: {error}",
    },
    "oauth_disconnected": {
        "en": "Google account disconnected.",
        "pt": "Conta Google desconectada.",
        "es": "Cuenta de Google desconectada.",
    },
    "oauth_disconnect_failed": {
        "en": "Failed to disconnect Google account.",
        "pt": "Falha ao desconectar conta Google.",
        "es": "Fallo al desconectar cuenta de Google.",
    },
    "oauth_success_title": {
        "en": "Connected!",
        "pt": "Conectado!",
        "es": "¡Conectado!",
    },
    "oauth_success_heading": {
        "en": "Google Connected!",
        "pt": "Google Conectado!",
        "es": "¡Google Conectado!",
    },
    "oauth_success_message": {
        "en": "Hello {name}! Jarvis now has access to your Calendar and Gmail.",
        "pt": "Olá {name}! O Jarvis agora tem acesso ao teu Calendar e Gmail.",
        "es": "¡Hola {name}! Jarvis ahora tiene acceso a tu Calendar y Gmail.",
    },
    "oauth_success_close": {
        "en": "You can close this window and go back to Telegram.",
        "pt": "Podes fechar esta janela e voltar ao Telegram.",
        "es": "Puedes cerrar esta ventana y volver a Telegram.",
    },
    "oauth_error_page_title": {
        "en": "Error",
        "pt": "Erro",
        "es": "Error",
    },
    "oauth_error_heading": {
        "en": "Connection Error",
        "pt": "Erro ao Conectar",
        "es": "Error al Conectar",
    },
    "oauth_error_retry": {
        "en": "Try again or contact the admin.",
        "pt": "Tenta novamente ou fala com o admin.",
        "es": "Inténtalo de nuevo o contacta al admin.",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # CALENDAR AGENT (expanded)
    # ══════════════════════════════════════════════════════════════════════════
    "cal_already_connected": {
        "en": "Your Google account is already connected! Calendar and Gmail active.",
        "pt": "A tua conta Google já está conectada! Calendar e Gmail activos.",
        "es": "¡Tu cuenta de Google ya está conectada! Calendar y Gmail activos.",
    },
    "cal_connect_link": {
        "en": "Click the link to connect your Google account "
        "(Calendar + Gmail):\n{auth_url}",
        "pt": "Clica no link para conectar a tua conta Google "
        "(Calendar + Gmail):\n{auth_url}",
        "es": "Haz clic en el enlace para conectar tu cuenta de Google "
        "(Calendar + Gmail):\n{auth_url}",
    },
    "cal_no_meetings": {
        "en": "You have no scheduled meetings.",
        "pt": "Não tens reuniões agendadas.",
        "es": "No tienes reuniones programadas.",
    },
    "cal_no_title": {
        "en": "Untitled",
        "pt": "Sem título",
        "es": "Sin título",
    },
    "cal_next_meeting": {
        "en": "Your next meeting is '{summary}' on {time}",
        "pt": "A tua próxima reunião é '{summary}' em {time}",
        "es": "Tu próxima reunión es '{summary}' el {time}",
    },
    "cal_next_meeting_location": {
        "en": " at {location}",
        "pt": " em {location}",
        "es": " en {location}",
    },
    "cal_no_events_today": {
        "en": "You have no events scheduled for today.",
        "pt": "Não tens eventos agendados para hoje.",
        "es": "No tienes eventos programados para hoy.",
    },
    "cal_events_today": {
        "en": "You have {count} event(s) today:\n\n",
        "pt": "Tens {count} evento(s) hoje:\n\n",
        "es": "Tienes {count} evento(s) hoy:\n\n",
    },
    "cal_no_events_week": {
        "en": "You have no events scheduled for this week.",
        "pt": "Não tens eventos agendados para esta semana.",
        "es": "No tienes eventos programados para esta semana.",
    },
    "cal_events_week": {
        "en": "You have {count} event(s) this week:\n\n",
        "pt": "Tens {count} evento(s) esta semana:\n\n",
        "es": "Tienes {count} evento(s) esta semana:\n\n",
    },
    "cal_no_events_upcoming": {
        "en": "You have no events in the next 7 days.",
        "pt": "Não tens eventos nos próximos 7 dias.",
        "es": "No tienes eventos en los próximos 7 días.",
    },
    "cal_events_upcoming": {
        "en": "You have {count} upcoming event(s):\n\n",
        "pt": "Tens {count} evento(s) próximos:\n\n",
        "es": "Tienes {count} evento(s) próximos:\n\n",
    },
    "cal_briefing_header": {
        "en": "**Calendar Briefing**\n\n",
        "pt": "**Briefing do Calendário**\n\n",
        "es": "**Briefing del Calendario**\n\n",
    },
    "cal_briefing_no_events": {
        "en": "**Today:** No events scheduled.",
        "pt": "**Hoje:** Sem eventos agendados.",
        "es": "**Hoy:** Sin eventos programados.",
    },
    "cal_briefing_today": {
        "en": "**Today ({date}):**\n",
        "pt": "**Hoje ({date}):**\n",
        "es": "**Hoy ({date}):**\n",
    },
    "cal_error": {
        "en": "Error accessing your calendar: {error}",
        "pt": "Erro ao acessar o teu calendário: {error}",
        "es": "Error al acceder a tu calendario: {error}",
    },
    "cal_event_missing_title": {
        "en": "Couldn't identify the event title. "
        "Please specify what you want to schedule.",
        "pt": "Não consegui identificar o título do evento. "
        "Por favor, especifica o que queres agendar.",
        "es": "No pude identificar el título del evento. "
        "Por favor, especifica qué quieres agendar.",
    },
    "cal_event_invalid_datetime": {
        "en": "Error processing the event date and time. "
        "Please use a valid format (e.g., 2025-02-15T15:00:00).",
        "pt": "Erro ao processar data e hora do evento. "
        "Por favor, usa um formato válido (ex: 2025-02-15T15:00:00).",
        "es": "Error al procesar la fecha y hora del evento. "
        "Por favor, usa un formato válido (ej: 2025-02-15T15:00:00).",
    },
    "cal_event_missing_datetime": {
        "en": "Couldn't identify the event date and time. "
        "Please specify when you want to schedule.",
        "pt": "Não consegui identificar a data e hora do evento. "
        "Por favor, especifica quando queres agendar.",
        "es": "No pude identificar la fecha y hora del evento. "
        "Por favor, especifica cuándo quieres agendar.",
    },
    "cal_event_validation_error": {
        "en": "Error processing event data: {error}. Please use a valid format.",
        "pt": "Erro ao processar dados do evento: {error}. "
        "Por favor, usa um formato válido.",
        "es": "Error al procesar datos del evento: {error}. "
        "Por favor, usa un formato válido.",
    },
    "cal_event_creation_failed": {
        "en": "Could not create the event. Please try again.",
        "pt": "Não foi possível criar o evento. Por favor, tenta novamente.",
        "es": "No fue posible crear el evento. Por favor, inténtalo de nuevo.",
    },
    "cal_event_created": {
        "en": "Event created successfully!\n\n",
        "pt": "Evento criado com sucesso!\n\n",
        "es": "¡Evento creado con éxito!\n\n",
    },
    "cal_event_date_label": {
        "en": "Date: {date}",
        "pt": "Data: {date}",
        "es": "Fecha: {date}",
    },
    "cal_event_location_label": {
        "en": "\nLocation: {location}",
        "pt": "\nLocal: {location}",
        "es": "\nUbicación: {location}",
    },
    "cal_event_description_label": {
        "en": "\nDescription: {description}",
        "pt": "\nDescrição: {description}",
        "es": "\nDescripción: {description}",
    },
    "cal_no_events": {
        "en": "You have no scheduled events.",
        "pt": "Não tens eventos agendados.",
        "es": "No tienes eventos programados.",
    },
    "cal_no_events_with_location": {
        "en": "No future events with location found.",
        "pt": "Nenhum evento futuro com localização encontrado.",
        "es": "No se encontraron eventos futuros con ubicación.",
    },
    "cal_event_all_day": {
        "en": "The event '{summary}' is an all-day event, with no specific time.",
        "pt": "O evento '{summary}' é um evento de dia inteiro, "
        "sem horário específico.",
        "es": "El evento '{summary}' es un evento de todo el día, "
        "sin horario específico.",
    },
    "cal_traffic_partial": {
        "en": "Next event with location: '{summary}' at {location} "
        "at {time}. Traffic service not available to check conditions.",
        "pt": "Próximo evento com local: '{summary}' em {location} "
        "às {time}. Serviço de tráfego não disponível "
        "para verificar condições.",
        "es": "Próximo evento con ubicación: '{summary}' en {location} "
        "a las {time}. Servicio de tráfico no disponible "
        "para verificar condiciones.",
    },
    "cal_traffic_header": {
        "en": "Traffic Alert for Event\n\n"
        "Event: {summary}\n"
        "Time: {time}\n"
        "Location: {location}\n\n",
        "pt": "Alerta de Tráfego para Evento\n\n"
        "Evento: {summary}\n"
        "Horário: {time}\n"
        "Local: {location}\n\n",
        "es": "Alerta de Tráfico para Evento\n\n"
        "Evento: {summary}\n"
        "Horario: {time}\n"
        "Ubicación: {location}\n\n",
    },
    "cal_traffic_error": {
        "en": "Error checking traffic for event: {error}",
        "pt": "Erro ao verificar tráfego para evento: {error}",
        "es": "Error al verificar tráfico para evento: {error}",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # EMAIL AGENT (expanded)
    # ══════════════════════════════════════════════════════════════════════════
    "email_help": {
        "en": "📧 *Email Management*\n\n"
        "You can tell me:\n"
        "• _'Show my emails'_\n"
        "• _'Unread emails from Gmail'_\n"
        "• _'Reply to the last email'_\n"
        "• _'Summarize João's email'_\n"
        "• _'How many emails do I have?'_\n"
        "• _'Connect Gmail'_",
        "pt": "📧 *Gestão de Email*\n\n"
        "Podes dizer-me:\n"
        "• _'Mostra os meus emails'_\n"
        "• _'Emails não lidos do Gmail'_\n"
        "• _'Responde ao último email'_\n"
        "• _'Resume o email do João'_\n"
        "• _'Quantos emails tenho?'_\n"
        "• _'Conectar Gmail'_",
        "es": "📧 *Gestión de Email*\n\n"
        "Puedes decirme:\n"
        "• _'Muestra mis emails'_\n"
        "• _'Emails no leídos de Gmail'_\n"
        "• _'Responde al último email'_\n"
        "• _'Resume el email de João'_\n"
        "• _'¿Cuántos emails tengo?'_\n"
        "• _'Conectar Gmail'_",
    },
    "email_no_emails": {
        "en": "📭 No emails{filter} found.",
        "pt": "📭 Nenhum email{filter} encontrado.",
        "es": "📭 Ningún email{filter} encontrado.",
    },
    "email_filter_from_account": {
        "en": " from {account}",
        "pt": " do {account}",
        "es": " de {account}",
    },
    "email_filter_unread": {
        "en": " unread",
        "pt": " não lidos",
        "es": " no leídos",
    },
    "email_list_title": {
        "en": "📧 *Emails{filter} — {account}*\n\n",
        "pt": "📧 *Emails{filter} — {account}*\n\n",
        "es": "📧 *Emails{filter} — {account}*\n\n",
    },
    "email_no_subject": {
        "en": "(no subject)",
        "pt": "(sem assunto)",
        "es": "(sin asunto)",
    },
    "email_list_interact": {
        "en": "\n_Say 'reply to 1' or 'summarize 2' to interact._",
        "pt": "\n_Diz 'responde ao 1' ou 'resume o 2' para interagir._",
        "es": "\n_Di 'responde al 1' o 'resume el 2' para interactuar._",
    },
    "email_connect_error": {
        "en": "❌ Could not generate the connection link. {error}",
        "pt": "❌ Não foi possível gerar o link de conexão. {error}",
        "es": "❌ No fue posible generar el enlace de conexión. {error}",
    },
    "email_already_connected": {
        "en": "✅ Your Gmail is already connected! Say 'show my emails' to view.",
        "pt": "✅ O teu Gmail já está conectado! Diz 'mostra os meus emails' para ver.",
        "es": "✅ ¡Tu Gmail ya está conectado! Di 'muestra mis emails' para ver.",
    },
    "email_connect_link": {
        "en": "🔗 To connect your Gmail, click the link:\n{auth_url}"
        "\n\nAfter authorizing, say 'show my emails'.",
        "pt": "🔗 Para conectar o teu Gmail, clica no link:\n{auth_url}"
        "\n\nDepois de autorizar, diz 'mostra os meus emails'.",
        "es": "🔗 Para conectar tu Gmail, haz clic en el enlace:"
        "\n{auth_url}\n\nDespués de autorizar, di 'muestra mis emails'.",
    },
    "email_count_header": {
        "en": "📊 *Your emails*\n",
        "pt": "📊 *Seus emails*\n",
        "es": "📊 *Tus emails*\n",
    },
    "email_count_line": {
        "en": "{icon} **{label}:** {unread} unread / {total} total",
        "pt": "{icon} **{label}:** {unread} não lidos / {total} total",
        "es": "{icon} **{label}:** {unread} no leídos / {total} total",
    },
    "email_count_total_unread": {
        "en": "\n🔵 **Total unread: {count}**",
        "pt": "\n🔵 **Total não lidos: {count}**",
        "es": "\n🔵 **Total no leídos: {count}**",
    },
    "email_count_all_read": {
        "en": "\n✅ No unread emails!",
        "pt": "\n✅ Sem emails por ler!",
        "es": "\n✅ ¡Sin emails por leer!",
    },
    "email_not_found": {
        "en": "❌ Couldn't find the email. Show the list first with 'show my emails'?",
        "pt": "❌ Não encontrei o email. "
        "Podes mostrar a lista primeiro com 'mostra os meus emails'?",
        "es": "❌ No encontré el email. "
        "¿Puedes mostrar la lista primero con 'muestra mis emails'?",
    },
    "email_summary_header": {
        "en": "📧 **{account}** — Summary\n\n"
        "👤 **From:** {sender}\n"
        "📌 **Subject:** {subject}\n\n{summary}",
        "pt": "📧 **{account}** — Resumo\n\n"
        "👤 **De:** {sender}\n"
        "📌 **Assunto:** {subject}\n\n{summary}",
        "es": "📧 **{account}** — Resumen\n\n"
        "👤 **De:** {sender}\n"
        "📌 **Asunto:** {subject}\n\n{summary}",
    },
    "email_no_email_to_reply": {
        "en": "❌ Couldn't find any email to reply to. Say 'show my emails' first.",
        "pt": "❌ Não encontrei nenhum email para responder. "
        "Diz 'mostra os meus emails' primeiro.",
        "es": "❌ No encontré ningún email para responder. "
        "Di 'muestra mis emails' primero.",
    },
    "email_draft_header": {
        "en": "📝 *Reply draft — {account}*\n\n"
        "**To:** {to}\n**Subject:** Re: {subject}\n\n"
        "---\n{draft}\n---\n\n"
        "✅ Say **'yes'** to send or **'no'** to cancel.\n"
        "Or say what you want to change.",
        "pt": "📝 *Rascunho de resposta — {account}*\n\n"
        "**Para:** {to}\n**Assunto:** Re: {subject}\n\n"
        "---\n{draft}\n---\n\n"
        "✅ Diz **'sim'** para enviar ou **'não'** para cancelar.\n"
        "Ou diz o que queres alterar.",
        "es": "📝 *Borrador de respuesta — {account}*\n\n"
        "**Para:** {to}\n**Asunto:** Re: {subject}\n\n"
        "---\n{draft}\n---\n\n"
        "✅ Di **'sí'** para enviar o **'no'** para cancelar.\n"
        "O di qué quieres cambiar.",
    },
    "email_reply_cancelled": {
        "en": "✅ Reply cancelled. Email not sent.",
        "pt": "✅ Resposta cancelada. Email não enviado.",
        "es": "✅ Respuesta cancelada. Email no enviado.",
    },
    "email_no_draft": {
        "en": "❌ No draft to send. Request a reply first.",
        "pt": "❌ Sem rascunho para enviar. Pede uma resposta primeiro.",
        "es": "❌ Sin borrador para enviar. Pide una respuesta primero.",
    },
    "email_send_error_with_auth": {
        "en": "❌ {error}\n\n🔗 Connect Gmail: {auth_url}",
        "pt": "❌ {error}\n\n🔗 Conecta o Gmail: {auth_url}",
        "es": "❌ {error}\n\n🔗 Conecta Gmail: {auth_url}",
    },
    "email_reply_sent": {
        "en": "✅ Reply sent via {account}!",
        "pt": "✅ Resposta enviada pelo {account}!",
        "es": "✅ ¡Respuesta enviada por {account}!",
    },
    "email_send_error": {
        "en": "❌ Error sending: {error}\nTry again.",
        "pt": "❌ Erro ao enviar: {error}\nTente novamente.",
        "es": "❌ Error al enviar: {error}\nInténtalo de nuevo.",
    },
    "email_ignored": {
        "en": "✅ Email ignored. I won't notify you about this one.",
        "pt": "✅ Email ignorado. Não vou notificar-te sobre este.",
        "es": "✅ Email ignorado. No te notificaré sobre este.",
    },
    "email_draft_updated": {
        "en": "📝 *Draft updated:*\n\n---\n{draft}\n---\n\n"
        "✅ **'yes'** to send or **'no'** to cancel.",
        "pt": "📝 *Rascunho actualizado:*\n\n---\n{draft}\n---\n\n"
        "✅ **'sim'** para enviar ou **'não'** para cancelar.",
        "es": "📝 *Borrador actualizado:*\n\n---\n{draft}\n---\n\n"
        "✅ **'sí'** para enviar o **'no'** para cancelar.",
    },
    "email_no_sent_replies": {
        "en": "📭 I haven't replied to any emails for you yet.",
        "pt": "📭 Ainda não respondi a nenhum email por ti.",
        "es": "📭 Aún no he respondido a ningún email por ti.",
    },
    "email_sent_replies_header": {
        "en": "📤 *Emails replied by bot*\n",
        "pt": "📤 *Emails respondidos pelo bot*\n",
        "es": "📤 *Emails respondidos por el bot*\n",
    },
    "email_no_body": {
        "en": "_No email body._",
        "pt": "_Sem corpo de email._",
        "es": "_Sin cuerpo de email._",
    },
    "email_incoming_notification": {
        "en": "{urgency_icon} *{account}* — Email received\n\n"
        "👤 **From:** {sender}\n"
        "📌 **Subject:** {subject}\n\n"
        "📝 **Summary:**\n{summary}\n\n"
        "💬 Do you want me to reply?",
        "pt": "{urgency_icon} *{account}* — Email recebido\n\n"
        "👤 **De:** {sender}\n"
        "📌 **Assunto:** {subject}\n\n"
        "📝 **Resumo:**\n{summary}\n\n"
        "💬 Queres que eu responda?",
        "es": "{urgency_icon} *{account}* — Email recibido\n\n"
        "👤 **De:** {sender}\n"
        "📌 **Asunto:** {subject}\n\n"
        "📝 **Resumen:**\n{summary}\n\n"
        "💬 ¿Quieres que responda?",
    },
    "email_user_id_required": {
        "en": "user_id required to send emails.",
        "pt": "user_id obrigatório para enviar emails.",
        "es": "user_id obligatorio para enviar emails.",
    },
    "email_gmail_unavailable": {
        "en": "GmailService not available.",
        "pt": "GmailService não disponível.",
        "es": "GmailService no disponible.",
    },
    "email_gmail_not_connected": {
        "en": "Gmail not connected.",
        "pt": "Gmail não conectado.",
        "es": "Gmail no conectado.",
    },
    "email_need_connect_first": {
        "en": "You need to connect your Gmail first. Click the link to authorize.",
        "pt": "Precisas conectar o teu Gmail primeiro. Clica no link para autorizar.",
        "es": "Necesitas conectar tu Gmail primero. "
        "Haz clic en el enlace para autorizar.",
    },
    "email_connect_url_already": {
        "en": "Gmail is already connected!",
        "pt": "Gmail já está conectado!",
        "es": "¡Gmail ya está conectado!",
    },
    "email_connect_url_click": {
        "en": "Click the link to connect your Gmail.",
        "pt": "Clica no link para conectar o teu Gmail.",
        "es": "Haz clic en el enlace para conectar tu Gmail.",
    },
    "email_all_accounts": {
        "en": "all accounts",
        "pt": "todas as contas",
        "es": "todas las cuentas",
    },
    "email_today_at": {
        "en": "today at {time}",
        "pt": "hoje às {time}",
        "es": "hoy a las {time}",
    },
    "email_yesterday": {
        "en": "yesterday",
        "pt": "ontem",
        "es": "ayer",
    },
    "email_days_ago": {
        "en": "{days} days ago",
        "pt": "há {days} dias",
        "es": "hace {days} días",
    },
    "email_summary_prompt": {
        "en": "Summarize this email in 2-3 sentences.\n"
        "Identify:\n"
        "- Who sent it and what it's about\n"
        "- Whether it needs a reply or action\n"
        "- Urgency (high/medium/low)\n\n"
        "From: {sender}\nSubject: {subject}\n\n{body}",
        "pt": "Resuma este email em 2-3 frases.\n"
        "Identifique:\n"
        "- Quem enviou e sobre o quê\n"
        "- Se precisa de resposta ou acção\n"
        "- Urgência (alta/média/baixa)\n\n"
        "De: {sender}\nAssunto: {subject}\n\n{body}",
        "es": "Resume este email en 2-3 frases.\n"
        "Identifica:\n"
        "- Quién envió y de qué trata\n"
        "- Si necesita respuesta o acción\n"
        "- Urgencia (alta/media/baja)\n\n"
        "De: {sender}\nAsunto: {subject}\n\n{body}",
    },
    "email_summary_prompt_detailed": {
        "en": "Give a detailed summary of this email.\n\n"
        "From: {sender}\nSubject: {subject}\n\n{body}",
        "pt": "Dá um resumo detalhado deste email.\n\n"
        "De: {sender}\nAssunto: {subject}\n\n{body}",
        "es": "Da un resumen detallado de este email.\n\n"
        "De: {sender}\nAsunto: {subject}\n\n{body}",
    },
    "email_reply_prompt": {
        "en": "Generate a professional and natural reply to this email.\n"
        "{instruction}\n\n"
        "Original email:\nFrom: {sender}\n"
        "Subject: {subject}\nBody: {body}\n\n"
        "Write only the reply body, no subject greeting.",
        "pt": "Gera uma resposta profissional e natural em português "
        "para este email.\n{instruction}\n\n"
        "Email original:\nDe: {sender}\n"
        "Assunto: {subject}\nCorpo: {body}\n\n"
        "Escreve apenas o corpo da resposta, sem saudação de assunto.",
        "es": "Genera una respuesta profesional y natural en español "
        "para este email.\n{instruction}\n\n"
        "Email original:\nDe: {sender}\n"
        "Asunto: {subject}\nCuerpo: {body}\n\n"
        "Escribe solo el cuerpo de la respuesta, sin saludo de asunto.",
    },
    "email_reply_instruction": {
        "en": "Instruction: {instruction}",
        "pt": "Instrução: {instruction}",
        "es": "Instrucción: {instruction}",
    },
    "email_reply_default_instruction": {
        "en": "Polite and concise reply.",
        "pt": "Resposta educada e concisa.",
        "es": "Respuesta educada y concisa.",
    },
    "email_reply_fallback": {
        "en": "Thank you for your email about '{subject}'. I'll be in touch.",
        "pt": "Obrigado pelo seu email sobre '{subject}'. Fico aguardando.",
        "es": "Gracias por tu email sobre '{subject}'. Quedo a la espera.",
    },
    "email_reply_fallback_generic": {
        "en": "Thank you for your message. I will reply soon.",
        "pt": "Obrigado pela sua mensagem. Irei responder em breve.",
        "es": "Gracias por tu mensaje. Responderé pronto.",
    },
    "email_summary_formatted": {
        "en": "📧 **From:** {sender}\n"
        "📌 **Subject:** {subject}\n"
        "📝 **Summary:** {summary}\n"
        "⚡ **Urgency:** {urgency}",
        "pt": "📧 **De:** {sender}\n"
        "📌 **Assunto:** {subject}\n"
        "📝 **Resumo:** {summary}\n"
        "⚡ **Urgência:** {urgency}",
        "es": "📧 **De:** {sender}\n"
        "📌 **Asunto:** {subject}\n"
        "📝 **Resumen:** {summary}\n"
        "⚡ **Urgencia:** {urgency}",
    },
    "email_summary_all_header": {
        "en": "📧 *Summary of your latest emails*\n\n",
        "pt": "📧 *Resumo dos teus últimos emails*\n\n",
        "es": "📧 *Resumen de tus últimos emails*\n\n",
    },
    "email_summary_all_empty": {
        "en": "📭 No emails to summarize.",
        "pt": "📭 Sem emails para resumir.",
        "es": "📭 Sin emails para resumir.",
    },
    "email_urgency_high": {
        "en": "High — needs reply",
        "pt": "Alta — precisa de resposta",
        "es": "Alta — necesita respuesta",
    },
    "email_urgency_medium": {
        "en": "Medium",
        "pt": "Média",
        "es": "Media",
    },
    "email_urgency_low": {
        "en": "Low",
        "pt": "Baixa",
        "es": "Baja",
    },
    # ══════════════════════════════════════════════════════════════════════════
    # EMAIL POLLING
    # ══════════════════════════════════════════════════════════════════════════
    "email_poll_single": {
        "en": "\U0001f4e7 New email from {sender}\n"
        "\U0001f4cc Subject: {subject}\n"
        "\U0001f4dd Summary: {summary}\n\n"
        "Reply | Ignore | Read full",
        "pt": "\U0001f4e7 Novo email de {sender}\n"
        "\U0001f4cc Assunto: {subject}\n"
        "\U0001f4dd Resumo: {summary}\n\n"
        "Responder | Ignorar | Ler completo",
        "es": "\U0001f4e7 Nuevo email de {sender}\n"
        "\U0001f4cc Asunto: {subject}\n"
        "\U0001f4dd Resumen: {summary}\n\n"
        "Responder | Ignorar | Leer completo",
    },
    "email_poll_multiple": {
        "en": "\U0001f4e7 {count} new emails:\n{email_list}\n\n"
        "Want details on any of these?",
        "pt": "\U0001f4e7 {count} novos emails:\n{email_list}\n\n"
        "Quer detalhes de algum?",
        "es": "\U0001f4e7 {count} nuevos emails:\n{email_list}\n\n"
        "\u00bfQuieres detalles de alguno?",
    },
    "email_poll_summary_prompt": {
        "en": "Summarize this email in 1-2 short sentences for a notification.\n"
        "From: {sender}\nSubject: {subject}\n\n{body}",
        "pt": "Resuma este email em 1-2 frases curtas para uma "
        "notifica\u00e7\u00e3o.\n"
        "De: {sender}\nAssunto: {subject}\n\n{body}",
        "es": "Resume este email en 1-2 frases cortas para una "
        "notificaci\u00f3n.\n"
        "De: {sender}\nAsunto: {subject}\n\n{body}",
    },
    "email_poll_token_expired": {
        "en": "\u26a0\ufe0f Your Gmail connection has expired. "
        "Email notifications are paused.\n"
        "Please reconnect: say 'connect gmail'.",
        "pt": "\u26a0\ufe0f A sua conex\u00e3o Gmail expirou. "
        "Notifica\u00e7\u00f5es de email foram pausadas.\n"
        "Reconecte: diga 'conectar gmail'.",
        "es": "\u26a0\ufe0f Tu conexi\u00f3n Gmail ha expirado. "
        "Las notificaciones de email est\u00e1n pausadas.\n"
        "Reconecta: di 'conectar gmail'.",
    },
    "email_poll_enabled": {
        "en": "\u2705 Email notifications activated! "
        "You'll receive alerts for new emails.",
        "pt": "\u2705 Notifica\u00e7\u00f5es de email ativadas! "
        "Receber\u00e1 alertas de novos emails.",
        "es": "\u2705 \u00a1Notificaciones de email activadas! "
        "Recibir\u00e1s alertas de nuevos emails.",
    },
    "email_poll_disabled": {
        "en": "\U0001f515 Email notifications deactivated.",
        "pt": "\U0001f515 Notifica\u00e7\u00f5es de email desativadas.",
        "es": "\U0001f515 Notificaciones de email desactivadas.",
    },
    "email_poll_already_enabled": {
        "en": "Email notifications are already active.",
        "pt": "Notifica\u00e7\u00f5es de email j\u00e1 est\u00e3o ativas.",
        "es": "Las notificaciones de email ya est\u00e1n activas.",
    },
    "email_poll_already_disabled": {
        "en": "Email notifications are already off.",
        "pt": "Notifica\u00e7\u00f5es de email j\u00e1 est\u00e3o desligadas.",
        "es": "Las notificaciones de email ya est\u00e1n desactivadas.",
    },
    "email_poll_not_connected": {
        "en": "You need to connect Gmail first to enable email notifications.",
        "pt": "Precisa conectar o Gmail primeiro para ativar notifica\u00e7\u00f5es.",
        "es": "Necesitas conectar Gmail primero para activar notificaciones.",
    },
    "email_poll_error": {
        "en": "Failed to update email notification settings. Try again later.",
        "pt": "Falha ao atualizar configura\u00e7\u00f5es de "
        "notifica\u00e7\u00e3o. Tente novamente.",
        "es": "Error al actualizar configuraci\u00f3n de "
        "notificaciones. Int\u00e9ntalo luego.",
    },
    "email_poll_status": {
        "en": "\U0001f4e7 Email notifications: {status}",
        "pt": "\U0001f4e7 Notifica\u00e7\u00f5es de email: {status}",
        "es": "\U0001f4e7 Notificaciones de email: {status}",
    },
    # ── Email reply suggestion + inline buttons ──────────────────────────
    "email_poll_single_reply": {
        "en": "\U0001f4e7 New email from {sender}\n"
        "\U0001f4cc Subject: {subject}\n"
        "\U0001f4dd Summary: {summary}\n\n"
        "{urgency} Urgency\n"
        '\U0001f4ac Suggested reply:\n"{suggested_reply}"',
        "pt": "\U0001f4e7 Novo email de {sender}\n"
        "\U0001f4cc Assunto: {subject}\n"
        "\U0001f4dd Resumo: {summary}\n\n"
        "{urgency} Urg\u00eancia\n"
        '\U0001f4ac Resposta sugerida:\n"{suggested_reply}"',
        "es": "\U0001f4e7 Nuevo email de {sender}\n"
        "\U0001f4cc Asunto: {subject}\n"
        "\U0001f4dd Resumen: {summary}\n\n"
        "{urgency} Urgencia\n"
        '\U0001f4ac Respuesta sugerida:\n"{suggested_reply}"',
    },
    "email_poll_single_noreply": {
        "en": "\U0001f4e7 New email from {sender}\n"
        "\U0001f4cc Subject: {subject}\n"
        "\U0001f4dd Summary: {summary}",
        "pt": "\U0001f4e7 Novo email de {sender}\n"
        "\U0001f4cc Assunto: {subject}\n"
        "\U0001f4dd Resumo: {summary}",
        "es": "\U0001f4e7 Nuevo email de {sender}\n"
        "\U0001f4cc Asunto: {subject}\n"
        "\U0001f4dd Resumen: {summary}",
    },
    "email_poll_analysis_prompt": {
        "en": (
            "Analyze this email and respond ONLY with a JSON object.\n\n"
            "From: {sender}\nSubject: {subject}\n"
            "Summary: {summary}\nToday's date: {today}\n\n"
            "Rules for needs_reply:\n"
            "- TRUE if the sender is a real person AND the email "
            "contains:\n"
            "  * A question expecting an answer\n"
            "  * An event, meeting, call, or appointment request\n"
            "  * A direct request or ask for action\n"
            "  * A proposal needing confirmation\n"
            "  * A follow-up that expects a response\n"
            "- FALSE if the email is:\n"
            "  * A newsletter, marketing, or automated notification\n"
            "  * From a noreply@ or system address\n"
            "  * A receipt, confirmation, or status update\n"
            "  * An FYI / informational message not expecting a "
            "response\n\n"
            "Set event_request=true when the email proposes, "
            "requests, or invites to ANY event with a date/time: "
            "meetings, calls, appointments, parties, dinners, "
            "hangouts, medical appointments, cinema, BBQs, "
            "or any invitation with a proposed date/time. "
            "Extract proposed_datetime in ISO 8601 format "
            "(e.g. 2026-03-04T15:00:00) using today's date to "
            "resolve relative dates like 'tomorrow'. "
            "Extract proposed_location if mentioned.\n\n"
            "JSON format:\n"
            '{{"needs_reply": true/false, '
            '"suggested_reply": "short reply in English '
            '(empty string if no reply needed)", '
            '"urgency": "high/medium/low", '
            '"event_request": true/false, '
            '"proposed_datetime": "ISO 8601 or null", '
            '"proposed_location": "location or empty string"}}\n\n'
            "Respond ONLY with the JSON object, no extra text."
        ),
        "pt": (
            "Analyze this email and respond ONLY with a JSON object.\n\n"
            "From: {sender}\nSubject: {subject}\n"
            "Summary: {summary}\nToday's date: {today}\n\n"
            "Rules for needs_reply:\n"
            "- TRUE if the sender is a real person AND the email "
            "contains:\n"
            "  * A question expecting an answer\n"
            "  * An event, meeting, call, or appointment request\n"
            "  * A direct request or ask for action\n"
            "  * A proposal needing confirmation\n"
            "  * A follow-up that expects a response\n"
            "- FALSE if the email is:\n"
            "  * A newsletter, marketing, or automated notification\n"
            "  * From a noreply@ or system address\n"
            "  * A receipt, confirmation, or status update\n"
            "  * An FYI / informational message not expecting a "
            "response\n\n"
            "Set event_request=true when the email proposes, "
            "requests, or invites to ANY event with a date/time: "
            "meetings, calls, appointments, parties, dinners, "
            "hangouts, medical appointments, cinema, BBQs, "
            "or any invitation with a proposed date/time. "
            "Extract proposed_datetime in ISO 8601 format "
            "(e.g. 2026-03-04T15:00:00) using today's date to "
            "resolve relative dates like 'amanha'. "
            "Extract proposed_location if mentioned.\n\n"
            "JSON format:\n"
            '{{"needs_reply": true/false, '
            '"suggested_reply": "resposta curta em portugues '
            '(string vazia se nao precisa resposta)", '
            '"urgency": "high/medium/low", '
            '"event_request": true/false, '
            '"proposed_datetime": "ISO 8601 or null", '
            '"proposed_location": "local ou string vazia"}}\n\n'
            "Respond ONLY with the JSON object, no extra text."
        ),
        "es": (
            "Analyze this email and respond ONLY with a JSON object.\n\n"
            "From: {sender}\nSubject: {subject}\n"
            "Summary: {summary}\nToday's date: {today}\n\n"
            "Rules for needs_reply:\n"
            "- TRUE if the sender is a real person AND the email "
            "contains:\n"
            "  * A question expecting an answer\n"
            "  * An event, meeting, call, or appointment request\n"
            "  * A direct request or ask for action\n"
            "  * A proposal needing confirmation\n"
            "  * A follow-up that expects a response\n"
            "- FALSE if the email is:\n"
            "  * A newsletter, marketing, or automated notification\n"
            "  * From a noreply@ or system address\n"
            "  * A receipt, confirmation, or status update\n"
            "  * An FYI / informational message not expecting a "
            "response\n\n"
            "Set event_request=true when the email proposes, "
            "requests, or invites to ANY event with a date/time: "
            "meetings, calls, appointments, parties, dinners, "
            "hangouts, medical appointments, cinema, BBQs, "
            "or any invitation with a proposed date/time. "
            "Extract proposed_datetime in ISO 8601 format "
            "(e.g. 2026-03-04T15:00:00) using today's date to "
            "resolve relative dates like 'manana'. "
            "Extract proposed_location if mentioned.\n\n"
            "JSON format:\n"
            '{{"needs_reply": true/false, '
            '"suggested_reply": "respuesta corta en espanol '
            '(string vacio si no necesita respuesta)", '
            '"urgency": "high/medium/low", '
            '"event_request": true/false, '
            '"proposed_datetime": "ISO 8601 or null", '
            '"proposed_location": "lugar o string vacio"}}\n\n'
            "Respond ONLY with the JSON object, no extra text."
        ),
    },
    "email_cb_sent": {
        "en": "\u2705 Reply sent to {sender}!",
        "pt": "\u2705 Resposta enviada para {sender}!",
        "es": "\u2705 \u00a1Respuesta enviada a {sender}!",
    },
    "email_cb_sent_with_event": {
        "en": "\u2705 Reply sent to {sender}! "
        '\U0001f4c5 Event "{summary}" added to calendar.',
        "pt": "\u2705 Resposta enviada para {sender}! "
        '\U0001f4c5 Evento "{summary}" adicionado \u00e0 agenda.',
        "es": "\u2705 \u00a1Respuesta enviada a {sender}! "
        '\U0001f4c5 Evento "{summary}" agregado a la agenda.',
    },
    "email_cb_sent_event_failed": {
        "en": "\u2705 Reply sent to {sender}! "
        "\u26a0\ufe0f Could not create calendar event.",
        "pt": "\u2705 Resposta enviada para {sender}! "
        "\u26a0\ufe0f N\u00e3o foi poss\u00edvel criar evento "
        "na agenda.",
        "es": "\u2705 \u00a1Respuesta enviada a {sender}! "
        "\u26a0\ufe0f No se pudo crear el evento en la agenda.",
    },
    "email_cb_edit_prompt": {
        "en": "\u270f\ufe0f Type your reply to {sender}.\n"
        "Subject: {subject}\n\n"
        "Send your message and I'll show a preview.",
        "pt": "\u270f\ufe0f Digite sua resposta para {sender}.\n"
        "Assunto: {subject}\n\n"
        "Envie sua mensagem e mostrarei uma pr\u00e9via.",
        "es": "\u270f\ufe0f Escribe tu respuesta a {sender}.\n"
        "Asunto: {subject}\n\n"
        "Env\u00eda tu mensaje y te mostrar\u00e9 "
        "una vista previa.",
    },
    "email_cb_ignored": {
        "en": "\U0001f515 Email marked as read.",
        "pt": "\U0001f515 Email marcado como lido.",
        "es": "\U0001f515 Email marcado como le\u00eddo.",
    },
    "email_cb_archived": {
        "en": "\U0001f5d1\ufe0f Email archived.",
        "pt": "\U0001f5d1\ufe0f Email arquivado.",
        "es": "\U0001f5d1\ufe0f Email archivado.",
    },
    "email_cb_draft_expired": {
        "en": "\u26a0\ufe0f This notification has expired. Check your email.",
        "pt": "\u26a0\ufe0f Esta notifica\u00e7\u00e3o expirou. Verifique seu email.",
        "es": "\u26a0\ufe0f Esta notificaci\u00f3n ha expirado. Revisa tu email.",
    },
    "email_cb_error": {
        "en": "\u26a0\ufe0f Could not complete the action. Try again later.",
        "pt": "\u26a0\ufe0f N\u00e3o foi poss\u00edvel completar "
        "a a\u00e7\u00e3o. Tente novamente.",
        "es": "\u26a0\ufe0f No se pudo completar la acci\u00f3n. Int\u00e9ntalo luego.",
    },
    "email_cb_send_confirm": {
        "en": '\U0001f4e4 Send this reply?\n\n"{reply_text}"\n\nTo: {to}',
        "pt": '\U0001f4e4 Enviar esta resposta?\n\n"{reply_text}"\n\nPara: {to}',
        "es": '\U0001f4e4 \u00bfEnviar esta respuesta?\n\n"{reply_text}"\n\nPara: {to}',
    },
    "email_btn_send": {
        "en": "\u2705 Send",
        "pt": "\u2705 Enviar",
        "es": "\u2705 Enviar",
    },
    "email_btn_edit": {
        "en": "\u270f\ufe0f Edit",
        "pt": "\u270f\ufe0f Editar",
        "es": "\u270f\ufe0f Editar",
    },
    "email_btn_ignore": {
        "en": "\u274c Ignore",
        "pt": "\u274c Ignorar",
        "es": "\u274c Ignorar",
    },
    "email_btn_read": {
        "en": "\U0001f4d6 Read full",
        "pt": "\U0001f4d6 Ler completo",
        "es": "\U0001f4d6 Leer completo",
    },
    "email_btn_archive": {
        "en": "\U0001f5d1\ufe0f Archive",
        "pt": "\U0001f5d1\ufe0f Arquivar",
        "es": "\U0001f5d1\ufe0f Archivar",
    },
    "email_btn_cancel": {
        "en": "\u274c Cancel",
        "pt": "\u274c Cancelar",
        "es": "\u274c Cancelar",
    },
    "email_btn_send_now": {
        "en": "\U0001f4e4 Send",
        "pt": "\U0001f4e4 Enviar",
        "es": "\U0001f4e4 Enviar",
    },
    # ── Calendar-aware email analysis ─────────────────────────────────
    "email_poll_single_event": {
        "en": "\U0001f4e7 New email from {sender}\n"
        "\U0001f4cc Subject: {subject}\n"
        "\U0001f4dd Summary: {summary}\n\n"
        "\U0001f4c5 Event detected: {proposed_datetime}\n"
        "{urgency} Urgency\n"
        '\U0001f4ac Suggested reply:\n"{suggested_reply}"',
        "pt": "\U0001f4e7 Novo email de {sender}\n"
        "\U0001f4cc Assunto: {subject}\n"
        "\U0001f4dd Resumo: {summary}\n\n"
        "\U0001f4c5 Evento detectado: {proposed_datetime}\n"
        "{urgency} Urg\u00eancia\n"
        '\U0001f4ac Resposta sugerida:\n"{suggested_reply}"',
        "es": "\U0001f4e7 Nuevo email de {sender}\n"
        "\U0001f4cc Asunto: {subject}\n"
        "\U0001f4dd Resumen: {summary}\n\n"
        "\U0001f4c5 Evento detectado: "
        "{proposed_datetime}\n"
        "{urgency} Urgencia\n"
        '\U0001f4ac Respuesta sugerida:\n"{suggested_reply}"',
    },
    "email_cal_conflict": {
        "en": "\u26a0\ufe0f Calendar conflict! You have "
        '"{event}" at {time}.\n'
        "\U0001f552 Available slots: {free_slots}",
        "pt": "\u26a0\ufe0f Conflito na agenda! Voc\u00ea tem "
        '"{event}" \u00e0s {time}.\n'
        "\U0001f552 Hor\u00e1rios livres: {free_slots}",
        "es": "\u26a0\ufe0f \u00a1Conflicto en agenda! Tienes "
        '"{event}" a las {time}.\n'
        "\U0001f552 Horarios libres: {free_slots}",
    },
    "email_cal_free": {
        "en": "\u2705 Time slot is free on your calendar.",
        "pt": "\u2705 Hor\u00e1rio livre na sua agenda.",
        "es": "\u2705 Horario libre en tu agenda.",
    },
    "email_poll_conflict_reprompt": {
        "en": (
            "The user received this event request email:\n"
            "From: {sender}\nSubject: {subject}\n"
            "Summary: {summary}\n\n"
            "However, the user has a CALENDAR CONFLICT:\n"
            '- Existing event: "{conflict_event}" at '
            "{conflict_time}\n"
            "- Available slots today: {free_slots}\n\n"
            "Write a polite reply suggesting an alternative time "
            "from the free slots. "
            "Respond ONLY with JSON:\n"
            '{{"suggested_reply": "the reply text"}}'
        ),
        "pt": (
            "O utilizador recebeu este email com convite para evento:\n"
            "De: {sender}\nAssunto: {subject}\n"
            "Resumo: {summary}\n\n"
            "Por\u00e9m, o utilizador tem CONFLITO NA AGENDA:\n"
            '- Evento existente: "{conflict_event}" \u00e0s '
            "{conflict_time}\n"
            "- Hor\u00e1rios livres hoje: {free_slots}\n\n"
            "Escreva uma resposta educada sugerindo um hor\u00e1rio "
            "alternativo dos hor\u00e1rios livres. "
            "Responda APENAS com JSON:\n"
            '{{"suggested_reply": "texto da resposta"}}'
        ),
        "es": (
            "El usuario recibi\u00f3 este email con solicitud "
            "de evento:\n"
            "De: {sender}\nAsunto: {subject}\n"
            "Resumen: {summary}\n\n"
            "Sin embargo, el usuario tiene CONFLICTO EN AGENDA:\n"
            '- Evento existente: "{conflict_event}" a las '
            "{conflict_time}\n"
            "- Horarios libres hoy: {free_slots}\n\n"
            "Escribe una respuesta educada sugiriendo un horario "
            "alternativo de los horarios libres. "
            "Responde SOLO con JSON:\n"
            '{{"suggested_reply": "texto de la respuesta"}}'
        ),
    },
    "email_btn_cal_view": {
        "en": "\U0001f4c5 Calendar",
        "pt": "\U0001f4c5 Agenda",
        "es": "\U0001f4c5 Agenda",
    },
    "email_btn_cal_add": {
        "en": "\u2795 Add event",
        "pt": "\u2795 Criar evento",
        "es": "\u2795 Crear evento",
    },
    "email_cal_unavailable": {
        "en": "\u26a0\ufe0f Calendar service unavailable.",
        "pt": "\u26a0\ufe0f Servi\u00e7o de agenda indispon\u00edvel.",
        "es": "\u26a0\ufe0f Servicio de agenda no disponible.",
    },
    "email_cal_not_connected": {
        "en": "\u26a0\ufe0f Google Calendar not connected. "
        "Connect it first to use calendar features.",
        "pt": "\u26a0\ufe0f Google Calendar n\u00e3o conectado. "
        "Conecte primeiro para usar a agenda.",
        "es": "\u26a0\ufe0f Google Calendar no conectado. "
        "Con\u00e9ctalo primero para usar la agenda.",
    },
    "email_cal_no_events": {
        "en": "\U0001f4c5 No events today.",
        "pt": "\U0001f4c5 Nenhum evento hoje.",
        "es": "\U0001f4c5 Sin eventos hoy.",
    },
    "email_cal_today_header": {
        "en": "\U0001f4c5 Today's events:",
        "pt": "\U0001f4c5 Eventos de hoje:",
        "es": "\U0001f4c5 Eventos de hoy:",
    },
    "email_cal_no_datetime": {
        "en": "\u26a0\ufe0f No date/time detected for this event.",
        "pt": "\u26a0\ufe0f Nenhuma data/hora detectada para este evento.",
        "es": "\u26a0\ufe0f No se detect\u00f3 fecha/hora para este evento.",
    },
    "email_cal_event_created": {
        "en": '\u2705 Event "{summary}" added to your calendar!',
        "pt": '\u2705 Evento "{summary}" adicionado \u00e0 sua agenda!',
        "es": '\u2705 \u00a1Evento "{summary}" agregado a tu agenda!',
    },
    # ── Maps Agent ────────────────────────────────────────────────────────
    "maps_service_unavailable": {
        "pt": "🗺️ Serviço de mapas indisponível no momento. Tente novamente mais tarde.",
        "en": "🗺️ Maps service is currently unavailable. Please try again later.",
        "es": "🗺️ El servicio de mapas no está disponible. Intenta de nuevo más tarde.",
    },
    "maps_error": {
        "pt": "❌ Erro ao processar a solicitação de mapas. Tente novamente.",
        "en": "❌ Error processing maps request. Please try again.",
        "es": "❌ Error al procesar la solicitud de mapas. Intenta de nuevo.",
    },
    "maps_need_destination": {
        "pt": (
            "📍 Para onde você quer ir? Diga algo como:\n"
            "• *Como chegar de Dublin a Cork*\n"
            "• *Rota para o aeroporto a pé*\n"
            "• *Directions to Heuston Station*"
        ),
        "en": (
            "📍 Where do you want to go? Try something like:\n"
            "• *Directions from Dublin to Cork*\n"
            "• *How to get to the airport walking*\n"
            "• *Route to Heuston Station*"
        ),
        "es": (
            "📍 ¿A dónde quieres ir? Prueba algo como:\n"
            "• *Cómo llegar de Dublin a Cork*\n"
            "• *Ruta al aeropuerto caminando*\n"
            "• *Dirección a Heuston Station*"
        ),
    },
    "maps_need_origin": {
        "pt": (
            "📍 De onde você está saindo? Diga algo como:\n"
            "• *Como chegar de Connolly a Heuston*\n"
            "Ou configure sua localização padrão."
        ),
        "en": (
            "📍 Where are you starting from? Try something like:\n"
            "• *Directions from Connolly to Heuston*\n"
            "Or set your default location."
        ),
        "es": (
            "📍 ¿Desde dónde sales? Prueba algo como:\n"
            "• *Cómo llegar de Connolly a Heuston*\n"
            "O configura tu ubicación predeterminada."
        ),
    },
    "maps_need_query": {
        "pt": "🔍 O que você quer buscar? Ex: *farmácia perto de Dublin*",
        "en": "🔍 What are you looking for? e.g. *pharmacy near Dublin*",
        "es": "🔍 ¿Qué buscas? Ej: *farmacia cerca de Dublin*",
    },
    "maps_no_results": {
        "pt": "🔍 Nenhum resultado encontrado para *{query}*. "
        "Tente com termos diferentes.",
        "en": "🔍 No results found for *{query}*. Try different search terms.",
        "es": "🔍 No se encontraron resultados para *{query}*. "
        "Intenta con otros términos.",
    },
    "maps_steps_header": {
        "pt": "🧭 **Passo a passo:**",
        "en": "🧭 **Step by step:**",
        "es": "🧭 **Paso a paso:**",
    },
    "maps_more_steps": {
        "pt": "passos adicionais",
        "en": "more steps",
        "es": "pasos adicionales",
    },
    "maps_results_header": {
        "pt": "🔍 Resultados para *{query}*:",
        "en": "🔍 Results for *{query}*:",
        "es": "🔍 Resultados para *{query}*:",
    },
    "maps_open_now": {
        "pt": "Aberto agora",
        "en": "Open now",
        "es": "Abierto ahora",
    },
    "maps_closed": {
        "pt": "Fechado",
        "en": "Closed",
        "es": "Cerrado",
    },
    "maps_opening_hours": {
        "pt": "Horário de funcionamento",
        "en": "Opening hours",
        "es": "Horario de apertura",
    },
    "maps_reviews": {
        "pt": "Avaliações",
        "en": "Reviews",
        "es": "Reseñas",
    },
    "maps_view_on_maps": {
        "pt": "Ver no Google Maps",
        "en": "View on Google Maps",
        "es": "Ver en Google Maps",
    },
    "maps_need_location": {
        "pt": (
            "📍 Não sei sua localização atual. Você pode:\n"
            "• Compartilhar localização pelo Telegram (clipe > Localização)\n"
            "• Dizer de onde está saindo: *rota de Connolly a Heuston*\n"
            "• Configurar sua localização padrão"
        ),
        "en": (
            "📍 I don't know your current location. You can:\n"
            "• Share your location via Telegram (clip > Location)\n"
            "• Tell me where you're starting from\n"
            "• Set a default location"
        ),
        "es": (
            "📍 No sé tu ubicación actual. Puedes:\n"
            "• Compartir ubicación por Telegram (clip > Ubicación)\n"
            "• Decirme de dónde sales\n"
            "• Configurar tu ubicación predeterminada"
        ),
    },
    # ── Saved Locations ───────────────────────────────────────────────
    "maps_ask_save_location": {
        "pt": (
            "Ainda nao sei onde fica sua **{alias}**.\n"
            "Qual o endereco? Vou salvar pra proxima vez.\n\n"
            "_Ex: Rua das Flores 123, Swords, Dublin_"
        ),
        "en": (
            "I don't know where your **{alias}** is yet.\n"
            "What's the address? I'll save it for next time.\n\n"
            "_E.g.: 123 Main Street, Swords, Dublin_"
        ),
        "es": (
            "Aun no se donde queda tu **{alias}**.\n"
            "Cual es la direccion? La guardare para la proxima vez.\n\n"
            "_Ej: Calle Mayor 123, Swords, Dublin_"
        ),
    },
    "maps_location_saved": {
        "pt": (
            "Pronto! Salvei **{alias}** como:\n"
            "  {address}\n\n"
            'Da proxima vez, basta dizer *"rota de {alias}"*'
            ' ou *"rota para {alias}"*.'
        ),
        "en": (
            "Done! I saved **{alias}** as:\n"
            "  {address}\n\n"
            'Next time, just say *"route from {alias}"*'
            ' or *"directions to {alias}"*.'
        ),
        "es": (
            "Listo! Guarde **{alias}** como:\n"
            "  {address}\n\n"
            'La proxima vez, solo di *"ruta desde {alias}"*'
            ' o *"ruta a {alias}"*.'
        ),
    },
    "maps_location_saved_no_coords": {
        "pt": (
            "Salvei **{alias}** como:\n"
            "  {address}\n\n"
            "Nao consegui verificar o endereco exato, "
            "mas vou usar na proxima rota."
        ),
        "en": (
            "Saved **{alias}** as:\n"
            "  {address}\n\n"
            "I couldn't verify the exact address, "
            "but I'll use it for your next route."
        ),
        "es": (
            "Guarde **{alias}** como:\n"
            "  {address}\n\n"
            "No pude verificar la direccion exacta, "
            "pero la usare en tu proxima ruta."
        ),
    },
    "maps_saved_locations_list": {
        "pt": "Seus locais salvos:",
        "en": "Your saved locations:",
        "es": "Tus ubicaciones guardadas:",
    },
    "maps_no_saved_locations": {
        "pt": (
            "Voce ainda nao tem locais salvos.\n"
            'Diga algo como *"minha casa e em Swords, Dublin"*'
            " e eu salvo pra voce."
        ),
        "en": (
            "You don't have any saved locations yet.\n"
            'Say something like *"my home is in Swords, Dublin"*'
            " and I'll save it."
        ),
        "es": (
            "Aun no tienes ubicaciones guardadas.\n"
            'Di algo como *"mi casa es en Swords, Dublin"*'
            " y la guardo."
        ),
    },
    "maps_location_deleted": {
        "pt": "Local **{alias}** removido.",
        "en": "Location **{alias}** removed.",
        "es": "Ubicacion **{alias}** eliminada.",
    },
    # ══════════════════════════════════════════════════════════════
    # Video Agent
    # ══════════════════════════════════════════════════════════════
    "video_empty_prompt": {
        "en": "Please describe the video you want or send a photo.",
        "pt": "Envie uma foto ou descreva o vídeo que deseja.",
        "es": "Envía una foto o describe el video que deseas.",
    },
    "video_grok_unavailable": {
        "en": "Grok video service not available.",
        "pt": "Serviço de vídeo Grok não disponível.",
        "es": "Servicio de video Grok no disponible.",
    },
    "video_grok_error": {
        "en": "Error generating video from photo.",
        "pt": "Erro ao gerar vídeo da foto.",
        "es": "Error al generar video de la foto.",
    },
    "video_grok_success": {
        "en": "🎬 Video generated from your photo!",
        "pt": "🎬 Vídeo gerado com sucesso a partir da foto!",
        "es": "🎬 ¡Video generado a partir de la foto!",
    },
    "video_veo_unavailable": {
        "en": "Video generation service not available.",
        "pt": "Serviço de geração de vídeo não disponível.",
        "es": "Servicio de generación de video no disponible.",
    },
    "video_veo_error": {
        "en": "Error generating video.",
        "pt": "Erro ao gerar vídeo.",
        "es": "Error al generar video.",
    },
    "video_veo_success": {
        "en": "🎬 Video generated!",
        "pt": "🎬 Vídeo gerado com sucesso!",
        "es": "🎬 ¡Video generado!",
    },
    "video_general_error": {
        "en": "Error generating video: {error}",
        "pt": "Erro ao gerar vídeo: {error}",
        "es": "Error al generar video: {error}",
    },
    # ══════════════════════════════════════════════════════════════
    # Image Agent
    # ══════════════════════════════════════════════════════════════
    "image_gen_success": {
        "en": "🎨 Image generated!",
        "pt": "🎨 Imagem gerada com sucesso!",
        "es": "🎨 ¡Imagen generada!",
    },
    "image_gen_error": {
        "en": "Error generating image.",
        "pt": "Erro ao gerar imagem.",
        "es": "Error al generar imagen.",
    },
    "image_gen_error_detail": {
        "en": "Error generating image: {error}",
        "pt": "Erro ao gerar imagem: {error}",
        "es": "Error al generar imagen: {error}",
    },
    "image_gen_background": {
        "en": "Got it! Generating your image in the background. I'll let you know when it's ready!",
        "pt": "Entendido! Estou gerando sua imagem em segundo plano. Avisarei quando estiver pronta!",
        "es": "¡Entendido! Estoy generando tu imagen en segundo plano. ¡Te avisaré cuando esté lista!",
    },
    # ══════════════════════════════════════════════════════════════
    # Photo Handler
    # ══════════════════════════════════════════════════════════════
    "bot_not_initialized": {
        "en": "Bot not initialized.",
        "pt": "Bot não inicializado.",
        "es": "Bot no inicializado.",
    },
    "photo_processing_error": {
        "en": "❌ Error processing the image. Try again with a clearer photo.",
        "pt": "❌ Erro ao processar a imagem. Tente novamente com uma foto mais nítida.",
        "es": "❌ Error al procesar la imagen. Inténtalo de nuevo con una foto más nítida.",
    },
    # ══════════════════════════════════════════════════════════════
    # Weather Agent
    # ══════════════════════════════════════════════════════════════
    "weather_query_error": {
        "en": "Could not check the weather.",
        "pt": "Não foi possível consultar o clima.",
        "es": "No fue posible consultar el clima.",
    },
    # ══════════════════════════════════════════════════════════════
    # Mercado — Shopping List
    # ══════════════════════════════════════════════════════════════
    "mercado_what_to_add": {
        "en": "❓ What items do you want to add?",
        "pt": "❓ Que itens queres adicionar?",
        "es": "❓ ¿Qué productos quieres añadir?",
    },
    "mercado_added": {
        "en": "✅ Added: {items}",
        "pt": "✅ Adicionado: {items}",
        "es": "✅ Añadido: {items}",
    },
    "mercado_already_in_list": {
        "en": "\n⚠️ Already in list: {items}",
        "pt": "\n⚠️ Já na lista: {items}",
        "es": "\n⚠️ Ya en la lista: {items}",
    },
    "mercado_current_list": {
        "en": "\n\n📋 Current list ({total} items):\n",
        "pt": "\n\n📋 Lista actual ({total} itens):\n",
        "es": "\n\n📋 Lista actual ({total} artículos):\n",
    },
    "mercado_list_empty": {
        "en": "🛒 Your shopping list is empty.\n\nTell me what to add!",
        "pt": "🛒 A tua lista de compras está vazia.\n\nDiz-me o que devo adicionar!",
        "es": "🛒 Tu lista de compras está vacía.\n\n¡Dime qué añadir!",
    },
    "mercado_list_header": {
        "en": "🛒 *Shopping List* ({total} items):\n\n",
        "pt": "🛒 *Lista de Compras* ({total} itens):\n\n",
        "es": "🛒 *Lista de Compras* ({total} artículos):\n\n",
    },
    "mercado_list_footer": {
        "en": '\n\n_Say "clear list" when you\'re done._',
        "pt": '\n\n_Diz "limpar lista" quando terminares._',
        "es": '\n\n_Di "limpiar lista" cuando termines._',
    },
    "mercado_what_to_remove": {
        "en": "❓ Which item do you want to remove?",
        "pt": "❓ Qual item queres remover?",
        "es": "❓ ¿Qué producto quieres eliminar?",
    },
    "mercado_item_removed": {
        "en": '🗑️ "{item}" removed.\n\n📋 {total} items remaining.',
        "pt": '🗑️ "{item}" removido.\n\n📋 Restam {total} itens.',
        "es": '🗑️ "{item}" eliminado.\n\n📋 Quedan {total} artículos.',
    },
    "mercado_item_not_found": {
        "en": '❌ "{item}" not found in the list.',
        "pt": '❌ "{item}" não encontrado na lista.',
        "es": '❌ "{item}" no encontrado en la lista.',
    },
    "mercado_list_cleared": {
        "en": "🗑️ List cleared! {total} item(s) removed.\n\n✅ Ready for the next shopping trip!",
        "pt": "🗑️ Lista limpa! {total} item(s) removido(s).\n\n✅ Prontos para a próxima compra!",
        "es": "🗑️ ¡Lista limpia! {total} artículo(s) eliminado(s).\n\n✅ ¡Listos para la próxima compra!",
    },
    "mercado_clear_error": {
        "en": "❌ Error clearing the list.",
        "pt": "❌ Erro ao limpar a lista.",
        "es": "❌ Error al limpiar la lista.",
    },
    "mercado_no_history": {
        "en": "📖 No shopping history yet.",
        "pt": "📖 Sem histórico de compras ainda.",
        "es": "📖 Sin historial de compras aún.",
    },
    "mercado_history_header": {
        "en": "📖 *Recent purchases:*\n\n",
        "pt": "📖 *Últimas compras:*\n\n",
        "es": "📖 *Últimas compras:*\n\n",
    },
    # ══════════════════════════════════════════════════════════════
    # Mercado — Receipt Processing
    # ══════════════════════════════════════════════════════════════
    "mercado_receipt_failed": {
        "en": "❌ Could not read the receipt.\n\n💡 Tips: good lighting, flat receipt, steady camera.",
        "pt": "❌ Não consegui ler a nota fiscal.\n\n💡 Dicas: boa iluminação, nota plana, câmera estável.",
        "es": "❌ No pude leer el recibo.\n\n💡 Consejos: buena iluminación, recibo plano, cámara estable.",
    },
    "mercado_duplicate_receipt": {
        "en": "⚠️ This receipt from *{mercado}* (€{total}) was already registered.\n\nNo duplicate data was saved.",
        "pt": "⚠️ Esta nota do *{mercado}* (€{total}) já foi registada anteriormente.\n\nNenhum dado duplicado foi guardado.",
        "es": "⚠️ Este recibo de *{mercado}* (€{total}) ya fue registrado.\n\nNo se guardaron datos duplicados.",
    },
    "mercado_receipt_header": {
        "en": "🧾 *Receipt registered — {mercado}*",
        "pt": "🧾 *Nota registada — {mercado}*",
        "es": "🧾 *Recibo registrado — {mercado}*",
    },
    "mercado_receipt_date_summary": {
        "en": "📅 {date} · {count} items · *€{total}*",
        "pt": "📅 {date} · {count} itens · *€{total}*",
        "es": "📅 {date} · {count} artículos · *€{total}*",
    },
    "mercado_items_header": {
        "en": "📋 *Items:*",
        "pt": "📋 *Itens:*",
        "es": "📋 *Artículos:*",
    },
    "mercado_more_items": {
        "en": " _...and {count} more items_",
        "pt": " _...e mais {count} itens_",
        "es": " _...y {count} artículos más_",
    },
    "mercado_price_alerts_header": {
        "en": "🔔 *Price alerts:*",
        "pt": "🔔 *Alertas de preço:*",
        "es": "🔔 *Alertas de precio:*",
    },
    "mercado_price_alert_item": {
        "en": "⚠️ *{product}* went up {pct}% (was €{old}, now €{new})",
        "pt": "⚠️ *{product}* subiu {pct}% (era €{old}, agora €{new})",
        "es": "⚠️ *{product}* subió {pct}% (era €{old}, ahora €{new})",
    },
    "mercado_tip_report": {
        "en": "_Use 'monthly report' to see this month's spending._",
        "pt": "_Usa 'relatório mensal' para ver gastos do mês._",
        "es": "_Usa 'informe mensual' para ver los gastos del mes._",
    },
    "mercado_tip_compare": {
        "en": "_Use 'compare [product]' to find the cheapest store._",
        "pt": "_Usa 'comparar [produto]' para ver onde é mais barato._",
        "es": "_Usa 'comparar [producto]' para ver dónde es más barato._",
    },
    # ══════════════════════════════════════════════════════════════
    # Mercado — Reports
    # ══════════════════════════════════════════════════════════════
    "mercado_no_purchases_month": {
        "en": "📊 No purchases recorded in {month} {year}.\n\nTake a photo of your next receipt!",
        "pt": "📊 Sem compras registadas em {month} {year}.\n\nTira uma foto da próxima nota fiscal!",
        "es": "📊 Sin compras registradas en {month} {year}.\n\n¡Toma una foto del próximo recibo!",
    },
    "mercado_report_header": {
        "en": "📊 *Report — {month} {year}*",
        "pt": "📊 *Relatório — {month} {year}*",
        "es": "📊 *Informe — {month} {year}*",
    },
    "mercado_total_spent": {
        "en": "💶 Total spent: *€{total}*",
        "pt": "💶 Total gasto: *€{total}*",
        "es": "💶 Total gastado: *€{total}*",
    },
    "mercado_stores_visited": {
        "en": "🏪 Stores visited: {count}",
        "pt": "🏪 Mercados visitados: {count}",
        "es": "🏪 Tiendas visitadas: {count}",
    },
    "mercado_spending_by_store": {
        "en": "🏆 *Spending by store:*",
        "pt": "🏆 *Gastos por mercado:*",
        "es": "🏆 *Gastos por tienda:*",
    },
    "mercado_top_categories": {
        "en": "🛒 *Top categories:*",
        "pt": "🛒 *Top categorias:*",
        "es": "🛒 *Top categorías:*",
    },
    "mercado_report_error": {
        "en": "❌ Error generating report. Try again.",
        "pt": "❌ Erro ao gerar relatório. Tente novamente.",
        "es": "❌ Error al generar el informe. Inténtalo de nuevo.",
    },
    # ══════════════════════════════════════════════════════════════
    # Mercado — Compare & Ranking
    # ══════════════════════════════════════════════════════════════
    "mercado_no_data_product": {
        "en": "🔍 I don't have data about *{product}* yet.\n\nRegister some receipts first!",
        "pt": "🔍 Ainda não tenho dados sobre *{product}*.\n\nRegista algumas notas fiscais primeiro!",
        "es": "🔍 Aún no tengo datos sobre *{product}*.\n\n¡Registra algunos recibos primero!",
    },
    "mercado_no_price_data": {
        "en": "❌ No price data for *{product}*.",
        "pt": "❌ Sem dados de preço para *{product}*.",
        "es": "❌ Sin datos de precio para *{product}*.",
    },
    "mercado_compare_header": {
        "en": "💰 *Price comparison — {product}*",
        "pt": "💰 *Comparação de preços — {product}*",
        "es": "💰 *Comparación de precios — {product}*",
    },
    "mercado_compare_savings": {
        "en": "💡 At *{store}* you save *€{amount}* per unit vs *{expensive_store}*.",
        "pt": "💡 No *{store}* poupas *€{amount}* por unidade vs *{expensive_store}*.",
        "es": "💡 En *{store}* ahorras *€{amount}* por unidad vs *{expensive_store}*.",
    },
    "mercado_compare_error": {
        "en": "❌ Error comparing prices.",
        "pt": "❌ Erro ao comparar preços.",
        "es": "❌ Error al comparar precios.",
    },
    "mercado_no_ranking_data": {
        "en": "📊 No purchase history yet. Register your first receipt!",
        "pt": "📊 Ainda sem histórico. Regista a primeira nota!",
        "es": "📊 Sin historial aún. ¡Registra tu primer recibo!",
    },
    "mercado_ranking_header": {
        "en": "🏪 *Store Ranking (all-time)*",
        "pt": "🏪 *Ranking de Mercados (histórico total)*",
        "es": "🏪 *Ranking de Tiendas (histórico total)*",
    },
    "mercado_cheapest_store": {
        "en": "💡 Where you spend least: *{store}*",
        "pt": "💡 Onde gastas menos: *{store}*",
        "es": "💡 Donde gastas menos: *{store}*",
    },
    "mercado_ranking_error": {
        "en": "❌ Error generating ranking.",
        "pt": "❌ Erro ao gerar ranking.",
        "es": "❌ Error al generar el ranking.",
    },
    "mercado_visit_count": {
        "en": "{count} visit(s)",
        "pt": "{count} visita(s)",
        "es": "{count} visita(s)",
    },
    "mercado_avg_ticket": {
        "en": "avg ticket €{amount}",
        "pt": "ticket médio €{amount}",
        "es": "ticket promedio €{amount}",
    },
    "mercado_purchase_count": {
        "en": "{count} purchase(s)",
        "pt": "{count} compra(s)",
        "es": "{count} compra(s)",
    },
    # ══════════════════════════════════════════════════════════════
    # Mercado — Month names
    # ══════════════════════════════════════════════════════════════
    "month_1": {"en": "January", "pt": "Janeiro", "es": "Enero"},
    "month_2": {"en": "February", "pt": "Fevereiro", "es": "Febrero"},
    "month_3": {"en": "March", "pt": "Março", "es": "Marzo"},
    "month_4": {"en": "April", "pt": "Abril", "es": "Abril"},
    "month_5": {"en": "May", "pt": "Maio", "es": "Mayo"},
    "month_6": {"en": "June", "pt": "Junho", "es": "Junio"},
    "month_7": {"en": "July", "pt": "Julho", "es": "Julio"},
    "month_8": {"en": "August", "pt": "Agosto", "es": "Agosto"},
    "month_9": {"en": "September", "pt": "Setembro", "es": "Septiembre"},
    "month_10": {"en": "October", "pt": "Outubro", "es": "Octubre"},
    "month_11": {"en": "November", "pt": "Novembro", "es": "Noviembre"},
    "month_12": {"en": "December", "pt": "Dezembro", "es": "Diciembre"},
    # ══════════════════════════════════════════════════════════════
    # Mercado — Categories (display names, NOT matching keywords)
    # ══════════════════════════════════════════════════════════════
    "cat_dairy": {"en": "Dairy", "pt": "Laticínios", "es": "Lácteos"},
    "cat_bakery": {"en": "Bakery", "pt": "Padaria", "es": "Panadería"},
    "cat_meat": {"en": "Meat", "pt": "Carnes", "es": "Carnes"},
    "cat_fish": {"en": "Fish", "pt": "Peixe", "es": "Pescado"},
    "cat_fruit": {"en": "Fruit", "pt": "Frutas", "es": "Frutas"},
    "cat_vegetables": {"en": "Vegetables", "pt": "Legumes", "es": "Verduras"},
    "cat_drinks": {"en": "Drinks", "pt": "Bebidas", "es": "Bebidas"},
    "cat_cleaning": {"en": "Cleaning", "pt": "Limpeza", "es": "Limpieza"},
    "cat_hygiene": {"en": "Hygiene", "pt": "Higiene", "es": "Higiene"},
    "cat_grocery": {"en": "Grocery", "pt": "Mercearia", "es": "Comestibles"},
    "cat_eggs": {"en": "Eggs", "pt": "Ovos", "es": "Huevos"},
    "cat_snacks": {"en": "Snacks", "pt": "Snacks", "es": "Snacks"},
    "cat_other": {"en": "Other", "pt": "Outros", "es": "Otros"},
    # ══════════════════════════════════════════════════════════════
    # Monthly Excel Report
    # ══════════════════════════════════════════════════════════════
    "mercado_excel_subject": {
        "en": "🧾 Monthly Shopping Report — {month} {year}",
        "pt": "🧾 Relatório Mensal de Compras — {month} {year}",
        "es": "🧾 Informe Mensual de Compras — {month} {year}",
    },
    "mercado_excel_email_body": {
        "en": "Your monthly shopping report is attached.\n\n{summary}\n\nSee the Excel file for full details.",
        "pt": "Seu relatório mensal de compras está em anexo.\n\n{summary}\n\nVeja o ficheiro Excel para detalhes.",
        "es": "Tu informe mensual de compras está adjunto.\n\n{summary}\n\nVer el archivo Excel para más detalles.",
    },
    "mercado_excel_telegram_with_email": {
        "en": "📊 {summary}\n\n📧 Excel report sent to your email!",
        "pt": "📊 {summary}\n\n📧 Relatório Excel enviado para o seu email!",
        "es": "📊 {summary}\n\n📧 ¡Informe Excel enviado a tu email!",
    },
    "mercado_excel_telegram_no_email": {
        "en": "📊 {summary}\n\n💡 Connect your Gmail to receive the report by email.",
        "pt": "📊 {summary}\n\n💡 Conecta o teu Gmail para receber o relatório por email.",
        "es": "📊 {summary}\n\n💡 Conecta tu Gmail para recibir el informe por email.",
    },
    "mercado_export_generating": {
        "en": "📊 Generating your Excel report...",
        "pt": "📊 A gerar o teu relatório Excel...",
        "es": "📊 Generando tu informe Excel...",
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


def _detect_lang_from_text(text: str) -> str:
    """
    Lightweight language detection from message text.

    Uses common marker words to distinguish Portuguese, Spanish,
    and English. Returns 2-letter code or "" if uncertain.
    """
    if not text:
        return ""
    lower = text.lower()

    # Portuguese markers (words unlikely in Spanish/English)
    _PT_MARKERS = (
        # Greetings / conversational
        "boa tarde",
        "bom dia",
        "boa noite",
        "tudo bem",
        "tudo bom",
        "como vai",
        "como voc\u00ea",  # como você
        "como voce",
        "ol\u00e1",  # olá
        "oi ",
        "oi,",
        "tchau",
        "at\u00e9 logo",  # até logo
        "ate logo",
        "valeu",
        "beleza",
        "falou",
        "e a\u00ed",  # e aí
        "e ai",
        # Common verbs/words
        "voc\u00ea",  # você
        "voce",
        "quero",
        "preciso",
        "obrigad",
        "por favor",
        "ajuda",
        "quanto custa",
        # Pronouns/articles unique to PT
        "meus ",
        "minha ",
        "minhas ",
        "meu ",
        "nosso",
        "nossa",
        "daqui",
        "aqui ",
        "agora ",
        "tamb\u00e9m",  # também
        "tambem",
        "ent\u00e3o",  # então
        "entao",
        # Tech/functional
        "ativar",
        "desativar",
        "ligar ",
        "desligar",
        " de email",
        "notifica\u00e7",  # notificaç
        "\u00e3o",  # ão
        "\u00e3es",  # ães
        "\u00f5es",  # ões
    )
    # Spanish markers (words unlikely in Portuguese/English)
    _ES_MARKERS = (
        # Greetings
        "buenas tardes",
        "buenos d\u00edas",  # buenos días
        "buenos dias",
        "buenas noches",
        "c\u00f3mo est\u00e1s",  # cómo estás
        "como estas",
        "hola ",
        "hola,",
        # Common words
        "quiero",
        "necesito",
        "gracias",
        "por favor",
        "ayuda",
        "cu\u00e1nto",  # cuánto
        "cuanto",
        # Functional
        "activar",
        "desactivar",
        "habilitar",
        "deshabilitar",
        "correo",
        "mis ",
    )

    pt_hits = sum(1 for m in _PT_MARKERS if m in lower)
    es_hits = sum(1 for m in _ES_MARKERS if m in lower)

    if pt_hits >= 2 or (pt_hits == 1 and es_hits == 0):
        return "pt"
    if es_hits >= 2 or (es_hits == 1 and pt_hits == 0):
        return "es"
    return ""


def get_user_lang(context: Optional[Dict[str, Any]] = None) -> str:
    """
    Detect user language from context.

    Priority:
    1. context["lang"] — explicitly set (e.g., by bot handler)
    2. user_preferences.language — saved preference from DB
    3. context["language_code"] — Telegram language_code
    4. Auto-detect from message text (context["message_text"])
    5. DEFAULT_LANG ("en")

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

    # 4. Auto-detect from message text
    msg_text = context.get("message_text", "")
    if msg_text:
        detected = _detect_lang_from_text(msg_text)
        if detected:
            return detected

    return DEFAULT_LANG
