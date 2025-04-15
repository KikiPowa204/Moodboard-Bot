from colorthief import ColorThief
import discord
import io
from PIL import ImageDraw, Image
import logging
import re
import os
import asyncio
from typing import Optional
from mysql.connector import Error    # Moody.py
import pathlib
from lib.database import MySQLStorage
from lib.analyser import ColorAnalyser
# In Moody.py
from discord.ext import commands
import random
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
            artist = await self.db.get_or_create_artist(artist_name=metadata['name'], social_media_link=metadata['social'])

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
                print (colors)
                await self.db.store_palette(
                artwork_id=artwork,
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
            embed.set_footer(text=f'Artwork ID: {artwork}')
            await ctx.send(embed=embed)

            await ctx.send("✅ Artwork submitted successfully!")

        except Exception as e:
            self.logger.error(f"Submission error: {e}", exc_info=True)
            await ctx.send(f"⚠️ Submission failed: {str(e)}")
    
    @commands.command(name='trend')
    async def show_theme_trends(self, ctx, *, theme: str):
        """Show dominant color trends for a specific art theme"""
        try:
            # 1. Get top palettes for this theme from database
            theme_palettes = await self.db.get_theme_palettes(theme.lower())
        
            if not theme_palettes:
                return await ctx.send(f"❌ No data found for '{theme}' theme")
        
            # 2. Aggregate dominant colors across all artworks
            color_stats = {}
            for palette in theme_palettes:
                dominant_color = next((c for c in palette['colors'] if c['dominance_rank'] == 1), None)
                if dominant_color:
                    hex_code = dominant_color['hex_code']
                    color_stats[hex_code] = color_stats.get(hex_code, 0) + 1
        
            # 3. Get top 5 most frequent colors
            top_colors = sorted(color_stats.items(), key=lambda x: x[1], reverse=True)[:5]
            hex_colors = [color[0] for color in top_colors]
        
            # 4. Generate moodboard image
            moodboard = self.generate_moodboard(hex_colors)
        
            # 5. Create embed
            embed = discord.Embed(
                title=f"🎨 Color Trends for '{theme.title()}'",
                description=f"Based on {len(theme_palettes)} artworks",
                color=int(hex_colors[0].lstrip('#'), 16)
            )
        
            file = discord.File(moodboard, filename="moodboard.png")
            embed.set_image(url="attachment://moodboard.png")
        
            for i, (hex_code, count) in enumerate(top_colors, 1):
                percentage = (count / len(theme_palettes)) * 100
                embed.add_field(
                    name=f"#{i} {hex_code}",
                    value=f"Appears in {percentage:.1f}% of artworks",
                    inline=True
                )
        
            await ctx.send(file=file, embed=embed)
        
        except Exception as e:
            await ctx.send(f"❌ Error generating trends: {str(e)}")

    def generate_moodboard(self, colors: list, width=600, height=300) -> io.BytesIO:
        """Generate a stylish moodboard image"""
        img = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(img)
    
        # Create gradient blocks
        block_width = width // len(colors)
        for i, hex_color in enumerate(colors):
            x0 = i * block_width
            x1 = x0 + block_width
        
            # Base color
            rgb = tuple(int(hex_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
            draw.rectangle([x0, 0, x1, height], fill=rgb)
        
            # Add texture/noise for visual interest
            for _ in range(100):
                xy = (random.randint(x0, x1), random.randint(0, height))
                draw.point(xy, fill=self._adjust_brightness(rgb, random.uniform(0.9, 1.1)))
    
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer

    def _adjust_brightness(self, rgb, factor):
        """Helper for moodboard texture"""
        return tuple((min(255, max(0, int(c * factor))) for c in rgb))
    
    def generate_palette_image(self, colors: list, width=400, height=100) -> io.BytesIO:
        """
        Generate a color palette image
        :param colors: List of hex color codes (e.g., ["#FF5733", "#33FF57"])
        :return: BytesIO buffer containing PNG image
        """
        print (f'in generate_palette_image {colors}')
        try:
            # Create blank image
            img = Image.new('RGB', (width, height))
            draw = ImageDraw.Draw(img)
    
            # Calculate color block widths
            block_width = width // len(colors)
    
            # Draw each color
            for i, hex_color in enumerate(colors):
                x0 = i * block_width
                x1 = x0 + block_width
                rgb = tuple(int(hex_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
                draw.rectangle([x0, 0, x1, height], fill=rgb)
    
            # Save to bytes buffer
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            return buffer
        except Exception as e:
            raise e
    
    @commands.command(name='showpalette', aliases=['palette', 'colors'])
    async def show_palette(self, ctx):
        """Display color palette by replying to an artwork message"""
        try:
            # Check if it's a reply
            if not ctx.message.reference:
                return await ctx.send("❌ Please reply to an artwork message to show its palette")
        
            # Get the referenced message
            ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        
            # Extract artwork ID from embed (assuming your embeds include it)
            artwork_id = None
            for embed in ref_msg.embeds:
                if embed.footer and embed.footer.text:
                    # Try extracting ID from footer (e.g., "Artwork ID: 123")
                    match = re.search(r"Artwork ID: (\d+)", embed.footer.text)
                    if match:
                        artwork_id = int(match.group(1))
                        break
        
            if not artwork_id:
                return await ctx.send("❌ Couldn't find artwork ID in the replied message")
            print (f'in show_palette. Artwork_ID: {artwork_id}')
            # Get palette from database
            palette = await self.db.get_artwork_palette(artwork_id)
            print ('Processed get_artwork_palette')
            if not palette:
                return await ctx.send("❌ No palette found for this artwork!")
        
            # Generate and send palette
            try:
                hex_colors = [color['hex_code'] for color in palette]
                image_buffer = self.generate_palette_image(hex_colors)
            except Exception as e:
                raise
            embed = discord.Embed(
                title=f"🎨 Color Palette for Artwork #{artwork_id}",
                color=int(hex_colors[0].lstrip('#'), 16)
            )
        
            file = discord.File(image_buffer, filename="palette.png")
            embed.set_image(url="attachment://palette.png")
        
            for i, hex_code in enumerate(hex_colors, 1):
                embed.add_field(
                    name=f"Color {i}",
                    value=f"`{hex_code}`\nDominance: {palette[i-1]['coverage']}%",
                    inline=True
                )
        
            await ctx.send(file=file, embed=embed)
        
        except Exception as e:
            await ctx.send(f"❌ Error generating palette: {str(e)}")
    @commands.command(name='artist')
    async def show_artworks(self, ctx, artist_name: str, page: int = 1):
        """Display artworks with their tags"""
        try:
            per_page = 5
            offset = (page - 1) * per_page

            # Get artist
            artist = await self.db.get_or_create_artist(
                artist_name=artist_name,
                social_media_link=""
            )

            # Get artworks
            artworks = await self.db.get_artworks_by_artist(
                artist_id=artist['id'],
                limit=per_page,
                offset=offset
            )

            if not artworks:
                return await ctx.send(f"No artworks found for {artist_name}")

            for art in artworks:
                # Fetch tags for this artwork
                tags = await self.db.get_artwork_tags(art['id'])
            
                # Create embed
                embed = discord.Embed(
                    title=art.get('title', 'Untitled'),
                    description=art.get('description', 'No description')[:100] + '...',
                    color=0x6E85B2
                )
                embed.set_image(url=art['image_url'])
            
                # Add tags if they exist
                if tags:
                    embed.add_field(
                        name="Tags",
                        value=", ".join(tags),
                        inline=False
                    )
            
                embed.set_footer(text=f'Artwork ID: {art["id"]} | Page {page}')
                await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"Error displaying artworks: {str(e)}")
            self.logger.error(f"Artworks error: {e}", exc_info=True)

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