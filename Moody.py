from colorthief import ColorThief
import discord
import io
from PIL import ImageDraw, Image
import logging
import re
import os
import math
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
import traceback
from colormath.color_objects import LabColor, sRGBColor
from colormath.color_conversions import convert_color
from _delta_e import delta_e_cie2000
import numpy as np
import matplotlib.pyplot as plt
from collections import Counter
from sklearn.cluster import KMeans

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
        self.pending_submissions = {}
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
        """Processes non-command messages with images"""
        if message.author.bot or message.content.startswith(self.bot.command_prefix):
            return
        
        if message.attachments:
            # Check for duplicate processing
            if message.id in self.pending_submissions:
                return
                
            self.pending_submissions[message.id] = True
            try:
                await self._process_non_command_image(message)
            finally:
                self.pending_submissions.pop(message.id, None)
    async def _process_non_command_image(self, message):
        """Handle image submissions that aren't commands"""
        try:
            # Your existing image processing logic here
            pass
        except Exception as e:
            self.logger.error(f"Image processing failed: {e}")
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
        """Modern color trend analysis with fixed numpy compatibility"""
        try:
            # 1. Get artworks with theme tag
            theme_artworks = await self.db.get_artworks_by_tag(theme.lower())
            if not theme_artworks:
                return await ctx.send(f"❌ No artworks found with '{theme}' tag")

            # 2. Process colors with error handling
            artwork_color_data = []
            for artwork in theme_artworks:
                palette = await self.db.get_artwork_palette(artwork['id'])
                if not palette:
                    continue
                
                lab_colors = []
                for color in palette:
                    try:
                        rgb = sRGBColor.new_from_rgb_hex(color['hex_code'])
                        lab = convert_color(rgb, LabColor)
                        lab_colors.append({
                            'lab': lab,
                            'hex': color['hex_code'],
                            'dominance': color['dominance_rank']
                        })
                    except Exception as e:
                        self.logger.warning(f"Color conversion failed: {e}")
                        continue
                
                if lab_colors:
                    artwork_color_data.append({
                        'artwork': artwork,
                        'colors': lab_colors
                    })

            if not artwork_color_data:
                return await ctx.send(f"❌ No valid color data for '{theme}'")

            # 3. Find reference color (most dominant)
            reference_color = max(
                (c for ad in artwork_color_data for c in ad['colors']),
                key=lambda x: x['dominance']
            )['lab']

            # 4. Score artworks by color similarity
            scored_artworks = []
            for artwork in artwork_color_data:
                score = 0
                best_matches = []
                
                for color in artwork['colors']:
                    try:
                        # FIXED: Proper float conversion
                        lab1 = (reference_color.lab_l, reference_color.lab_a, reference_color.lab_b)
                        lab2 = (color['lab'].lab_l, color['lab'].lab_a, color['lab'].lab_b)
                        delta_e = delta_e_cie2000(lab1, lab2)
                        similarity = max(0, 100 - delta_e)
                        score += similarity * (1/color['dominance'])
                        best_matches.append({
                            'hex': color['hex'],
                            'delta_e': delta_e,
                            'similarity': similarity
                        })
                    except Exception as e:
                        self.logger.warning(f"Delta-E calc failed: {e}")
                        continue
                
                if best_matches:
                    scored_artworks.append({
                        'artwork': artwork['artwork'],
                        'score': score,
                        'best_matches': sorted(best_matches, key=lambda x: x['delta_e'])[:3]
                    })

            # 5. Generate and send results
            if not scored_artworks:
                return await ctx.send("❌ No valid color matches found")
                
            top_artworks = sorted(scored_artworks, key=lambda x: x['score'], reverse=True)[:5]
            await self._send_trend_results(ctx, theme, reference_color, top_artworks)

        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Trend error: {traceback.format_exc()}")

    async def _send_trend_results(self, ctx, theme, reference_color, artworks):
        """Send formatted trend results"""
        # Generate visualization
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Convert reference color for display
        ref_rgb = convert_color(reference_color, sRGBColor).get_rgb_hex()
        
        # Plot each artwork's best matches
        for i, artwork in enumerate(artworks):
            for match in artwork['best_matches']:
                rgb = tuple(int(match['hex'].lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
                rgb = tuple(c/255 for c in rgb)
                size = max(10, 100 - match['delta_e'])
                
                ax.scatter(
                    match['delta_e'],
                    artwork['score'],
                    c=[rgb],
                    s=size,
                    alpha=0.7,
                    label=f"{artwork['artwork']['title']}" if i == 0 else ""
                )
        
        ax.set_xlabel('Color Difference (ΔE) → More Similar')
        ax.set_ylabel('Match Score')
        ax.set_title(f"Color Trends for '{theme}'")
        ax.legend()
        
        # Save and send
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', bbox_inches='tight', dpi=100)
        plt.close()
        buffer.seek(0)
        
        # Create embed
        embed = discord.Embed(
            title=f"🎨 Color Trends: '{theme}'",
            color=int(ref_rgb.lstrip('#'), 16)
        )
        embed.set_image(url="attachment://trend.png")
        
        # Add top match info
        for i, artwork in enumerate(artworks[:3], 1):
            best = artwork['best_matches'][0]
            embed.add_field(
                name=f"#{i} {artwork['artwork']['title']}",
                value=f"Closest: `{best['hex']}` (ΔE: {best['delta_e']:.1f})",
                inline=False
            )
        
        await ctx.send(file=discord.File(buffer, "trend.png"), embed=embed)
    @commands.command(name='paletteoverlap')
    async def show_palette_overlap(self, ctx, *, theme: str):
        """Show artworks with most consistent color palette overlaps"""
        try:
            # 1. Get all artworks with the theme tag
            theme_artworks = await self.db.get_artworks_by_tag(theme.lower())
            if not theme_artworks:
                return await ctx.send(f"❌ No artworks found with '{theme}' tag")

            # 2. Extract and cluster color palettes
            color_clusters = await self._cluster_artwork_colors(theme_artworks)
            
            if not color_clusters:
                return await ctx.send(f"❌ No consistent color patterns found for '{theme}'")

            # 3. Find artworks with most cluster matches
            matched_artworks = []
            for artwork in theme_artworks:
                palette = await self.db.get_artwork_palette(artwork['id'])
                if not palette:
                    continue
                
                match_score = 0
                for color in palette:
                    for cluster in color_clusters:
                        hex_code = color['hex_code']
                        if self._color_in_cluster(hex_code, cluster):
                            match_score += 1
                            break
                
                if match_score > 0:
                    matched_artworks.append({
                        'artwork': artwork,
                        'score': match_score,
                        'matched_colors': [c['hex_code'] for c in palette 
                                        if any(self._color_in_cluster(c['hex_code'], cluster) 
                                        for cluster in color_clusters)]
                    })

            if not matched_artworks:
                return await ctx.send("❌ No artworks matched the color clusters")

            # 4. Sort by most matches and get top 5
            top_artworks = sorted(matched_artworks, key=lambda x: x['score'], reverse=True)[:5]
            
            # 5. Generate visual comparison
            comparison_image = await self._generate_overlap_comparison(top_artworks, color_clusters)
            file = discord.File(comparison_image, filename="palette_overlap.png")

            # 6. Create embed
            embed = discord.Embed(
                title=f"🎨 Consistent Color Overlaps in '{theme}'",
                description=f"Top {len(top_artworks)} artworks sharing color patterns",
                color=0x6E85B2
            )
            
            # Add cluster info
            for i, cluster in enumerate(color_clusters[:3], 1):
                embed.add_field(
                    name=f"Color Group #{i}",
                    value="\n".join(cluster['representative_colors'][:3]),
                    inline=True
                )

            embed.set_image(url="attachment://palette_overlap.png")
            await ctx.send(file=file, embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            self.logger.error(f"Overlap error: {traceback.format_exc()}")

    async def _cluster_artwork_colors(self, artworks, n_clusters=5):
        """Cluster colors from all artworks to find common patterns"""
        
        # 1. Collect all dominant colors
        all_colors = []
        for artwork in artworks:
            palette = await self.db.get_artwork_palette(artwork['id'])
            if palette:
                # Get top 3 dominant colors per artwork
                dominant = sorted(palette, key=lambda x: x['dominance_rank'])[:3]
                all_colors.extend([color['hex_code'] for color in dominant])
        
        if len(all_colors) < n_clusters:
            return []

        # 2. Convert hex colors to LAB space for clustering
        lab_colors = np.array([self._hex_to_lab(hex_color) for hex_color in all_colors])
        
        # 3. Perform k-means clustering
        kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        clusters = kmeans.fit_predict(lab_colors)
        
        # 4. Build cluster info
        color_clusters = []
        for i in range(n_clusters):
            cluster_colors = [all_colors[j] for j in range(len(all_colors)) if clusters[j] == i]
            if cluster_colors:
                # Get most frequent colors in cluster
                from collections import Counter
                common_colors = Counter(cluster_colors).most_common(5)
                
                color_clusters.append({
                    'center': kmeans.cluster_centers_[i].tolist(),
                    'representative_colors': [color[0] for color in common_colors],
                    'size': len(cluster_colors)
                })
        
        # Sort by cluster size (most common patterns first)
        return sorted(color_clusters, key=lambda x: x['size'], reverse=True)

    def _color_in_cluster(self, hex_color, cluster, threshold=15.0):
        """Check if a color belongs to a cluster within threshold ΔE"""
        color_lab = self._hex_to_lab(hex_color)
        cluster_center = cluster['center']
        delta_e = delta_e_cie2000(color_lab, cluster_center)
        return delta_e < threshold

    def _hex_to_lab(self, hex_color, reference_color):
        """Convert hex color to LAB and calculate Delta-E with reference color"""
        try:
            # Convert hex color to RGB
            rgb = tuple(int(hex_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
            
            # Convert RGB to LAB
            color_rgb = sRGBColor.new_from_rgb_triplet(*rgb)
            color_lab = convert_color(color_rgb, LabColor)

            # Get the LAB values for reference color (dominant color)
            lab1 = (reference_color.lab_l, reference_color.lab_a, reference_color.lab_b)
            lab2 = (color_lab.lab_l, color_lab.lab_a, color_lab.lab_b)
            
            # Calculate the Delta-E between the reference color and the target color
            delta_e = delta_e_cie2000(lab1, lab2)

            return delta_e
        except Exception as e:
            self.logger.warning(f"Color conversion or Delta-E calculation failed: {e}")
            return None


    async def _generate_overlap_comparison(self, artworks, clusters):
        """Generate visual comparison of palette overlaps"""
        from matplotlib import pyplot as plt
        
        # Create figure
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # Plot cluster centers
        for i, cluster in enumerate(clusters[:5]):
            for j, color in enumerate(cluster['representative_colors'][:3]):
                ax.scatter(
                    i, j,
                    color=color,
                    s=300,
                    edgecolors='white'
                )
        
        # Plot artwork matches
        for aw_idx, artwork in enumerate(artworks[:5]):
            # Get artwork image thumbnail
            img = await self._get_image_thumbnail(artwork['artwork']['image_url'])
            
            # Plot image
            ax.imshow(
                img,
                extent=(aw_idx-0.4, aw_idx+0.4, -2, -1),
                aspect='auto',
                zorder=0
            )
            
            # Plot matched colors
            for color in artwork['matched_colors'][:5]:
                closest_cluster = next(
                    (i for i, cluster in enumerate(clusters) 
                    if self._color_in_cluster(color, cluster)),
                    -1
                )
                if closest_cluster >= 0:
                    ax.plot(
                        [aw_idx, closest_cluster],
                        [-0.5, 0],
                        color=color,
                        linewidth=2,
                        alpha=0.7
                    )
        
        ax.set_xlim(-1, max(5, len(artworks)))
        ax.set_ylim(-2.5, 2.5)
        ax.axis('off')
        ax.set_title('Color Palette Overlap Analysis', pad=20)
        
        # Save to buffer
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', bbox_inches='tight', dpi=120)
        plt.close()
        buffer.seek(0)
        return buffer

    async def _get_image_thumbnail(self, url, size=(200, 200)):
        """Download and resize image for visualization"""
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                img_data = await response.read()
        
        with Image.open(io.BytesIO(img_data)) as img:
            img.thumbnail(size)
            return img
    async def _generate_color_relationship_moodboard(self, artworks):
        """Generate moodboard showing color relationships"""
        # Create color relationship visualization
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Plot reference color and matches
        for artwork in artworks:
            for match in artwork['best_matches']:
                color = match['hex']
                delta_e = match['delta_e']
                
                # Convert to RGB for display
                rgb = tuple(int(color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
                rgb = tuple(c/255 for c in rgb)
                
                # Plot with size based on similarity
                size = max(1, 100 - delta_e) * 10
                ax.scatter(
                    delta_e, 
                    artwork['score'], 
                    c=[rgb],
                    s=size,
                    alpha=0.7
                )
        
        ax.set_xlabel('Color Difference (ΔE)')
        ax.set_ylabel('Match Score')
        ax.set_title('Color Relationship Analysis')
        
        # Save to buffer
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', bbox_inches='tight')
        plt.close()
        buffer.seek(0)
        return buffer
            
    def generate_moodboard(self, colors: list, width=600, height=300) -> io.BytesIO:
        """Generate a stylish moodboard image"""
        img = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(img)
        print ("in generate_moodboard")
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