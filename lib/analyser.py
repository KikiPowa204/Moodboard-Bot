from colorthief import ColorThief
from io import BytesIO
import io
import aiohttp
import logging
from typing import List, Dict

class ColorAnalyser:
    def __init__(self):
        self.http = None  # Initialize as None
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.logger = logging.getLogger(__name__)

    async def ensure_session(self):
        """Lazy initialization of HTTP session"""
        if self.http is None or self.http.closed:
            self.http = aiohttp.ClientSession(timeout=self.timeout)

    async def extract_palettes(self, image_url: str, color_count: int = 5) -> List[Dict]:
        """Enhanced color extraction with better error handling"""
        await self.ensure_session()  # Ensure we have a session
        
        try:
            # Validate URL first
            if not image_url.startswith(('http://', 'https://')):
                raise ValueError("Invalid image URL format")

            async with self.http.get(image_url, timeout=self.timeout, 
                                  max_size=5 * 1024 * 1024) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}")
                
                image_data = await response.read()
                
                if len(image_data) == 0:
                    raise ValueError("Empty image file")

                with io.BytesIO(image_data) as buffer:
                    try:
                        color_thief = ColorThief(buffer)
                        palette = color_thief.get_palette(
                            color_count=color_count,
                            quality=10
                        )
                        
                        total = sum(sum(color) for color in palette) or 1
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
        if self.http and not self.http.closed:
            await self.http.close()
            self.http = None



# Remove the module-level instance - let the bot create it when needed
color_analyser = ColorAnalyser()  # DELETE THIS LINE