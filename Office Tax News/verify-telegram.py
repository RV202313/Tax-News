import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'News Claude' / 'scripts'))
from common import load_env
from session_guard import exclusive_session_lock
import os
from telethon import TelegramClient

async def main():
    load_env(ROOT / '.telegram_auth' / '.env')
    session = ROOT / '.telegram_auth' / 'academy_news_windows.session'
    with exclusive_session_lock(session):
        client = TelegramClient(str(session), int(os.environ['TELEGRAM_API_ID']), os.environ['TELEGRAM_API_HASH'])
        await client.connect()
        try:
            me = await client.get_me()
            if not me or (me.username or '').lower() != 'academy_of_beps':
                raise RuntimeError('Unexpected Telegram account')
            entity = await client.get_entity(-1004472011991)
            print('Account verified: @academy_of_beps')
            print('Editorial chat accessible:', entity.title)
        finally:
            await client.disconnect()

asyncio.run(main())
