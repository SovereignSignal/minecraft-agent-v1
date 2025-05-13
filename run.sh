#!/bin/bash
set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting Minecraft Agent Setup...${NC}"

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed.${NC}"
    exit 1
fi

# Set up Python virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv || { 
        echo -e "${RED}Failed to create virtual environment. Please check your Python installation.${NC}"; 
        exit 1; 
    }
    echo -e "${GREEN}Virtual environment created successfully.${NC}"
fi

# Activate the virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source venv/bin/activate || {
    echo -e "${RED}Failed to activate virtual environment.${NC}"
    exit 1
}

# Verify activation
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo -e "${RED}Virtual environment activation failed.${NC}"
    exit 1
fi

# Install dependencies
echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip || {
    echo -e "${RED}Failed to upgrade pip.${NC}"
    exit 1
}

echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -r requirements.txt || {
    echo -e "${RED}Failed to install dependencies.${NC}"
    exit 1
}
echo -e "${GREEN}Dependencies installed successfully.${NC}"

# Start the Streamlit frontend for the Minecraft agent
echo -e "${GREEN}Starting Minecraft Agent frontend...${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
streamlit run frontend.py --server.port 8501

echo -e "\n${GREEN}Visit http://localhost:8501 to manage your Minecraft agent!${NC}"