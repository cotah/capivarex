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
