# AI Calling Agent - Batch Files Guide

## Available Batch Files

### 🚀 `start-backend.bat`
Starts the FastAPI backend server
- Creates/activates Python virtual environment
- Installs dependencies from requirements.txt
- Runs backend on http://localhost:8000
- **Preserves all existing backend functionality**

### 🎨 `start-frontend.bat` 
Starts the React frontend development server
- Installs npm dependencies if needed
- Runs frontend on http://localhost:3000
- Hot-reload enabled for development

### 🔥 `start-both.bat`
Starts both backend and frontend services simultaneously
- Launches backend in background
- Launches frontend in background
- Shows status for both services
- Press any key to stop all services

### ☁️ `deploy-vercel.bat`
Deploys frontend to Vercel
- Installs Vercel CLI if needed
- Builds production-ready frontend
- Deploys to Vercel hosting
- Shows deployment configuration instructions

## Quick Start

1. **For local development:**
   ```bash
   # Start everything at once
   start-both.bat
   
   # Or start individually
   start-backend.bat    # Terminal 1
   start-frontend.bat   # Terminal 2
   ```

2. **For production deployment:**
   ```bash
   # Deploy frontend to Vercel
   deploy-vercel.bat
   
   # Deploy backend separately (see DEPLOYMENT_GUIDE.md)
   ```

## Important Notes

- **Backend Preservation**: All existing FastAPI functionality is preserved
- **CORS Configuration**: Backend is configured to accept requests from frontend
- **Environment Variables**: Different configs for development/production
- **Vercel Ready**: Frontend is ready for Vercel deployment out of the box

## Access Points

- **Frontend (React)**: http://localhost:3000
- **Backend (FastAPI)**: http://localhost:8000  
- **API Documentation**: http://localhost:8000/docs
- **Backend Web UI**: http://localhost:8000 (original interface)

Both the new React frontend and original web interface work simultaneously with the same backend!