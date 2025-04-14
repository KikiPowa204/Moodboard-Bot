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
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Called when connected to Discord"""
        await self.db.initialize()
        await self.db.init_db()
        await self.bot.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, 
            name="for art submissions"
        ))
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
        """Submit artwork: !submit Name:..., Social:..., Title:..., Desc:..., Tags:..."""
        if not ctx.message.attachments:
            await ctx.send("❌ Please attach an image file!")
            return

        try:
            # Parse metadata
            lines = [line.strip() for line in ctx.message.content.split('\n') if line.strip()]
            metadata = {
            'name': None,
            'social': None,  # Keep original key for user input
            'title': None,
            'desc': None,
            'tags': None
        }
        
            for line in lines[1:]:  # Skip first line (!submit)
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if key == 'name':
                        metadata['name'] = value
                    elif key == 'social':
                        metadata['social'] = value  # Store as 'social'
                    elif key == 'title':
                        metadata['title'] = value
                    elif key == 'desc':
                        metadata['desc'] = value
                    elif key == 'tags':
                        metadata['tags'] = [t.strip() for t in value.split(',')] if value else []

            image_url = ctx.message.attachments[0].url

        # 1. First create submitter
            submitter = await self.db.get_or_create_submitter(
            submitter_id=str(ctx.author.id),
            name=ctx.author.display_name
        )

        # 2. Then create artist with proper key names
            artist_data = {
            'name': metadata['name'],
            'social_media_link': metadata['social'] or ""  # Map to correct key
        }
            artist = await self.db.get_or_create_artist(**artist_data)

        # 3. Then create artwork
            artwork = await self.db.create_artwork(
            submitter_id=submitter['id'],
            artist_id=artist['id'],
            image_url=image_url,
            title=metadata['title'],
            description=metadata['desc'],
            tags=metadata['tags']
        )

        # 4. Extract and store colors
            try:
                colors = await self.analyzer.extract_palettes(image_url)
                await self.db.store_palette(
                artwork_id=artwork['id'],
                colors=colors
            )
            except Exception as e:
                self.logger.error(f"Color analysis failed: {e}")
                await ctx.send("⚠️ Color analysis failed, but artwork was submitted successfully.")

        # Create embed
            embed = discord.Embed(
            title=f"🎨 {metadata['title']}",
            description=f"By {metadata['name']}",
            color=0x6E85B2
        )
            embed.add_field(name="Tags", value=", ".join(metadata['tags']) if metadata['tags'] else "None")
            embed.set_image(url=image_url)
            await ctx.send(embed=embed)

            await ctx.send("✅ Artwork submitted successfully!")

        except Exception as e:
            self.logger.error(f"Submission error: {e}", exc_info=True)
            await ctx.send(f"⚠️ Submission failed: {str(e)}")

        

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