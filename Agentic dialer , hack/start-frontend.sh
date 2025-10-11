#!/bin/bash

echo "Starting AI Calling Agent React Frontend..."
echo

echo "Checking if dependencies are installed..."
cd frontend

if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

echo
echo "Starting development server..."
echo "Frontend will be available at: http://localhost:3000"
echo "Make sure your FastAPI backend is running on port 8000"
echo

npm run dev