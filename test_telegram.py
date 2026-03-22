import asyncio
from telethon import TelegramClient
from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate
from moonscout.config import settings

PHONE = input("Enter your phone number (e.g. +15551234567): ")

async def test():
    client = TelegramClient(
        'test_session',
        settings.telegram_api_id,
        settings.telegram_api_hash,
        device_model="PC",
        system_version="Windows 10",
        app_version="1.0",
    )
    try:
        await client.connect()
        print("TCP connected.")
        if not await client.is_user_authorized():
            print("Sending code request...")
            await client.send_code_request(PHONE)
            print("Code sent! Check your Telegram app.")
            code = input("Enter the code: ")
            await client.sign_in(PHONE, code)
        print('Connected! Me:', await client.get_me())
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
    finally:
        await client.disconnect()

asyncio.run(test())
