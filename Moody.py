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
bot = commands.Bot(command_prefix='!', intents=intents)
# Default settings

# Runtime storage
class MoodyBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = MySQLStorage()
        self.analyzer = ColorAnalyser()
        self.logger = logging.getLogger(__name__)

    async def setup_hook(self):
        """Initializes resources before login"""
        await self.db.initialize()
        await self.db.init_db()
        await self.bot.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, 
            name="for art submissions"
        ))

    @commands.Cog.listener()
    async def on_ready(self):
        """Called when connected to Discord"""
        self.logger.info(f'Logged in as {self.bot.user}')  # Fixed: self.bot.user

    @commands.Cog.listener()
    async def on_message(self, message):
        """Processes all messages"""
        await self.bot.process_commands(message)
        
        # Fixed: Use self.bot.command_prefix
        if (message.attachments 
            and not message.author.bot
            and not message.content.startswith(self.bot.command_prefix)):
            await self._process_non_command_image(message)
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
    async def submit_artwork(self, ctx, *, args: str):
        """Submit artwork: !submit Artist, [social], [title], [desc], [tags]"""
        if not ctx.message.attachments:
            await ctx.send("❌ Please attach an image file!")
            return

        try:
            lines = args.split('\n')
            data = {'name': '', 'social': '', 'title': 'Untitled', 'desc': '', 'tags': []}

            for line in lines:
                if line.lower().startswith('name:'):
                    data['name'] = line[5:].strip()
                elif line.lower().startswith('social:'):
                    data['social'] = line[7:].strip()
                elif line.lower().startswith('title:'):
                    data['title'] = line[6:].strip()
                elif line.lower().startswith('desc:'):
                    data['desc'] = line[5:].strip()
                elif line.lower().startswith('tags:'):
                    data['tags'] = [t.strip() for t in line[5:].split(',')]

        # Process image
            image_url = ctx.message.attachments[0].url

        # Get/create records
            artist = await self.db.get_or_create_artist(
            name=data['name'],
            social_media=data['social']  # Ensure parameter matches actual method
        )

            submitter = await self.db.get_or_create_submitter(
            discord_id=str(ctx.author.id),
            name=ctx.author.display_name
        )

        # Store artwork
            artwork_id = await self.db.create_artwork(
            submitter_id=submitter['id'],
            artist_id=artist['id'],
            image_url=image_url,
            title=data['title'],
            description=data['desc'],
            tags=data['tags']
        )

        # Analyze and store palette (same as before)
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        data_img = await resp.read()
                        with io.BytesIO(data_img) as img_data:
                            palette = await self.analyzer.extract_palettes(img_data)
                            for i, color in enumerate(palette[:5]):
                                await self.db.add_color_to_palette(
                                artwork_id=artwork_id,
                                hex_code=color['hex'],
                                dominance_rank=i+1,
                                coverage=color['percentage']
                            )

            await ctx.send(f"✅ Submitted: {data['title']} by {data['name']} (ID: {artwork_id})")

        except Exception as e:
            self.logger.error(f"Submission error: {e}", exc_info=True)
            await ctx.send("⚠️ Submission failed. Please use the correct format.")

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

async def main():
    try:
        # Verify environment first
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise ValueError("DISCORD_TOKEN environment variable missing")
        await bot.add_cog(MoodyBot(bot))
        await bot.start(token)
        
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