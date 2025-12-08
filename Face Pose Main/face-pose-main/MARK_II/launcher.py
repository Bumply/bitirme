#!/usr/bin/env python3
"""
MARK II Wheelchair Control System - Interactive Launcher
Easy-to-use menu for running and managing the system
"""

import os
import sys
import subprocess
import time
import signal

# Change to script directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

# Colors
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

def clear_screen():
    os.system('clear' if os.name != 'nt' else 'cls')

def print_header():
    clear_screen()
    print(f"{Colors.CYAN}╔══════════════════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.END}  {Colors.BOLD}MARK II - Face-Controlled Wheelchair System{Colors.END}            {Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.END}  {Colors.YELLOW}Version 2.0.0{Colors.END}                                          {Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}╚══════════════════════════════════════════════════════════╝{Colors.END}")
    print()

def check_status():
    print(f"{Colors.BLUE}System Status:{Colors.END}")
    print("─────────────────────────────────────")
    
    # Check Python
    print(f"  Python:     {Colors.GREEN}✓{Colors.END} {sys.version.split()[0]}")
    
    # Check config
    if os.path.exists("config/config.yaml"):
        print(f"  Config:     {Colors.GREEN}✓{Colors.END} Found")
    else:
        print(f"  Config:     {Colors.RED}✗ Missing{Colors.END}")
    
    # Check if on Raspberry Pi
    is_pi = os.path.exists("/etc/rpi-issue")
    
    if is_pi:
        # Check camera
        if os.path.exists("/dev/video0"):
            print(f"  Camera:     {Colors.GREEN}✓{Colors.END} Detected")
        else:
            print(f"  Camera:     {Colors.RED}✗ Not detected{Colors.END}")
        
        # Check Arduino
        if os.path.exists("/dev/ttyUSB0") or os.path.exists("/dev/ttyACM0"):
            print(f"  Arduino:    {Colors.GREEN}✓{Colors.END} Connected")
        else:
            print(f"  Arduino:    {Colors.YELLOW}○ Not connected{Colors.END}")
    else:
        print(f"  Platform:   {Colors.YELLOW}─{Colors.END} Not on Raspberry Pi")
    
    # Check if app is running
    try:
        result = subprocess.run(['pgrep', '-f', 'python.*main.py'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  App Status: {Colors.GREEN}● Running{Colors.END}")
        else:
            print(f"  App Status: {Colors.YELLOW}○ Not running{Colors.END}")
    except:
        print(f"  App Status: {Colors.YELLOW}○ Unknown{Colors.END}")
    
    print("─────────────────────────────────────")
    print()

def kill_processes():
    print(f"{Colors.YELLOW}Stopping any running instances...{Colors.END}")
    try:
        subprocess.run(['pkill', '-9', '-f', 'python.*main.py'], 
                      stderr=subprocess.DEVNULL)
        subprocess.run(['pkill', '-9', '-f', 'libcamera'], 
                      stderr=subprocess.DEVNULL)
    except:
        pass
    time.sleep(1)
    print(f"{Colors.GREEN}Done.{Colors.END}")

def run_app():
    print_header()
    print(f"{Colors.GREEN}Starting Face-Controlled Wheelchair System...{Colors.END}")
    print()
    print(f"{Colors.CYAN}╔═══════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.END}  {Colors.BOLD}CONTROLS:{Colors.END}                            {Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.END}                                         {Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.END}  Look UP      → Move FORWARD            {Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.END}  Look DOWN    → Move BACKWARD           {Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.END}  Look LEFT    → Turn LEFT               {Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.END}  Look RIGHT   → Turn RIGHT              {Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.END}                                         {Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.END}  {Colors.YELLOW}RAISE EYEBROWS → Toggle ON/OFF{Colors.END}       {Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}╚═══════════════════════════════════════╝{Colors.END}")
    print()
    print(f"{Colors.YELLOW}First 8 seconds: CALIBRATION - Look straight ahead!{Colors.END}")
    print()
    print(f"{Colors.RED}Press Ctrl+C to stop{Colors.END}")
    print()
    print("═" * 50)
    
    kill_processes()
    
    # Create logs directory
    os.makedirs("logs", exist_ok=True)
    os.makedirs("src/logs", exist_ok=True)
    
    # Run the application
    os.chdir("src")
    try:
        subprocess.run([sys.executable, "main.py"])
    except KeyboardInterrupt:
        pass
    os.chdir("..")
    
    print()
    print(f"{Colors.YELLOW}Application stopped.{Colors.END}")
    input("Press Enter to return to menu...")

def view_logs():
    print_header()
    print(f"{Colors.BLUE}Recent Logs:{Colors.END}")
    print("─────────────────────────────────────")
    
    log_file = "src/logs/__main__.log"
    if os.path.exists(log_file):
        print(f"{Colors.CYAN}Last 30 lines:{Colors.END}")
        print()
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                for line in lines[-30:]:
                    print(line.rstrip())
        except Exception as e:
            print(f"Error reading log: {e}")
    else:
        print(f"{Colors.YELLOW}No logs found yet.{Colors.END}")
    
    print()
    input("Press Enter to return to menu...")

def view_errors():
    print_header()
    print(f"{Colors.RED}Error Logs:{Colors.END}")
    print("─────────────────────────────────────")
    
    log_file = "src/logs/__main___errors.log"
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r') as f:
                content = f.read().strip()
                if content:
                    lines = content.split('\n')
                    for line in lines[-50:]:
                        print(line)
                else:
                    print(f"{Colors.GREEN}Error log is empty (this is good!){Colors.END}")
        except Exception as e:
            print(f"Error reading log: {e}")
    else:
        print(f"{Colors.GREEN}No error log found (this is good!){Colors.END}")
    
    print()
    input("Press Enter to return to menu...")

def clear_logs():
    print_header()
    print(f"{Colors.YELLOW}Clearing all logs...{Colors.END}")
    
    import glob
    for pattern in ["src/logs/*.log", "logs/*.log"]:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
            except:
                pass
    
    print(f"{Colors.GREEN}Logs cleared.{Colors.END}")
    time.sleep(1)

def reset_camera():
    print_header()
    print(f"{Colors.YELLOW}Resetting camera...{Colors.END}")
    
    kill_processes()
    
    # Try libcamera reset
    try:
        subprocess.run(['timeout', '2', 'libcamera-hello', '--nopreview', '-t', '1'],
                      stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        print(f"{Colors.GREEN}Camera reset successful.{Colors.END}")
    except:
        print(f"{Colors.YELLOW}Camera reset attempted.{Colors.END}")
    
    time.sleep(2)

def update_git():
    print_header()
    print(f"{Colors.BLUE}Updating from GitHub...{Colors.END}")
    print()
    
    result = subprocess.run(['git', 'pull', 'origin', 'master'])
    
    print()
    if result.returncode == 0:
        print(f"{Colors.GREEN}Update successful!{Colors.END}")
    else:
        print(f"{Colors.RED}Update failed.{Colors.END}")
    
    input("Press Enter to return to menu...")

def show_help():
    print_header()
    print(f"{Colors.CYAN}╔═══════════════════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.END}  {Colors.BOLD}HOW TO USE THE WHEELCHAIR SYSTEM{Colors.END}                       {Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}╚═══════════════════════════════════════════════════════════╝{Colors.END}")
    print()
    print(f"{Colors.BOLD}1. SETUP{Colors.END}")
    print("   • Connect camera to Raspberry Pi ribbon port")
    print("   • Connect Arduino via USB cable")
    print("   • Position yourself ~50cm from camera")
    print()
    print(f"{Colors.BOLD}2. CALIBRATION (First 8 seconds after start){Colors.END}")
    print("   • Look STRAIGHT at the camera")
    print("   • Keep your head STILL")
    print("   • This sets your 'neutral' head position")
    print()
    print(f"{Colors.BOLD}3. CONTROLS{Colors.END}")
    print("   ┌───────────────────────────────────────┐")
    print("   │  HEAD MOVEMENT      →  WHEELCHAIR     │")
    print("   │  ─────────────────────────────────    │")
    print("   │  Look UP            →  Forward        │")
    print("   │  Look DOWN          →  Backward       │")
    print("   │  Look LEFT          →  Turn Left      │")
    print("   │  Look RIGHT         →  Turn Right     │")
    print("   │  ─────────────────────────────────    │")
    print("   │  RAISE BOTH BROWS   →  Toggle ON/OFF  │")
    print("   └───────────────────────────────────────┘")
    print()
    print(f"{Colors.BOLD}4. SAFETY FEATURES{Colors.END}")
    print(f"   • Wheelchair starts {Colors.RED}DISABLED{Colors.END}")
    print(f"   • Raise eyebrows to {Colors.GREEN}ENABLE{Colors.END}")
    print(f"   • Raise eyebrows again to {Colors.RED}DISABLE{Colors.END}")
    print(f"   • Face lost for 2 sec → Auto {Colors.RED}DISABLE{Colors.END}")
    print()
    print(f"{Colors.BOLD}5. TROUBLESHOOTING{Colors.END}")
    print("   • Camera busy?     → Use 'Reset Camera' (option 7)")
    print("   • App frozen?      → Use 'Stop Application' (option 2)")
    print("   • Seeing errors?   → Use 'View Error Logs' (option 5)")
    print("   • Need updates?    → Use 'Update from GitHub' (option 8)")
    print()
    input("Press Enter to return to menu...")

def main():
    while True:
        print_header()
        check_status()
        
        print(f"{Colors.BOLD}Main Menu:{Colors.END}")
        print("─────────────────────────────────────")
        print(f"  {Colors.GREEN}1){Colors.END} ▶  Start Application")
        print(f"  {Colors.GREEN}2){Colors.END} ◼  Stop Application")
        print(f"  {Colors.GREEN}3){Colors.END} 📋 View Recent Logs")
        print(f"  {Colors.GREEN}4){Colors.END} ⚠  View Error Logs")
        print(f"  {Colors.GREEN}5){Colors.END} 🗑  Clear Logs")
        print(f"  {Colors.GREEN}6){Colors.END} 📷 Reset Camera")
        print(f"  {Colors.GREEN}7){Colors.END} ⬇  Update from GitHub")
        print(f"  {Colors.GREEN}8){Colors.END} ❓ Help / How to Use")
        print(f"  {Colors.GREEN}0){Colors.END} ✕  Exit")
        print("─────────────────────────────────────")
        print()
        
        try:
            choice = input("Select option [0-8]: ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = '0'
        
        if choice == '1':
            run_app()
        elif choice == '2':
            kill_processes()
            time.sleep(1)
        elif choice == '3':
            view_logs()
        elif choice == '4':
            view_errors()
        elif choice == '5':
            clear_logs()
        elif choice == '6':
            reset_camera()
        elif choice == '7':
            update_git()
        elif choice == '8':
            show_help()
        elif choice == '0':
            print_header()
            print(f"{Colors.GREEN}Goodbye!{Colors.END}")
            sys.exit(0)
        else:
            print(f"{Colors.RED}Invalid option.{Colors.END}")
            time.sleep(1)

if __name__ == "__main__":
    main()
