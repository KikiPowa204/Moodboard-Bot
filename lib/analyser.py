from colorthief import ColorThief
from io import BytesIO
import io
import aiomysql
import aiohttp
import logging
import asyncio
from urllib.parse import urlparse
from typing import List, Optional

class ColorAnalyser:
    """Handles color palette extraction from images"""
    def __init__(self):
        self.http = aiohttp.ClientSession()
        self.timeout = aiohttp.ClientTimeout(total=10)

    async def _download_image(self, image_url: str) -> bytes:
        """Downloads image with timeout and error handling"""
        try:
            async with self.http.get(image_url, timeout=self.timeout) as response:
                if response.status == 200:
                    return await response.read()
                raise ValueError(f"HTTP {response.status}")
        except Exception as e:
            logging.error(f"Image download failed: {str(e)}")
            raise

    async def extract_palettes(self, image_url: str, color_count: int = 3) -> List[dict]:
        """
        Extracts dominant colors from an image
        Args:
            image_url: URL of the image to analyze
            color_count: Number of colors to extract (default: 3)
        Returns:
            List of color dictionaries with hex codes and dominance percentages
            Example: [{"hex": "#4A2E19", "percentage": 45.2}, ...]
        """
        try:
            # Download image
            image_data = await self._download_image(image_url)
            
            # Analyze colors
            with io.BytesIO(image_data) as buffer:
                color_thief = ColorThief(buffer)
                palette = color_thief.get_palette(color_count=color_count)
                
                # Calculate relative dominance (simplified)
                total = sum(sum(color) for color in palette)
                return [
                    {
                        "hex": self._rgb_to_hex(color),
                        "percentage": round(sum(color)/total * 100, 1) if total > 0 else 0
                    }
                    for color in palette
                ]
                
        except Exception as e:
            logging.error(f"Color analysis failed: {str(e)}")
            raise

    @staticmethod
    def _rgb_to_hex(rgb_tuple: tuple) -> str:
        """Converts RGB tuple to hex string"""
        return "#{:02x}{:02x}{:02x}".format(*rgb_tuple).upper()

    async def close(self):
        """Cleanup resources"""
        await self.http.close()