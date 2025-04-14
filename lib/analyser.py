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
    async def extract_palettes(self, image_url: str):
        await self.ensure_session()
        try:
            async with self.http.get(image_url, timeout=self.timeout) as response:
                response.raise_for_status()
                image_data = await response.read()
            
            # Add manual size check
                if len(image_data) > 5 * 1024 * 1024:  # 5MB
                    raise ValueError("Image too large")
            
                with BytesIO(image_data) as buffer:
                    color_thief = ColorThief(buffer)
                    palette = color_thief.get_palette(color_count=5, quality=10)
                        
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


