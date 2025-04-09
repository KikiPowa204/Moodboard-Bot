from colorthief import ColorThief
import discord
from io import BytesIO
import logging
import asyncio
from typing import Optional
from discord.ext.commands import Bot
import mysql.connector
from mysql.connector import Error    # Moody.py
import pathlib
from lib.database import ArtDatabase
from lib.analyzer import ColorAnalyser

class MoodyBot(commands.Bot):
    def __init__(self):
        self.db = ArtDatabase()
        self.analyzer = ColorAnalyzer()

    async def on_message(self, message):
        if message.attachments:
            await self.process_submission(message)

    async def process_submission(self, message):
        """Handles user interaction only"""
        await message.channel.send("Processing your artwork...")
        success = await self.db.full_submission_pipeline(
            message=message,
            image_url=message.attachments[0].url
        )
        if success:
            await message.add_reaction('✅')