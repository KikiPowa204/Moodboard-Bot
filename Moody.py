from colorthief import ColorThief
import discord
from io import BytesIO
import logging
import os
import asyncio
from typing import Optional
from mysql.connector import Error    # Moody.py
import pathlib
from lib.database import MySQLStorage
from lib.analyser import ColorAnalyser
# In Moody.py
from discord.ext import commands
import math
import discord
import logging
import aiohttp

pending_submissions = {}  # Format: {prompt_message_id: original_message_data}
intents = discord.Intents.default()
intents.message_content = True
# Custom database module
#Update this bitch
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default settings

# Runtime storage

class MoodyBot(commands.Bot):
    def __init__(self, command_prefix='!'):
        intents = discord.Intents.all()
        intents.message_content = True
        super().__init__(command_prefix=command_prefix, intents=intents)  # Proper parent init

        self.db = MySQLStorage()
        self.analyzer = None
        self.logger = logging.getLogger(__name__)

    async def setup_hook(self):
        """Proper async initialization"""
        try:
            # Initialize database
            self.db = MySQLStorage()
            await self.db.initialize()
            
            # Initialize analyzer
            self.analyzer = ColorAnalyser()
            
            # Verify all components
            if not all([self.db, self.analyzer]):
                raise RuntimeError("Component initialization failed")
                
            self.logger.info("All components initialized successfully")
            
        except Exception as e:
            self.logger.critical(f"Initialization failed: {e}")
            await self.emergency_shutdown()
            raise

    async def emergency_shutdown(self):
        """Cleanup resources if initialization fails"""
        if self.analyzer:
            await self.analyzer.close()
        if self.db:
            await self.db.close()

    async def close(self):
        """Proper shutdown sequence"""
        try:
            if self.analyzer:
                await self.analyzer.close()
            if self.db:
                await self.db.close()
        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")
        finally:
            await super().close()

    @commands.command()
    async def artworks(self, ctx, page: int = 1):
        """View your submitted artworks"""
        try:
            per_page = 5
            artist = await self.db.get_or_create_artist(
                discord_id=str(ctx.author.id),
                name=ctx.author.display_name
            )
            
            artworks = await self.db.get_artworks(artist['id'], page, per_page)
            total = await self.db.count_artworks(artist['id'])
            
            if not artworks:
                return await ctx.send("No artworks found!")
                
            embed = discord.Embed(
                title=f"Your Art Collection (Page {page}/{max(1, (total + per_page - 1) // per_page)})",
                color=0x6E85B2
            )
            
            for art in artworks:
                palette = await self.db.get_palette(art['id'])
                embed.add_field(
                    name=art.get('title', 'Untitled'),
                    value=f"Colors: {', '.join(c['hex_code'] for c in palette[:3])}",
                    inline=False
                )
                
            await ctx.send(embed=embed)
            
        except Exception as e:
            self.logger.error(f"Artworks command failed: {e}")
            await ctx.send("⚠️ Error fetching artworks")

    async def on_message(self, message):
        if message.author.bot:
            return
            
        await self.process_commands(message)
        
        # Process image attachments in supported channels
        if (message.attachments and 
            isinstance(message.channel, (discord.TextChannel, discord.Thread))):
            await self.process_submission(message)
async def main():
    try:
        # Verify environment first
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise ValueError("DISCORD_TOKEN environment variable missing")
        
        bot = MoodyBot()
        await bot.start(token)  # Better than run() for control
        
    except Exception as e:
        logging.critical(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run with proper cleanup
    asyncio.run(main())