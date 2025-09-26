# Demand-Tech Agentic Dialer

A production-ready, agentic outbound calling assistant with a modern Web UI, powered by LiveKit Agents and Google Realtime AI. It supports running fully from the console for quick testing and via a sleek web dashboard for managing lead lists, starting/stopping calls, and joining a browser-based audio session.

This document thoroughly describes every file, module, endpoint, configuration, and workflow in this repository.

---

## Highlights

- **Agentic Dialer**: Live, Voice-first agent using `livekit-agents` with Google’s Realtime LLM backend.
- **Modern Web UI**: FastAPI + Jinja2 + CSS for a responsive, dark-themed dashboard.
- **Console Mode**: Quickly test flows from your terminal, with campaign and prospect selection.
- **Campaigns as Modules**: Swap prompt packs at runtime (SplashBI, KonfHub, Zoom Phone, Default).
- **Lead Personalization**: Auto-injects per-lead context (name, role, email, company, etc.) into the session.
- **Auto-Next**: Automatically start the next call from the UI after the current one ends.
- **Browser Call**: Join a LiveKit room from your browser and converse with the agent.
- **Configurable**: All key behaviors controlled via `.env` and environment variables.

---

## Repository Structure

```
AI_Calling_Agent/
├── agent.py                 # Agent runtime + console UX + campaign & lead selection
├── leads.csv                # Sample leads with headers used by both console & UI
├── prompts.py               # Default campaign prompts
├── prompts2.py              # Campaign prompts: SplashBI (alt pack)
├── prompts3.py              # Campaign prompts: KonfHub
├── prompts4.py              # Campaign prompts: Zoom Phone (DM0122)
├── requirements.txt         # Python dependencies
├── LICENSE                  # MIT license
├── webui/
│   ├── app.py               # FastAPI app for dashboard, APIs, and browser call
│   ├── static/
│   │   └── style.css        # Dark-themed UI styles
│   └── templates/
│       ├── base.html        # Base template, header/footer
│       ├── index.html       # Dashboard: leads table, call controls, status card
│       └── browser_call.html# Browser-join page (LiveKit Web SDK)
└── README.md                # This file
```

---

## Prerequisites

- Python 3.10+
- A running LiveKit server (Cloud or self-hosted) with API Key/Secret
- Google Realtime AI access via `livekit-plugins-google` (see that plugin's docs for account setup)
- Windows, macOS, or Linux. Windows-specific notes included below.

---

## Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   # Optional utilities used by the README or your workflow
   pip install httpx
   ```

2. Create a `.env` file in `AI_Calling_Agent/`:
   ```ini
   # LiveKit server
   LIVEKIT_URL=wss://your-livekit-host
   LIVEKIT_API_KEY=your_api_key
   LIVEKIT_API_SECRET=your_api_secret

   # Optional: path to leads CSV (defaults to ./leads.csv)
   LEADS_CSV_PATH=d:/path/to/leads.csv

   # Optional: override the campaign prompt module & attributes used by the agent
   CAMPAIGN_PROMPT_MODULE=prompts       # e.g., prompts | prompts2 | prompts3 | prompts4
   CAMPAIGN_AGENT_NAME=ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS
   CAMPAIGN_SESSION_NAME=SESSION_INSTRUCTION

   # Optional: choose a lead by index (1-based) for single-call flows
   LEAD_INDEX=1
   ```

3. Verify your leads CSV has the expected headers (see CSV format section).

---

## Running the Web UI

Start the FastAPI app with Uvicorn from the `AI_Calling_Agent/` directory.

- Generic:
  ```bash
  uvicorn webui.app:app --host 0.0.0.0 --port 8000 --reload
  ```

- Python module form (helpful on some systems):
  ```bash
  python -m uvicorn webui.app:app --host 0.0.0.0 --port 8000 --reload
  ```

- Windows launcher form:
  ```bash
  py -m uvicorn webui.app:app --host 0.0.0.0 --port 8000 --reload
  ```

Open your browser to:
- http://localhost:8000

### What you can do in the Web UI

- **Choose Campaign**: Top-left selector (Dropdown). Applies to subsequent calls.
- **View Prospects**: Paginated table (reads from `leads.csv` or `LEADS_CSV_PATH`).
- **Start Call**: Click "Start Call" for a lead. A status card appears, and the backend spawns a console agent process.
- **Call Next**: Starts the next lead automatically (based on current page end index).
- **End Current Call**: Stops the running console agent process.
- **End Session**: Stops auto-next and any running process.
- **Auto Next**: Toggle to automatically start the next call when a call ends.
- **Browser Call**: From the table you can instead trigger the browser-based call flow via `/browser/start`, and then join the room on `/browser/call`.

---

## Running from the Console (no UI)

Run the agent in interactive console mode and manage calls directly from the terminal:

```bash
python ./agent.py
```

Console features in `agent.py`:
- Prints a paginated list of prospects from `leads.csv`.
- Allows selecting a campaign pack once, then repeatedly choosing prospects.
- Spawns a single-call child process per selection using `RUN_SINGLE_CALL=1`.
- Uses the `livekit-agents` CLI under the hood via `agents.cli.run_app(...)`.

Single-call mode can also be started explicitly (used by the web UI):
```bash
RUN_SINGLE_CALL=1 python ./agent.py console
```

Note: On Windows, environment variables can be set per-command using `set` or passing via your shell; the UI handles this internally for you.

---

## Environment Variables (Complete)

- `LIVEKIT_URL` (required for browser call): LiveKit server URL (wss:// or https:// for HTTP APIs).
- `LIVEKIT_API_KEY` (required for token issuance).
- `LIVEKIT_API_SECRET` (required for token issuance).
- `LEADS_CSV_PATH` (optional): Absolute or relative path to the leads CSV.
- `LEAD_INDEX` (optional): 1-based index of the lead to use in a single-call run.
- `RUN_SINGLE_CALL` (internal): When `"1"`, the agent runs a single session and exits (used by web UI child processes).
- `CAMPAIGN_PROMPT_MODULE` (optional): Python module providing campaign prompts, default `prompts`.
- `CAMPAIGN_AGENT_NAME` (optional): Constant name for agent instructions, default `ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS`.
- `CAMPAIGN_SESSION_NAME` (optional): Constant name for session instructions, default `SESSION_INSTRUCTION`.

---

## Campaigns and Prompts

Campaigns are defined as a mapping in `agent.py` (`CAMPAIGNS`) and consumed by the UI (`webui/app.py`). Available packs:

- `prompts` (Default SplashBI pack)
- `prompts2` (SplashBI – alternate pack)
- `prompts3` (KonfHub)
- `prompts4` (Zoom Phone – DM0122)

Each prompt module exposes:
- `ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS`: Rich agent persona and dynamic behavioral guidance.
- `SESSION_INSTRUCTION`: Step-by-step script with placeholders like `[Prospect Name]`, `[Resource Name]`, `[Job Title]`, `[Company Name]`, `[____@abc.com]`.

The agent injects a structured "Lead Context" preface (from CSV fields) and performs string replacement for bracket placeholders, personalizing the script per lead.

---

## Lead CSV Format

The CSV must include these headers (case-sensitive):

```csv
prospect_name,resource_name,job_title,company_name,email,phone,timezone
```

- `resource_name` is the caller identity used in greetings (e.g., Alice Rivera).
- `timezone` can be used for UI display and future scheduling logic.

A sample file is provided at `AI_Calling_Agent/leads.csv`.

---

## Web API Endpoints (FastAPI)

Defined in `webui/app.py`.

- `GET /` — Dashboard
  - Query: `page` (int, default 1), `campaign` (str, optional)
  - Renders `templates/index.html` with leads, pagination, and campaign dropdown

- `POST /call` — Start a call for a specific lead (console mode under the hood)
  - Form: `lead_global_index` (int, zero-based), `campaign` (str, optional), `page` (int)
  - Redirects back to `/?page=...` to avoid double submit

- `POST /api/select_campaign` — Set the selected campaign
  - Form: `campaign` (str|None)
  - Response: `{ ok, campaign, campaign_label }`

- `POST /api/start_call` — Start a call for a given zero-based lead index
  - Form: `lead_global_index` (int), `campaign` (str, optional)
  - Response: `{ ok, status, lead_index, campaign, campaign_label }`

- `POST /api/end_call` — End the current call; optionally auto-start next
  - Form: `auto_next` (bool, default True)
  - Response: `{ ok, had_proc, status, lead_index, auto_next_started, campaign, campaign_label }`

- `GET /api/status` — Poll current process status
  - Response: `{ status, running, lead_index, campaign, campaign_label, auto_next, lead }`

- `POST /api/auto_next` — Toggle auto-next behavior
  - Form: `enabled` (bool)
  - Response: `{ ok, auto_next }`

- `POST /api/stop_all` — End session: disable auto-next and stop any running call
  - Response: `{ ok, status, auto_next }`

- `POST /next` — Convenience for starting the next index (used by UI button)
  - Form: `next_index` (int, zero-based), `campaign` (str, optional), `page` (int)
  - Redirects back to `/?page=...`

- `POST /browser/start` — Spawn the agent connected to a named room, redirect to browser UI
  - Form: `lead_global_index` (int), `campaign` (str, optional)
  - Redirects to `/browser/call?room=room-{index+1}&campaign=...`

- `GET /browser/call` — Browser-join page
  - Query: `room` (str, required), `campaign` (str, optional)
  - Requires `LIVEKIT_URL`. Renders `templates/browser_call.html`.

- `GET /api/token` — Issue LiveKit access token for the browser
  - Query: `room` (str), `identity` (str)
  - Requires `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
  - Response: `{ token }` (JWT signed with HS256)

- `GET /vendor/livekit-client.js` — Serve/caches LiveKit UMD build via backend
- `GET /vendor/livekit-client.esm.js` — Serve/caches LiveKit ESM build via backend

---

## Agent Runtime (agent.py)

Key components and flow:

- `Assistant(Agent)`: Configures `google.beta.realtime.RealtimeModel` with voice, temperature, and instructions.
- `entrypoint(ctx)`: Creates `AgentSession`, starts it with `RoomInputOptions` (audio-only, telephony-grade noise cancellation), connects, injects personalized session instructions, and generates the first reply.
- `CAMPAIGNS`: Mapping of human labels to `(module, agent_attr, session_attr)`.
- `_load_campaign_prompts(...)`: Dynamically import the selected prompt module/attributes (with env var fallbacks).
- `_read_leads(...)`: Reads and normalizes CSV rows.
- Console helpers: `_select_campaign_from_console()`, `_select_prospect_from_console()`.
- Main loop: Paginated console UI to select a lead; spawns child single-call processes with env propagation for campaign selection and `LEAD_INDEX`.

Voice options (via Google Realtime): `Puck, Charon, Kore, Fenrir, Aoede, Leda, Oru, Zephyr` — default is `Leda` (see `Assistant` constructor).

Noise cancellation: `noise_cancellation.BVCTelephony()` (ideal for telephony audio).

---

## Web UI Implementation (webui/)

- `webui/app.py`:
  - Creates FastAPI app, mounts `static/`, configures `Jinja2Templates` for `templates/`.
  - Reads `LEADS_CSV_PATH` (or `./leads.csv`) via `read_leads()`.
  - Spawns and manages a single console call process using `subprocess.Popen`, tracks status via globals, and offers an auto-next watcher thread.
  - Implements all routes listed above and token issuance using `PyJWT`.

- `webui/templates/base.html`:
  - Base layout with header/footer, includes Google Fonts Inter and `/static/style.css`.

- `webui/templates/index.html`:
  - Dashboard page: campaign selector, status panel, leads table with "Start Call" buttons, and client-side JS to interact with JSON APIs.
  - Toast notifications, progress bar, and a rich live call card that shows prospect details and campaign tag.

- `webui/templates/browser_call.html`:
  - ESM script that attempts to import the LiveKit Web SDK from local or CDN sources.
  - Joins the specified room using a short-lived token from `/api/token`.
  - Publishes mic, listens for audio tracks (agent speech), and exposes Join/Leave/Mute controls.

- `webui/static/style.css`:
  - Polished, dark-mode CSS with utility classes for panels, tables, badges, chips, buttons, pagination, toast, and an action bar.

---

## Dependencies

From `requirements.txt`:

- `livekit-agents` — Agent runtime and CLI utilities.
- `livekit-plugins-google` — Google Realtime integration.
- `livekit-plugins-noise-cancellation` — BVC Telephony noise suppression.
- `python-dotenv` — Load `.env` values.
- `fastapi` — Web server framework.
- `uvicorn` — ASGI server.
- `jinja2` — HTML templating.
- `PyJWT` — JWT signing for LiveKit tokens.

Optional (mentioned in README examples):
- `httpx` — Used by `webui/app.py` to fetch CDN assets (LiveKit Web SDK) with in-memory caching.

---

## Deployment Notes

- Expose the app behind a reverse proxy (nginx, Caddy, etc.) or run on a PaaS.
- Ensure environment variables are set in your hosting environment.
- For the browser-call feature, `LIVEKIT_URL` must be reachable from the user’s browser.
- Prefer HTTPS for all endpoints; ensure correct CORS/CSRF if you expose APIs cross-origin.
- Scale-out strategy: The web UI uses a single-process spawn model for calls. For high volume, consider a job queue or a worker pool and stateful tracking.

---

## Windows Notes

- Use `py -m uvicorn webui.app:app --host 0.0.0.0 --port 8000 --reload` if `python` isn’t on PATH.
- Process termination uses `proc.terminate()` best-effort on Windows; if a process lingers, use Task Manager to end the child Python process.
- When setting environment variables for one-off runs, use `set VAR=value && command` (CMD) or `$Env:VAR="value"; command` (PowerShell).

---

## Troubleshooting

- "Failed to load LiveKit client script":
  - The backend tries multiple CDNs in `GET /vendor/livekit-client*.js`. Check internet connectivity or CDN access restrictions.

- "LiveKit credentials not configured":
  - Ensure `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` are set. The `/api/token` endpoint requires these.

- No audio or the agent doesn’t respond:
  - Confirm your microphone permissions (browser).
  - Verify the agent process is running (`/api/status` shows `running: true`).
  - Check LiveKit server health and room connectivity.

- No leads loaded:
  - Verify `LEADS_CSV_PATH` or ensure `leads.csv` is present and has correct headers.

- Selecting campaign has no effect:
  - The selected campaign is applied to new calls. Existing running calls won’t change.

- Console app exits immediately:
  - When `RUN_SINGLE_CALL=1`, it runs one session and exits by design. Run `python ./agent.py` without that env for interactive mode.

---

## Security Considerations

- Do not commit `.env` with real credentials.
- JWT is signed with `HS256` using `LIVEKIT_API_SECRET`. Keep secrets safe.
- Consider rate-limiting public JSON API endpoints or placing behind auth if deployed beyond a trusted network.

---

## Roadmap Ideas

- Multi-call concurrency and queueing.
- CRM/ATS integration for logging outcomes.
- Scheduling integration based on `timezone` and availability.
- Rich analytics dashboard for call outcomes and durations.
- Pluggable TTS/STT and model providers.

---

## License

This project is licensed under the MIT License. See `LICENSE` for details.

---

## Credits

- Built with LiveKit Agents, FastAPI, and Jinja2.
- Voice and realtime LLM via `livekit-plugins-google`.
- UI/UX designed for efficient dialing workflows.