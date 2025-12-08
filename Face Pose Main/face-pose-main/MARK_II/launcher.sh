#!/bin/bash
# MARK II Wheelchair Control System - Interactive Launcher
# Easy-to-use menu for running and managing the system

# Colors for better visibility
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Change to the MARK_II directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Function to print header
print_header() {
    clear
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  ${BOLD}MARK II - Face-Controlled Wheelchair System${NC}            ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  ${YELLOW}Version 2.0.0${NC}                                          ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Function to check system status
check_status() {
    echo -e "${BLUE}System Status:${NC}"
    echo "─────────────────────────────────────"
    
    # Check if Python is available
    if command -v python3 &> /dev/null; then
        py_ver=$(python3 --version 2>&1)
        echo -e "  Python:     ${GREEN}✓${NC} $py_ver"
    else
        echo -e "  Python:     ${RED}✗ Not found${NC}"
    fi
    
    # Check if config exists
    if [ -f "config/config.yaml" ]; then
        echo -e "  Config:     ${GREEN}✓${NC} Found"
    else
        echo -e "  Config:     ${RED}✗ Missing${NC}"
    fi
    
    # Check camera (Raspberry Pi only)
    if [ -f /etc/rpi-issue ]; then
        if [ -e /dev/video0 ] || vcgencmd get_camera 2>/dev/null | grep -q "detected=1"; then
            echo -e "  Camera:     ${GREEN}✓${NC} Detected"
        else
            echo -e "  Camera:     ${RED}✗ Not detected${NC}"
        fi
        
        # Check if camera is busy
        if lsof /dev/video0 2>/dev/null | grep -q .; then
            echo -e "  Camera:     ${YELLOW}⚠ In use by another process${NC}"
        fi
    else
        echo -e "  Camera:     ${YELLOW}─${NC} (Not on Raspberry Pi)"
    fi
    
    # Check if main.py is running
    if pgrep -f "python.*main.py" > /dev/null; then
        echo -e "  App Status: ${GREEN}● Running${NC}"
    else
        echo -e "  App Status: ${YELLOW}○ Not running${NC}"
    fi
    
    # Check Arduino connection
    if [ -e /dev/ttyUSB0 ] || [ -e /dev/ttyACM0 ]; then
        echo -e "  Arduino:    ${GREEN}✓${NC} Connected"
    else
        echo -e "  Arduino:    ${YELLOW}○ Not connected${NC}"
    fi
    
    echo "─────────────────────────────────────"
    echo ""
}

# Function to kill existing processes
kill_processes() {
    echo -e "${YELLOW}Stopping any running instances...${NC}"
    pkill -9 -f "python.*main.py" 2>/dev/null
    pkill -9 -f "libcamera" 2>/dev/null
    sleep 1
    echo -e "${GREEN}Done.${NC}"
}

# Function to run the main application
run_app() {
    print_header
    echo -e "${GREEN}Starting Face-Controlled Wheelchair System...${NC}"
    echo ""
    echo -e "${CYAN}Controls:${NC}"
    echo "  • Look UP     → Move Forward"
    echo "  • Look DOWN   → Move Backward"  
    echo "  • Look LEFT   → Turn Left"
    echo "  • Look RIGHT  → Turn Right"
    echo "  • RAISE EYEBROWS → Toggle Enable/Disable"
    echo ""
    echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
    echo ""
    echo "─────────────────────────────────────"
    
    # Kill any existing processes first
    kill_processes
    
    # Create logs directory
    mkdir -p logs src/logs
    
    # Run the application
    cd src
    python3 main.py
    cd ..
    
    echo ""
    echo -e "${YELLOW}Application stopped.${NC}"
    read -p "Press Enter to return to menu..."
}

# Function to run with debug output
run_debug() {
    print_header
    echo -e "${YELLOW}Starting in DEBUG mode (verbose logging)...${NC}"
    echo ""
    
    kill_processes
    mkdir -p logs src/logs
    
    cd src
    python3 -u main.py 2>&1 | tee ../logs/debug_$(date +%Y%m%d_%H%M%S).log
    cd ..
    
    echo ""
    echo -e "${YELLOW}Debug session ended.${NC}"
    read -p "Press Enter to return to menu..."
}

# Function to view logs
view_logs() {
    print_header
    echo -e "${BLUE}Recent Logs:${NC}"
    echo "─────────────────────────────────────"
    
    if [ -f "src/logs/__main__.log" ]; then
        echo -e "${CYAN}Last 30 lines of main log:${NC}"
        echo ""
        tail -30 src/logs/__main__.log
    else
        echo -e "${YELLOW}No logs found.${NC}"
    fi
    
    echo ""
    echo "─────────────────────────────────────"
    read -p "Press Enter to return to menu..."
}

# Function to view errors
view_errors() {
    print_header
    echo -e "${RED}Error Logs:${NC}"
    echo "─────────────────────────────────────"
    
    if [ -f "src/logs/__main___errors.log" ]; then
        echo -e "${RED}Recent errors:${NC}"
        echo ""
        tail -50 src/logs/__main___errors.log
    else
        echo -e "${GREEN}No error log found (this is good!).${NC}"
    fi
    
    echo ""
    echo "─────────────────────────────────────"
    read -p "Press Enter to return to menu..."
}

# Function to clear logs
clear_logs() {
    print_header
    echo -e "${YELLOW}Clearing all logs...${NC}"
    rm -rf src/logs/*.log logs/*.log 2>/dev/null
    echo -e "${GREEN}Logs cleared.${NC}"
    sleep 1
}

# Function to stop app
stop_app() {
    print_header
    echo -e "${YELLOW}Stopping application...${NC}"
    kill_processes
    echo -e "${GREEN}Application stopped.${NC}"
    sleep 1
}

# Function to reboot camera
reboot_camera() {
    print_header
    echo -e "${YELLOW}Resetting camera...${NC}"
    
    # Kill any processes using camera
    pkill -9 -f "python.*main.py" 2>/dev/null
    pkill -9 -f "libcamera" 2>/dev/null
    sleep 1
    
    # Try to reset camera module
    if command -v libcamera-hello &> /dev/null; then
        echo "Testing camera..."
        timeout 2 libcamera-hello --nopreview -t 1 2>/dev/null
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}Camera reset successful.${NC}"
        else
            echo -e "${YELLOW}Camera may need a system reboot.${NC}"
        fi
    fi
    
    sleep 2
}

# Function to show help
show_help() {
    print_header
    echo -e "${CYAN}How to Use the Wheelchair System:${NC}"
    echo "═══════════════════════════════════════════════════════════"
    echo ""
    echo -e "${BOLD}1. SETUP${NC}"
    echo "   • Make sure the camera is connected to the Raspberry Pi"
    echo "   • Connect Arduino via USB cable"
    echo "   • Position yourself in front of the camera"
    echo ""
    echo -e "${BOLD}2. CALIBRATION (First 8 seconds)${NC}"
    echo "   • Look straight at the camera"
    echo "   • Keep your head still"
    echo "   • This sets your 'neutral' position"
    echo ""
    echo -e "${BOLD}3. CONTROLS${NC}"
    echo "   ┌─────────────────────────────────────┐"
    echo "   │  Look UP      → Move FORWARD        │"
    echo "   │  Look DOWN    → Move BACKWARD       │"
    echo "   │  Look LEFT    → Turn LEFT           │"
    echo "   │  Look RIGHT   → Turn RIGHT          │"
    echo "   │  RAISE BROWS  → Toggle ON/OFF       │"
    echo "   └─────────────────────────────────────┘"
    echo ""
    echo -e "${BOLD}4. SAFETY${NC}"
    echo "   • Wheelchair starts DISABLED"
    echo "   • Raise eyebrows to ENABLE movement"
    echo "   • Raise eyebrows again to DISABLE"
    echo "   • If face is lost for 2 seconds → auto DISABLE"
    echo ""
    echo -e "${BOLD}5. TROUBLESHOOTING${NC}"
    echo "   • Camera busy?  → Use 'Reset Camera' option"
    echo "   • App frozen?   → Use 'Stop Application'"
    echo "   • Check errors  → Use 'View Error Logs'"
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    read -p "Press Enter to return to menu..."
}

# Function to update from git
update_from_git() {
    print_header
    echo -e "${BLUE}Updating from GitHub...${NC}"
    echo ""
    
    git pull origin master
    
    echo ""
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Update successful!${NC}"
    else
        echo -e "${RED}Update failed. Check your internet connection.${NC}"
    fi
    
    read -p "Press Enter to return to menu..."
}

# Main menu loop
while true; do
    print_header
    check_status
    
    echo -e "${BOLD}Main Menu:${NC}"
    echo "─────────────────────────────────────"
    echo -e "  ${GREEN}1)${NC} ▶  Start Application"
    echo -e "  ${GREEN}2)${NC} ◼  Stop Application"
    echo -e "  ${GREEN}3)${NC} 🔧 Start in Debug Mode"
    echo -e "  ${GREEN}4)${NC} 📋 View Recent Logs"
    echo -e "  ${GREEN}5)${NC} ⚠  View Error Logs"
    echo -e "  ${GREEN}6)${NC} 🗑  Clear Logs"
    echo -e "  ${GREEN}7)${NC} 📷 Reset Camera"
    echo -e "  ${GREEN}8)${NC} ⬇  Update from GitHub"
    echo -e "  ${GREEN}9)${NC} ❓ Help / How to Use"
    echo -e "  ${GREEN}0)${NC} ✕  Exit"
    echo "─────────────────────────────────────"
    echo ""
    
    read -p "Select option [0-9]: " choice
    
    case $choice in
        1) run_app ;;
        2) stop_app ;;
        3) run_debug ;;
        4) view_logs ;;
        5) view_errors ;;
        6) clear_logs ;;
        7) reboot_camera ;;
        8) update_from_git ;;
        9) show_help ;;
        0) 
            print_header
            echo -e "${GREEN}Goodbye!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option. Please try again.${NC}"
            sleep 1
            ;;
    esac
done
