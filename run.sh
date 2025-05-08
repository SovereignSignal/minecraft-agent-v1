#!/bin/bash

# Set up Python virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

# Activate the virtual environment
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Start the Streamlit frontend for the Minecraft agent
streamlit run frontend.py --server.port 8501

echo "\nVisit http://localhost:8501 to manage your Minecraft agent!" 