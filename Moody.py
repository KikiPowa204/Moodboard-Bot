from colorthief import ColorThief
import discord
import io
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
        super().__init__(command_prefix=command_prefix, intents=intents)
        
        # Initialize with None, will be set in setup_hook
        self.db = None
        self.analyzer = None
        self.logger = logging.getLogger(__name__)

    async def setup_hook(self):
        """Initialize resources with robust error handling"""
        try:
            # Initialize database first
            self.db = MySQLStorage()
            self.logger.info("Initializing database connection...")
            
            if not await self.db.initialize():
                raise RuntimeError("Failed to initialize database connection")
            
            # Initialize tables
            self.logger.info("Verifying database tables...")
            if not await self.db.init_db():
                self.logger.warning("Table initialization completed with warnings")
            
            # Initialize analyzer
            self.analyzer = ColorAnalyser()
            self.logger.info("✅ All components initialized successfully")
            
        except Exception as e:
            self.logger.critical(f"Initialization failed: {e}")
            await self.emergency_shutdown()
            raise

    async def emergency_shutdown(self):
        """Cleanup resources if initialization fails"""
        try:
            if self.analyzer:
                await self.analyzer.close()
            if self.db:
                await self.db.close()
        except Exception as e:
            self.logger.error(f"Emergency shutdown error: {e}")

    @commands.command(name='submit')
    async def submit_artwork(self, ctx, artist_name: str, social_media: str = "", title: str = "Untitled", description: str = "", *, tags: str = ""):
        """Submit an artwork with proper artist attribution"""
        if not ctx.message.attachments:
            return await ctx.send("Please attach an image file!")
        
        try:
            # Get or create submitter
            submitter = await self.db.get_or_create_submitter(
            discord_id=str(ctx.author.id),
            name=ctx.author.display_name
            )
            
            # Get or create artist
            artist = await self.db.get_or_create_artist(
            name=artist_name.strip(),
            social_media=social_media.strip()
            )
            
            # Process image
            image_url = ctx.message.attachments[0].url
            async with self.analyzer.http.get(image_url) as response:
                image_data = await response.read()
            
            # Analyze colors
            with io.BytesIO(image_data) as buffer:
                palette = await self.analyzer.extract_palettes(buffer)
            
            # Store artwork
            artwork_id = await self.db.create_artwork(
            submitter_id=submitter['id'],
            artist_id=artist['id'],
            image_url=image_url,
            title=title,
            description=description,
            tags=[t.strip() for t in tags.split(",") if t.strip()]
            )
            
            # Store color palette
            for i, color in enumerate(palette):
                await self.db.add_color_to_palette(
                    artwork_id=artwork_id,
                    hex_code=color['hex'],
                    dominance_rank=i+1,
                    coverage=color['percentage']
            )
            
            await ctx.send(f"✅ Artwork submitted successfully! Artist: {artist_name}")

        except Exception as e:
            self.logger.error(f"Submission failed: {e}")
            await ctx.send("⚠️ Error processing your artwork")

    @commands.command(name='display')
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
            await self.submit_artwork(message)
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