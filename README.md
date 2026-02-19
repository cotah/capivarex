# SuperBot God - Your Proactive AI Assistant

[![Status](https://img.shields.io/badge/status-in%20development-blue)](https://github.com/your-username/superbot-god)
[![Version](https://img.shields.io/badge/version-3.0-green)](https://github.com/your-username/superbot-god)
[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-FastAPI-green.svg)](https://fastapi.tiangolo.com/)

**SuperBot God** is a "Jarvis-like" proactive AI assistant designed to integrate multiple services and provide contextual briefings across various interfaces. This project aims to create an intelligent companion that can manage your daily tasks, from scheduling meetings to controlling your smart home.

---

## 🚀 Features

- **Proactive Assistance:** Initiates conversations and provides briefings based on your context (agenda, traffic, weather).
- **Multi-Interface:** Works seamlessly across Telegram, a WebApp (PWA), and is designed for future smartwatch and physical device integrations.
- **Multi-Agent System:** A sophisticated orchestrator routes user requests to specialized agents for handling different tasks.
- **Integrated Services:** Connects to a wide range of services to provide a holistic experience.

### ✅ Implemented Services

- **Google Calendar:** Read and create events in your calendar.
- **Smartcar:** Connect to your electric vehicle to monitor battery, location, and control charging/locks.
- **Weather:** Get real-time weather forecasts for any location.
- **Finance:** Fetch real-time stock quotes.
- **AI-Powered Media:**
    - **Chat:** Conversational AI powered by OpenAI's GPT-4.
    - **Research:** Web search capabilities via Perplexity AI.
    - **Development:** Code generation and explanation with Anthropic's Claude.
    - **Image Generation:** Create images from text prompts using Google's Gemini.
    - **Video Generation:** Generate videos from text with Google Gemini Veo 3.1.
    - **Text-to-Speech:** Convert text into natural-sounding speech with ElevenLabs.

### ⏳ Planned Integrations

- **Google Maps Traffic:** Real-time traffic information and proactive alerts.
- **Smart Home:** Control smart devices (lights, thermostats, locks) via Seam API and Alexa.
- **Virtual Avatar:** A D-ID powered virtual avatar for the web interface.

---

## 🔧 Tech Stack

- **Backend:** Python 3.11 with FastAPI
- **Database:** Supabase (PostgreSQL)
- **Cache:** Upstash Redis
- **Authentication:** JWT (JSON Web Tokens)
- **Primary AI:** OpenAI GPT-4
- **Interfaces:** Telegram Bot, WebSockets

---

## ⚙️ Getting Started

Follow these instructions to get the project up and running on your local machine.

### Prerequisites

- Python 3.11+
- A Supabase account for the database.
- An Upstash account for Redis.
- API keys for the various services (OpenAI, Google, Perplexity, etc.).

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/cotah/bot_GOD.git
    cd bot_GOD
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows, use `.venv\Scripts\activate`
    ```

3.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure environment variables:**

    Copy the `.env.example` file to `.env` and fill in your real API keys:

    ```bash
    cp .env.example .env
    ```

    Edit the `.env` file and replace all placeholder values with your actual credentials.

5.  **Configure Google credentials:**

    Copy the example credential files and fill in your real values:

    ```bash
    cp credentials.example.json credentials.json
    cp service_account.example.json service_account.json
    ```

    Edit the JSON files with your credentials from the Google Cloud Console.

    **IMPORTANT:** Never commit `.env`, `credentials.json`, or `service_account.json` to Git. They are already listed in `.gitignore`.

### Running with Docker (Recommended)

1.  Make sure Docker Desktop is running.
2.  Run the startup script:

    ```bash
    ./start_all.sh
    ```

    This builds the images and starts the API, the arq worker, and Redis via Docker Compose.

    The API will be available at `http://localhost:8000` and docs at `http://localhost:8000/docs`.

### Running with Docker (Production)

For production deployments using gunicorn with multiple workers:

```bash
docker-compose -f docker-compose.prod.yml up --build -d
```

### Running without Docker

1.  **Start the backend server:**

    ```bash
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
    ```

2.  **Start the Telegram bot:**

    ```bash
    python telegram_bot/main.py
    ```

3.  **Start the background task worker (optional):**

    ```bash
    arq worker.WorkerSettings
    ```

    Requires a Redis instance and the `REDIS_URL` environment variable.

---

## 🤝 Contributing

Contributions are welcome! If you have ideas for new features, integrations, or improvements, feel free to open an issue or submit a pull request. Please make sure to follow the existing code style and add tests for any new functionality.

1.  Fork the Project
2.  Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3.  Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4.  Push to the Branch (`git push origin feature/AmazingFeature`)
5.  Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the `LICENSE` file for details.

---

## 📧 Contact

Your Name - your.email@example.com

Project Link: [https://github.com/cotah/bot_GOD](https://github.com/cotah/bot_GOD)
