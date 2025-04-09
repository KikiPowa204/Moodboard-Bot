import aiomysql
import os
import discord
from pathlib import Path
from mysql.connector import connect, Error
from typing import Optional
import aiomysql
import re
from urllib.parse import urlparse
import logging
class MySQLStorage:
    def __init__(self):
        self.pool = None
    def _parse_public_url(self):
        """Extract connection details from MYSQL_PUBLIC_URL"""
        url = os.getenv('MYSQL_PUBLIC_URL')
        if not url:
            raise ValueError("Public Url not found in env")
        try:
            #parse the url
            parsed = urlparse(url)
            return {
                'host': parsed.hostname,
                'port': parsed.port or 3306,  # Default MySQL port
                'user': parsed.username,
                'password': parsed.password,
                'db': parsed.path[1:]  # Remove leading '/'
            }
        except Exception as e:
            raise ValueError(f'Failed to parse URL: {e}')
        
    async def initialise(self):
        "Initialise only once for this db at setup"
        
        await self._create_connection()
        print (f'pool autocommit status: {self.pool.autocommit[0].autocommit}')
    
    async def _create_connection(self):
        """create and return MYSQL connection"""
        try:
            config = self._parse_public_url

            self.pool = await aiomysql.create_pool(
                host = config['host'],
                port=config['port'],
                user=config['user'],
                password=config['password'],
                db=config['db'],
                minsize=5,
                maxsize=10,
                connect_timeout=10,
                autocommit=False
            )
            print (f"Connection to MYSQL at {config['host']}': {config['port']}")
        except Exception as e:
            print(f"❌ Connection failed. Verify:")
            print(f"- MYSQL_PUBLIC_URL is correct")
            print(f"- MySQL service is running (not paused)")
            print(f"- Error details: {e}")
            raise
    async def execute_query(self, query, args=None):
        """Generic query executor"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query,args or ())
                await conn.commit()
                return cursor
    
    async def init_db(self):
        """initialize Database Tables"""
        if not self.pool:
            await self._create_connection()
        
        