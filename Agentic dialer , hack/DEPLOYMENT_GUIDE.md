# Deployment Guide for AI Calling Agent

## Quick Start with Batch Files

### Starting Backend Only
```bash
# Windows
start-backend.bat
```
This will:
- Create and activate a Python virtual environment
- Install dependencies from requirements.txt
- Start the FastAPI backend on http://localhost:8000

### Starting Frontend Only
```bash
# Windows
start-frontend.bat
```
This will:
- Install npm dependencies if needed
- Start the React development server on http://localhost:3000

### Starting Both Services
```bash
# Windows  
start-both.bat
```
This will:
- Start both backend and frontend services
- Automatically open browser windows for both
- Press any key to stop all services

## Vercel Deployment (Frontend Only)

### Prerequisites
1. Install Vercel CLI: `npm install -g vercel`
2. Login to Vercel: `vercel login`

### Deploy Frontend to Vercel
1. Navigate to the project root:
   ```bash
   cd AI_Calling_Agent
   ```

2. Deploy to Vercel:
   ```bash
   vercel
   ```

3. Configure your backend URL in production:
   - Update `frontend/.env.production` with your backend domain
   - Or set the environment variable in Vercel dashboard

### Environment Variables for Vercel
Set these in your Vercel project settings:
- `VITE_API_BASE_URL`: Your backend API URL (e.g., `https://your-backend.com`)

## Backend Deployment Options

Since Vercel doesn't support Python FastAPI, you'll need to deploy the backend separately:

### Option 1: Railway
1. Connect your GitHub repository to Railway
2. Create a new project and select the root directory
3. Set environment variables as needed
4. Railway will automatically detect and deploy your FastAPI app

### Option 2: Heroku
1. Create a `Procfile` in the root directory:
   ```
   web: uvicorn webui.app:app --host 0.0.0.0 --port $PORT
   ```
2. Deploy using Heroku CLI or GitHub integration

### Option 3: DigitalOcean App Platform
1. Connect your repository
2. Select Python runtime
3. Set the run command: `uvicorn webui.app:app --host 0.0.0.0 --port $PORT`

### Option 4: Self-hosted VPS
1. Clone repository on your server
2. Install Python and dependencies
3. Use a process manager like PM2 or systemd
4. Set up reverse proxy with Nginx

## Environment Variables

### Backend (.env file in root)
```
LIVEKIT_URL=your_livekit_url
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret
GOOGLE_API_KEY=your_google_api_key
LEADS_CSV_PATH=./leads.csv
SUPABASE_URL=your_supabase_url (optional)
SUPABASE_SERVICE_ROLE_KEY=your_supabase_key (optional)
```

### Frontend
- Development: `VITE_API_BASE_URL=http://localhost:8000`
- Production: `VITE_API_BASE_URL=https://your-backend-domain.com`

## Full Production Setup

1. Deploy backend to your preferred platform
2. Update `frontend/.env.production` with your backend URL
3. Deploy frontend to Vercel
4. Ensure CORS is properly configured in your backend for your frontend domain

## Local Development

1. Start backend: `start-backend.bat`
2. Start frontend: `start-frontend.bat`
3. Access the application at http://localhost:3000

The backend preserves all existing functionality while the frontend provides a modern React interface.