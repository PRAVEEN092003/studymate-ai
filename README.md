# StudyMate AI — College Study Companion (Phase 6: Authentication & Security)

A modular, high-reliability AI study companion web application designed for college students, powered by Flask, SQLite, and the Groq API with a premium SaaS dark aesthetic and full multi-user authentication with isolated chat histories.

---

## 1. Project Structure

```text
├── app.py                      # Flask application factory, session & security config
├── requirements.txt            # Python dependencies (Flask, python-dotenv, requests)
├── .env.example                # Sample environment variables configuration
├── .gitignore                  # Git exclusions for keys, venvs, and SQLite files
├── README.md                   # Project documentation and quickstart instructions
├── database/
│   └── db.py                   # SQLite schema, user auth, session isolation & metrics
├── services/
│   ├── groq_service.py         # Groq API client with timeouts, jitter & quota detection
│   └── cache_service.py        # Normalized SHA-256 caching layer with TTL expiration
├── routes/
│   ├── auth_routes.py          # /auth/register, /auth/login, /auth/logout & CSRF protection
│   └── chat_routes.py          # /api/health, /api/chat, /api/sessions & concurrency guards
├── templates/
│   ├── index.html              # Main chat interface with user profile footer & CSRF
│   ├── login.html              # Premium dark login view with rate limiting feedback
│   └── register.html           # Registration view with server-side validation
└── static/
    ├── css/
    │   └── style.css           # Premium design system: deep charcoal, violet/blue accents
    └── js/
        └── app.js              # Session search, auto-resizing composer, code block copy, CSRF
```

---

## 2. Authentication & Security Architecture (Phase 6)

* **User Registration & Validation**:
  * Fields: Full Name, Email Address, Password, Confirm Password.
  * Server-side email normalization (`strip().lower()`) and RFC-compliant format validation.
  * Duplicate email detection returning clear user feedback.
  * Secure password hashing with Werkzeug's `scrypt`/`pbkdf2:sha256` utilities (`generate_password_hash`). Plaintext passwords are never stored or logged.
* **User Login & Session Security**:
  * Generic authentication failure errors ("Invalid email or password.") preventing account enumeration.
  * Flask server-side signed cookie sessions with session fixation mitigation (`session.clear()` and session re-generation upon login).
  * In-memory/SQLite rate limiting against brute-force attacks (max 5 failed attempts per 5 minutes per IP address).
  * Password visibility toggle on both login and registration cards.
* **CSRF Protection**:
  * CSRF tokens generated per session and embedded into forms and HTML meta tags.
  * State-changing requests (`/auth/logout`, `/auth/register`, `/auth/login`, and AJAX chat API requests via `X-CSRF-Token`) validated before processing.
* **Strict User-Specific Chat Isolation**:
  * All chat sessions and messages are strictly linked to `user_id`.
  * Every read, write, and delete operation validates server-side session ownership.
  * Frontend cannot tamper with user IDs; user IDs are retrieved exclusively from server-side sessions.
  * Cross-user session access attempts are blocked with `403 Forbidden`.
* **Zero Groq Overhead for Auth Operations**:
  * Login, registration, profile viewing, and logout do not trigger Groq API calls.
  * AI response cache is decoupled from user authentication credentials.

---

## 3. Environment Variables

Create a `.env` file in the root directory by copying `.env.example`:

```bash
cp .env.example .env
```

| Variable | Required? | Default | Description |
| :--- | :---: | :--- | :--- |
| `GROQ_API_KEY` | **Yes** | `""` | Your Groq API key from https://console.groq.com/keys |
| `FLASK_SECRET_KEY` | **Yes** (Prod) | Auto dev key | Flask secret key for cryptographically signed session cookies |
| `SESSION_COOKIE_SECURE` | No | `False` | Set `True` in production (requires HTTPS) |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | LLM model identifier |
| `GROQ_MAX_TOKENS` | No | `1024` | Maximum tokens per response |
| `GROQ_TIMEOUT` | No | `30` | Request timeout in seconds |
| `GROQ_MAX_RETRIES`| No | `3` | Maximum retry attempts on HTTP 429 rate limits |
| `CACHE_TTL_SECONDS`| No | `86400` | Expiration time for cached responses (24 hours) |
| `PORT` | No | `5000` | Local port for Flask server |
| `FLASK_DEBUG` | No | `True` | Flask debug mode |
| `DATABASE_PATH` | No | `college_assistant.db` | Path to SQLite database file |
| `PROMPT_VERSION` | No | `v1.0` | Version tag for cache invalidation |
| `MAX_HISTORY_TURNS` | No | `6` | Number of recent messages to pass as context |
| `MAX_MESSAGE_LENGTH` | No | `4000` | Input message character limit |

---

## 4. Setup and Run Instructions

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Configure Environment
```powershell
copy .env.example .env
```
Ensure `GROQ_API_KEY` and optionally `FLASK_SECRET_KEY` are configured in `.env`.

### Step 3: Run Automated Tests
```bash
python -m unittest discover tests
```

### Step 4: Run the Application
```bash
python app.py
```

Access the application in your browser at:
**http://127.0.0.1:5000**
(Unauthenticated visitors will be cleanly redirected to `/auth/login`).
