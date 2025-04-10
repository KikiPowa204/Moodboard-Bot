from Moody import MoodyBot
import os
import asyncio
import logging
async def main():
    bot = MoodyBot()
    try:
        await bot.start(os.getenv('DISCORD_TOKEN'))
    except Exception as e:
        logging.critical(f"Bot crashed: {e}")
    finally:
        await bot.close()

if __name__ == '__main__':
    asyncio.run(main())