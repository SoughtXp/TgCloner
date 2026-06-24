import sys
from colorama import Fore

def main():
    if '--cli' in sys.argv:
        from src.client import get_client
        from src.cloner import run_cloner
        client = get_client()
        with client:
            try:
                client.loop.run_until_complete(run_cloner(client))
            except (KeyboardInterrupt, SystemExit):
                print(f"\n{Fore.RED}Script closed.")
    else:
        print(f"{Fore.GREEN}Starting TGClonerX Web Dashboard...")
        print(f"{Fore.WHITE}Open your browser at: {Fore.CYAN}http://localhost:5000\n")
        try:
            from server import app
            app.run(host='0.0.0.0', port=5000, debug=False)
        except (KeyboardInterrupt, SystemExit):
            print(f"\n{Fore.RED}Web Server closed.")

if __name__ == '__main__':
    main()
