import os
from colorama import init, Fore

init(autoreset=True)

CONFIG_FILE = "config.txt"

_API_ID = None
_API_HASH = None

def get_credentials():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            lines = f.read().splitlines()
            if len(lines) >= 2:
                try:
                    return int(lines[0].strip()), lines[1].strip()
                except ValueError:
                    pass
    
    print(f"{Fore.YELLOW}=== INITIAL CONFIGURATION (FIRST TIME ONLY) ===")
    print(f"{Fore.WHITE}Get your credentials from: {Fore.CYAN}https://my.telegram.org\n")
    
    while True:
        try:
            api_id = int(input(f"{Fore.GREEN}Paste your API ID (numbers only): {Fore.WHITE}").strip())
            break
        except ValueError:
            print(f"{Fore.RED}Invalid ID. It must be numbers only.")
            
    api_hash = input(f"{Fore.GREEN}Paste your API HASH: {Fore.WHITE}").strip()
    
    with open(CONFIG_FILE, "w") as f:
        f.write(f"{api_id}\n{api_hash}")
        
    print(f"\n{Fore.GREEN}✓ Credentials saved to {CONFIG_FILE}!\n")
    return api_id, api_hash

def load_config():
    global _API_ID, _API_HASH
    if _API_ID is None or _API_HASH is None:
        _API_ID, _API_HASH = get_credentials()
    return _API_ID, _API_HASH
