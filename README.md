# StudyMate AI — AI Assistant for College Students

StudyMate AI is an AI-powered academic assistant designed to help college students understand concepts, prepare for examinations, and get answers to academic questions through an interactive chat interface.

Built using Python, Flask, SQLite, and the Groq API, StudyMate AI provides a simple and user-friendly platform for academic assistance with secure user authentication, persistent chat history, response caching, and an AI-powered conversational experience.

## Features

- **AI Academic Assistant** — Get explanations, academic guidance, and answers to study-related questions.
- **User Authentication** — Secure registration, login, and logout functionality.
- **Personal Chat History** — Keep conversations separate for individual users.
- **Multiple Chat Sessions** — Create and manage separate conversations.
- **Response Caching** — Reuse eligible cached responses to reduce unnecessary API requests.
- **Academic-Focused Responses** — Encourage clear explanations, structured answers, and factual accuracy.
- **Markdown Rendering** — Display formatted responses with headings, lists, and code blocks.
- **Light and Dark Modes** — Switch between light and dark themes.
- **SQLite Database** — Store application data locally.
- **API Error Handling** — Handle temporary API failures and rate-limit responses.
- **Configurable AI Responses** — Adjust response token limits and conversation history through environment variables.
- **Environment-Based Configuration** — Keep API credentials and sensitive configuration outside the source code.
- **Automated Tests** — Test important application functionality using pytest.

## Tech Stack

| Component | Technology |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python, Flask |
| Database | SQLite |
| AI Integration | Groq API |
| AI Model | Configurable through environment variables |
| Authentication | Flask Sessions and Password Hashing |
| Caching | SQLite-Based Response Cache |
| Testing | pytest |
| Version Control | Git and GitHub |

## Project Structure

```text
studymate-ai/
│
├── app.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
│
├── database/
│   └── db.py
│
├── routes/
│   ├── auth_routes.py
│   └── chat_routes.py
│
├── services/
│   ├── cache_service.py
│   ├── groq_service.py
│   └── search_service.py
│
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── app.js
│
├── templates/
│   ├── index.html
│   ├── login.html
│   └── register.html
│
└── tests/
    ├── test_backend.py
    ├── test_factual_accuracy.py
    ├── test_groq_cache.py
    └── test_registration_fix.py
```

## Prerequisites

Before running StudyMate AI, make sure you have the following installed:

- Python 3.10 or later
- pip
- Git
- A Groq API key

## Installation and Setup

### 1. Clone the Repository

Clone the repository to your local machine.

```bash
git clone https://github.com/YOUR_USERNAME/studymate-ai.git
```

Navigate to the project directory.

```bash
cd studymate-ai
```

Replace `YOUR_USERNAME` with your GitHub username.

### 2. Create a Virtual Environment

Create an isolated Python environment for the project.

**Windows PowerShell:**

```powershell
python -m venv venv
```

Activate the virtual environment.

```powershell
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution, activate the environment using Command Prompt:

```cmd
venv\Scripts\activate.bat
```

### 3. Install Dependencies

Install the required Python packages.

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root directory.

Use `.env.example` as a reference for the required configuration variables.

Example configuration:

```env
FLASK_APP=app.py
FLASK_ENV=development
FLASK_DEBUG=True
PORT=5000

FLASK_SECRET_KEY=replace-with-a-secure-random-secret
SESSION_COOKIE_SECURE=False

DATABASE_PATH=college_assistant.db

GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-20b
GROQ_MAX_TOKENS=768
GROQ_TIMEOUT=30
GROQ_MAX_RETRIES=2

CACHE_TTL_SECONDS=86400

PROMPT_VERSION=v2.0
MAX_HISTORY_TURNS=4
MAX_MESSAGE_LENGTH=4000
WEB_SEARCH_ENABLED=False
```

**Important:** The values above are examples. Use the configuration supported by your project.

#### Obtain a Groq API Key

1. Open the official Groq Console.
2. Sign in to your account.
3. Generate an API key.
4. Add the key to your local `.env` file.

Groq Console: https://console.groq.com/keys

#### Security Guidelines

- Never upload your `.env` file to GitHub.
- Never expose your API key in source code or screenshots.
- Never commit passwords or private credentials.
- Generate a secure, random Flask secret key.
- Do not use development settings in a production deployment.
- Keep `.env` excluded through `.gitignore`.

### 5. Run the Application

Start the Flask application.

```bash
python app.py
```

Once the server starts, open your browser and visit:

http://127.0.0.1:5000

Register a new account or log in to begin using StudyMate AI.

## Application Workflow

The application follows this general workflow:

1. The user opens the application in a web browser.
2. A new user registers an account or an existing user logs in.
3. The authenticated user accesses the academic chat interface.
4. The user submits an academic question.
5. The backend processes the request and checks whether an eligible cached response exists.
6. If a valid cached response is available, it can be reused.
7. Otherwise, the application can request an AI-generated response through the configured Groq API.
8. The response is returned to the frontend and displayed to the user.
9. Conversations are associated with the appropriate user.
10. The user can continue previous conversations or start another chat session.

The exact behavior depends on the application's current configuration and implementation.

## Core Modules

### 1. Authentication Module

The authentication module provides user registration, login, logout, and session management.

It is designed to protect user accounts and keep individual users' conversations separate.

### 2. AI Chat Module

The chat module handles academic questions and communicates with the configured AI service.

It supports structured answers intended to make academic topics easier to understand.

### 3. Response Caching Module

The caching module stores eligible responses so repeated requests can potentially be answered without another AI API call.

The cache expiration period is configurable through environment settings.

### 4. Academic Response Module

The academic response logic encourages the assistant to provide relevant explanations, avoid unsupported claims, and structure answers according to the user's question.

AI-generated answers may still contain mistakes and should be verified when accuracy is important.

### 5. Database Module

SQLite provides local data storage for the application.

The database layer supports application data management, including user-related and conversation-related information.

### 6. Frontend Module

The frontend uses HTML, CSS, and JavaScript to provide the user interface.

It includes the chat interface, authentication pages, message interactions, and theme-related functionality.

## API Usage and Optimization

StudyMate AI integrates with the Groq API to generate AI-powered academic responses.

The application includes configurable controls intended to reduce unnecessary API consumption.

These include:

- Response caching for eligible repeated requests.
- Configurable maximum response tokens.
- Bounded conversation history.
- Configurable request timeouts.
- Limited retries for selected failures.
- Handling for API errors and rate limits.

Actual API consumption depends on the questions submitted, cache effectiveness, selected model, and the limits imposed by the API provider.

Caching does not guarantee that API limits will never be reached.

## Testing

The project includes automated tests for important backend functionality.

Run the test suite from the project root directory:

```bash
python -m pytest -q
```

The test suite includes coverage for areas such as:

- Backend application behavior.
- Authentication-related functionality.
- AI response caching.
- Academic response accuracy logic.

Test results depend on the current code, environment configuration, and test setup.

## Configuration

Important settings can be configured through environment variables.

| Variable | Purpose |
|---|---|
| `FLASK_APP` | Flask application entry point |
| `FLASK_ENV` | Development environment configuration |
| `FLASK_DEBUG` | Development debugging setting |
| `PORT` | Application port |
| `FLASK_SECRET_KEY` | Flask session security key |
| `DATABASE_PATH` | SQLite database path |
| `GROQ_API_KEY` | Groq API authentication |
| `GROQ_MODEL` | Configured AI model |
| `GROQ_MAX_TOKENS` | Maximum generated response tokens |
| `GROQ_TIMEOUT` | API request timeout |
| `GROQ_MAX_RETRIES` | Maximum configured retry attempts |
| `CACHE_TTL_SECONDS` | Response cache expiration period |
| `PROMPT_VERSION` | Prompt version identifier |
| `MAX_HISTORY_TURNS` | Conversation history limit |
| `MAX_MESSAGE_LENGTH` | Maximum accepted message length |
| `WEB_SEARCH_ENABLED` | Controls the web search configuration |

Available settings and their actual behavior depend on the implementation in the current version of the project.

## Current Limitations

- Web search is disabled by default in the example configuration.
- AI responses depend on the configured model and available API quota.
- AI-generated information may occasionally be inaccurate.
- Institution-specific information may not be available for every college.
- Current college fees, admission details, and placement statistics should be verified using official sources.
- Production deployment requires appropriate security, hosting, and configuration settings.

## Future Enhancements

Potential future improvements include:

- Integration with verified academic resources.
- Optional web search for current information.
- College-specific information for additional institutions.
- Study notes and document summarization.
- Automatic quiz and practice question generation.
- Subject-specific learning assistance.
- Improved response evaluation and factual verification.
- Production deployment with enhanced monitoring.
- Additional accessibility and personalization features.

## Security Considerations

StudyMate AI handles user accounts and may process personal conversation data.

Before deploying the application publicly:

- Use secure production environment variables.
- Enable HTTPS.
- Configure secure session cookies.
- Verify CSRF protection for relevant requests.
- Review authentication and authorization logic.
- Protect API credentials.
- Avoid exposing sensitive information in application logs.
- Keep dependencies updated.
- Protect database files and backups.
- Review rate limits and abuse prevention.
- Test the application under production-like conditions.

Do not commit real API keys, local databases containing personal data, or private configuration files.

## Contributing

Contributions, suggestions, and bug reports are welcome.

To contribute:

1. Fork the repository.
2. Create a new feature branch.
3. Implement your changes.
4. Run the available tests.
5. Commit your changes.
6. Submit a pull request.

Please ensure that API keys and sensitive information are not included in commits.

## License

No license has been specified for this project yet.

Add a `LICENSE` file if you intend to grant others explicit permission to use, modify, and distribute the project.

## Author

PRAVEEN R (B.TECH CSBS)

## Acknowledgements

- Flask for the Python web framework.
- SQLite for local database storage.
- Groq for AI inference services.
- Python and its open-source ecosystem.

---

**StudyMate AI — Making Academic Learning More Accessible with AI.**
