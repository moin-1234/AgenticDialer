@echo off
echo Deploying AI Calling Agent Frontend to Vercel...
echo.

echo Checking if Vercel CLI is installed...
vercel --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing Vercel CLI globally...
    npm install -g vercel
    echo.
)

echo Navigating to frontend directory...
cd frontend

echo Installing/updating dependencies...
npm install

echo Building the project...
npm run build

echo Deploying to Vercel...
echo Note: Make sure to set VITE_API_BASE_URL in your Vercel project settings
echo.
vercel --prod

echo.
echo Deployment complete!
echo Remember to:
echo 1. Set VITE_API_BASE_URL environment variable in Vercel dashboard
echo 2. Deploy your backend to a separate service (Railway, Heroku, etc.)
echo 3. Update CORS settings in backend with your Vercel domain

pause