# Instruções para Integrar Funcionalidades de Voz no Telegram Bot

## Arquivos Criados

1. **`services/elevenlabs_service.py`** - Serviço de Text-to-Speech
2. **`services/whisper_service.py`** - Serviço de Speech-to-Text
3. **`agents/voice_agent.py`** - Agente de voz
4. **`api/routes/voice.py`** - Rotas da API para voz
5. **`telegram_voice_handler.py`** - Handlers para Telegram

## Passos para Integração no `telegram_bot.py`

### 1. Adicionar Imports

No início do arquivo `telegram_bot.py`, adicione:

```python
# Importar handlers de voz
from telegram_voice_handler import (
    handle_voice,
    handle_audio,
    cmd_falar,
    cmd_vozes,
    cmd_falar_com
)
```

### 2. Registrar Handlers

Na função `main()`, onde os handlers são registrados (por volta da linha 1545), adicione:

```python
# Voice handlers
app.add_handler(MessageHandler(filters.VOICE, handle_voice))
app.add_handler(MessageHandler(filters.AUDIO, handle_audio))

# Voice commands
app.add_handler(CommandHandler("falar", cmd_falar))
app.add_handler(CommandHandler("vozes", cmd_vozes))
app.add_handler(CommandHandler("falar_com", cmd_falar_com))
```

### 3. Adicionar Comandos ao Menu de Ajuda

Se houver um comando `/help` ou `/start`, adicione:

```
/falar <texto> - Converter texto em áudio
/vozes - Listar vozes disponíveis
/falar_com <voz> <texto> - Falar com voz específica
```

## Comandos Disponíveis

### Para Usuários:

- **`/falar <texto>`** - Converte texto em áudio e envia como mensagem de voz
  - Exemplo: `/falar Olá, como você está?`

- **`/vozes`** - Lista todas as vozes disponíveis

- **`/falar_com <voz> <texto>`** - Converte texto em áudio usando voz específica
  - Exemplo: `/falar_com adam Bom dia!`

- **Enviar mensagem de voz** - O bot transcreve automaticamente e mostra o texto

## Vozes Disponíveis

- `rachel` - Voz feminina calma (padrão)
- `adam` - Voz masculina profunda
- `antoni` - Voz masculina natural
- `bella` - Voz feminina jovem
- `elli` - Voz feminina emocional
- `josh` - Voz masculina jovem
- `arnold` - Voz masculina madura
- `sam` - Voz masculina dinâmica

## API Endpoints

A API também está pronta para uso no WebApp:

### Text-to-Speech
```
POST /api/voice/text-to-speech
{
  "text": "Olá, mundo!",
  "voice": "rachel"
}
```

### Speech-to-Text
```
POST /api/voice/speech-to-text
FormData: audio (arquivo), language (pt)
```

### Listar Vozes
```
GET /api/voice/voices
```

### Listar Idiomas
```
GET /api/voice/languages
```

## Testando

1. **Teste de Text-to-Speech no Telegram:**
   ```
   /falar Olá, este é um teste de voz!
   ```

2. **Teste de Speech-to-Text:**
   - Envie uma mensagem de voz para o bot
   - O bot deve responder com a transcrição

3. **Teste de Vozes:**
   ```
   /vozes
   /falar_com adam Testando voz masculina
   ```

## Próximos Passos

Após integrar no Telegram, você pode:

1. Integrar no WebApp (frontend)
2. Adicionar conversação contínua por voz
3. Implementar modo "sempre ouvindo"
4. Adicionar suporte a mais idiomas

## Observações

- Os arquivos de áudio são salvos temporariamente e deletados após o uso
- O serviço usa ElevenLabs para TTS (você já tem a API key configurada)
- O serviço usa OpenAI Whisper para STT (você já tem a API key configurada)
- Todos os serviços respeitam o sistema multi-tenant do projeto
