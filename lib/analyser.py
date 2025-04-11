from colorthief import ColorThief
from io import BytesIO
import io
import aiomysql
import aiohttp
import logging
import asyncio
from urllib.parse import urlparse
from typing import List, Optional, Dict

class ColorAnalyser:
    def __init__(self):
        self.http = aiohttp.ClientSession()
        self.timeout = aiohttp.ClientTimeout(total=30)  # Increased timeout
        self.logger = logging.getLogger(__name__)

    async def extract_palettes(self, image_url: str, color_count: int = 5) -> List[Dict]:
        """Enhanced color extraction with better error handling"""
        try:
            # Validate URL first
            if not image_url.startswith(('http://', 'https://')):
                raise ValueError("Invalid image URL format")

            # Download with size limit (5MB)
            async with self.http.get(image_url, timeout=self.timeout, 
                                  max_size=5 * 1024 * 1024) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}")
                
                image_data = await response.read()
                
                # Validate image
                if len(image_data) == 0:
                    raise ValueError("Empty image file")

                # Analyze colors
                with io.BytesIO(image_data) as buffer:
                    try:
                        color_thief = ColorThief(buffer)
                        palette = color_thief.get_palette(
                            color_count=color_count,
                            quality=10  # Faster processing
                        )
                        
                        # Normalize dominance percentages
                        total = sum(sum(color) for color in palette) or 1  # Avoid division by zero
                        return [
                            {
                                "hex": self._rgb_to_hex(color),
                                "percentage": round(sum(color)/total * 100, 1)
                            }
                            for color in palette
                        ]
                        
                    except Exception as e:
                        raise ValueError(f"Color analysis failed: {str(e)}")

        except aiohttp.ClientError as e:
            self.logger.error(f"Network error: {e}")
            raise ConnectionError("Failed to download image")
        except Exception as e:
            self.logger.error(f"Analysis error: {e}")
            raise

    @staticmethod
    def _rgb_to_hex(rgb: tuple) -> str:
        """Convert RGB to hex with validation"""
        if len(rgb) != 3 or not all(0 <= c <= 255 for c in rgb):
            raise ValueError("Invalid RGB values")
        return "#{:02X}{:02X}{:02X}".format(*rgb)

    async def close(self):
        """Proper resource cleanup"""
        if not self.http.closed:
            await self.http.close()
color_analyser = ColorAnalyser