#!/bin/bash

# Q-Cleaner Web Panel Runner
# Creates venv, installs dependencies, and launches web panel

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
PYTHON_SCRIPT="$SCRIPT_DIR/web.py"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

echo -e "${BOLD}${CYAN}╔════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║       Q-Cleaner Web Panel for macOS        ║${NC}"
echo -e "${BOLD}${CYAN}╚════════════════════════════════════════════╝${NC}"
echo ""

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed.${NC}"
    echo "Please install Python 3 first: brew install python3"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo -e "${RED}Failed to create virtual environment.${NC}"
        exit 1
    fi
    echo -e "${GREEN}Virtual environment created.${NC}"
fi

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source "$VENV_DIR/bin/activate"

if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to activate virtual environment.${NC}"
    exit 1
fi

# Check if packages are installed, install if needed
check_and_install_packages() {
    if [ -f "$REQUIREMENTS" ]; then
        # Check if flask is installed
        if ! python3 -c "import flask" &> /dev/null; then
            echo -e "${YELLOW}Installing required packages...${NC}"
            pip install --upgrade pip -q
            pip install -r "$REQUIREMENTS" -q
            if [ $? -eq 0 ]; then
                echo -e "${GREEN}Packages installed successfully.${NC}"
            else
                echo -e "${RED}Failed to install packages.${NC}"
                exit 1
            fi
        else
            echo -e "${GREEN}All packages are already installed.${NC}"
        fi
    else
        echo -e "${YELLOW}No requirements.txt found, installing flask...${NC}"
        pip install flask -q
    fi
}

check_and_install_packages

echo ""
echo -e "${GREEN}Launching Q-Cleaner Web Panel...${NC}"
echo -e "${CYAN}Opening http://127.0.0.1:5050 in your browser${NC}"
echo ""

# Run the Python script
python3 "$PYTHON_SCRIPT"

# Deactivate virtual environment on exit
deactivate 2>/dev/null
