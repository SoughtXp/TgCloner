from telethon import TelegramClient
from src.config import load_config

_client = None

def get_client(session_name='tgclonerx_session', loop=None):
    global _client
    if _client is None:
        api_id, api_hash = load_config()
        _client = TelegramClient(session_name, api_id, api_hash, loop=loop)
    return _client
