from colorthief import ColorThief
import discord
from io import BytesIO
import logging
import asyncio
from typing import Optional
import mysql.connector
from mysql.connector import Error    # Moody.py
import pathlib
from lib.database import mysql_storage
from lib.analyser import color_analyser
# In Moody.py
from discord.ext import commands
import math
import discord
import logging
import aiohttp
import io

class MoodyBot(commands.Bot):
    def __init__(self, command_prefix='!'):
        super().__init__(command_prefix)
        self.db = mysql_storage()
        self.analyzer = color_analyser()
        self.logger = logging.getLogger(__name__)

    async def setup_hook(self):
        """Initialize resources when bot starts"""
        await self.db.initialize()

    async def close(self):
        """Cleanup resources when bot stops"""
        await self.db.close()
        await self.analyzer.close()
        await super().close()

    async def process_submission(self, message):
        """Enhanced submission handler with progress updates"""
        try:
            if not message.attachments:
                return

            # Step 1: Initial processing message
            status_msg = await message.channel.send("🖌️ Starting artwork analysis...")
            
            # Step 2: Get artist info
            await status_msg.edit(content="🖌️ Verifying artist profile...")
            artist = await self.db.get_or_create_artist(
                discord_id=str(message.author.id),
                name=message.author.display_name
            )

            # Step 3: Download and analyze image
            await status_msg.edit(content="🖌️ Analyzing color palette...")
            image_url = message.attachments[0].url
            palette = await self.analyzer.extract_palettes(image_url)

            # Step 4: Store in database
            await status_msg.edit(content="🖌️ Saving to archive...")
            success = await self.db.full_submission_pipeline(
                artist_id=artist['id'],
                image_url=image_url,
                palette=palette,
                metadata={
                    'channel_id': message.channel.id,
                    'message_id': message.id,
                    'title': f"Artwork by {message.author.display_name}"
                }
            )

            # Step 5: Final response
            if success:
                await status_msg.edit(content=f"✅ Saved! Dominant colors: {', '.join(c['hex'] for c in palette[:3])}")
                await message.add_reaction('🎨')
            else:
                await status_msg.edit(content="❌ Failed to save artwork")

        except Exception as e:
            self.logger.error(f"Submission error: {e}", exc_info=True)
            await message.channel.send(f"⚠️ Error: {str(e)}")
            if 'status_msg' in locals():
                await status_msg.delete()

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