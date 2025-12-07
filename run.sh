#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Q-Cleaner Web Panel for macOS        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo ""

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${GREEN}Creating virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate venv
echo -e "${GREEN}Activating virtual environment...${NC}"
source venv/bin/activate

# Install requirements
if [ -f "requirements.txt" ]; then
    # Check if packages are installed
    if ! pip freeze | grep -q "flask"; then
        echo -e "${GREEN}Installing dependencies...${NC}"
        pip install -r requirements.txt
    else
        echo -e "${GREEN}All packages are already installed.${NC}"
    fi
fi

# Run the web panel
echo ""
echo -e "${GREEN}Launching Q-Cleaner Web Panel...${NC}"
echo -e "${BLUE}Opening http://127.0.0.1:5050 in your browser${NC}"
echo ""
python3 app.py

# Deactivate on exit
deactivate
