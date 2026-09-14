# SightGuide

SightGuide is an AI-powered assistive vision system for blind and visually impaired people. It captures live camera feeds, detects people, vehicles, obstacles, and path hazards, and provides real-time optical character recognition (OCR) / text reading with spatial clock directions, synthesized earcons, and haptic feedback.

## Architecture

```text
frontend/src/features (Camera, Live HUD, OCR, TTS) -> frontend/src/core/api -> backend/app/routes
                                                                             -> backend/app/schemas
                                                                             -> backend/app/services
                                                                             -> backend/app/ai (Multimodal Gemini Vision)
                                                                             -> backend/app/assistant & tools
```

- `frontend/src/features`: Live camera viewfinder, obstacle detection HUD, OCR reading card, Web Speech TTS, and haptics.
- `frontend/src/core`: API client with `detectObstacles`, `readTextFromImage`, and `describeScene`.
- `backend/app/routes`: `/api/guidance/detect`, `/api/guidance/read_text`, `/api/guidance/describe`, and `/api/voice/ws`.
- `backend/app/schemas`: Data models for obstacles, OCR requests/responses, vision requests, and responses.
- `backend/app/services`: Vision obstacle detection, YOLO-based object detection, and specialized OCR text reading logic.
- `backend/app/ai`: Multimodal language model providers (Gemini Vision API).
- `tests`: API, Gemini multimodal vision/OCR, and WebSocket voice pipeline tests.


## Run locally

```powershell
Copy-Item .env.example .env
python -m pip install -r backend/requirements.txt
$env:PYTHONPATH = "backend"
python -m uvicorn app.main:app --reload
```

YOLO is installed through the backend dependency file above, so it is available only to the Python/FastAPI service.

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

The API is available at `http://localhost:8000/docs`; the frontend is at `http://localhost:5173`.

## Test

```powershell
$env:PYTHONPATH = "backend"
python -m pytest
```

## Deploy without Docker (Vercel/Netlify + separate backend host)

The backend reads every setting from environment variables (`backend/app/core/config.py`),
so you do **not** deploy a `.env` file (it is gitignored anyway). You provide the
secrets as env vars on the host. See `.env.example` for the full list.

**Backend host** (Railway / Render / Fly / a VPS — whatever you like):
1. Use the root `Procfile` (sets `PYTHONPATH=backend` and runs uvicorn on `$PORT`).
   Or run manually: `PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port 8000`,
   run from the repo root.
2. Set these env vars on the host (in a secrets manager if available):
   - `GEMINI_API_KEY` (required — this is what makes the features actually work)
   - `GEMINI_MODEL`, `GOOGLE_MAPS_API_KEY`, `GOOGLE_MAPS_MAP_ID`
   - `MONGO_URI`, `MONGO_DATABASE`
   - `REDIS_URL` (optional — app falls back to in-memory cache if unset)
   - `CORS_ORIGINS` (set to your deployed frontend URL, e.g. `https://yourapp.vercel.app`)
3. Install deps: `pip install -r backend/requirements.txt`

**Frontend** (Vercel / Netlify):
1. At build time set:
   - `VITE_API_URL` = your deployed backend URL, e.g. `https://your-backend.example.com/api`
   - `VITE_GOOGLE_MAPS_API_KEY` if the UI needs the Maps key
2. Build command `npm run build` (Vite), output dir `dist`.

> Without `GEMINI_API_KEY` and a reachable `VITE_API_URL`, the app loads but the
> AI/vision/voice features will error — those two vars are what make it actually work.

## Docker

```powershell
Copy-Item .env.example .env
docker compose up --build
```
