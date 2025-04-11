import aiomysql
import os
import logging
from urllib.parse import urlparse
from typing import Optional, Dict, List, Union
from mysql.connector import connect, Error  # Import MySQL connector
import asyncio

class MySQLStorage:
    def __init__(self):
        self.pool = None
        self.logger = logging.getLogger(__name__)

    def _parse_public_url(self) -> Dict[str, Union[str, int]]:
        """Extract connection details from MYSQL_PUBLIC_URL"""
        url = os.getenv('MYSQL_PUBLIC_URL')
        if not url:
            raise ValueError("MYSQL_PUBLIC_URL not found in environment variables")
        
        try:
            parsed = urlparse(url)
            if not all([parsed.scheme, parsed.hostname, parsed.username]):
                raise ValueError("Invalid URL format")
            
            return {
                'host': parsed.hostname,
                'port': parsed.port or 3306,
                'user': parsed.username,
                'password': parsed.password,
                'db': parsed.path[1:]  # Remove leading '/'
            }
        except Exception as e:
            self.logger.error(f"URL parsing failed: {e}")
            raise ValueError(f'Invalid MYSQL_PUBLIC_URL format: {e}')

    async def initialize(self) -> None:
        """Initialize connection pool with proper error handling"""
        if self.pool is not None:
            self.logger.warning("Connection pool already exists")
            return
            
        try:
            await self._create_connection()
            if not await self.validate_connection():
                raise ConnectionError("Failed to validate initial connection")
                
            # Initialize tables separately to avoid mixing concerns
            if not await self.init_db():
                self.logger.warning("Table initialization completed with warnings")
                
            self.logger.info("Database pool initialized successfully")
            
        except Exception as e:
            self.logger.critical(f"Database initialization failed: {e}")
            await self.close()  # Clean up if initialization fails
            raise

    async def _create_connection(self) -> None:
        """Create MySQL connection pool with retry logic"""
        config = self._parse_public_url()
        
        for attempt in range(3):  # 3 retries
            try:
                if self.pool:
                    return True
                self.logger.info(f"Connecting to MySQL (attempt {attempt+1}/{3})...")

                
                self.pool = await aiomysql.create_pool(
                    host=config['host'],
                    port=config['port'],
                    user=config['user'],
                    password=config['password'],
                    db=config['db'],
                    minsize=1,  # Lower minimum for development
                    maxsize=5,
                    connect_timeout=30,
                    autocommit=False,
                    cursorclass=aiomysql.DictCursor
                )
                self.logger.info(f"Connected to MySQL at {config['host']}:{config['port']}")
                if await self._verify_connection():
                    self.logger.info("Database connection established")
                    return True    
            except Exception as e:
                if attempt == 2:  # Last attempt
                    raise ConnectionError(f"MySQL connection failed after 3 attempts: {e}")
                await asyncio.sleep(1)  # Wait before retrying
                continue

    async def execute_query(self, query: str, args: Optional[tuple] = None) -> aiomysql.Cursor:
        """Execute a single query with parameters"""
        if not self.pool:
            raise RuntimeError("Database connection not initialized")
            
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute(query, args or ())
                    await conn.commit()
                    return cursor
                except Exception as e:
                    await conn.rollback()
                    self.logger.error(f"Query failed: {query[:100]}... Error: {e}")
                    raise

    async def init_db(self) -> bool:
        """Initialize database tables with proper error handling"""
        if not self.pool:
            await self._create_connection()

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    # Suppress "table exists" warnings
                    await cursor.execute("SET sql_notes = 0;")
                    await conn.begin()
                    
                    # Table creation queries
                    tables = [
                        '''CREATE TABLE IF NOT EXISTS artists (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            discord_id VARCHAR(255) UNIQUE NOT NULL,
                            name VARCHAR(255) NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
                        
                        '''CREATE TABLE IF NOT EXISTS artworks (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            artist_id INT NOT NULL,
                            image_url TEXT NOT NULL,
                            title VARCHAR(255),
                            description TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (artist_id) REFERENCES artists(id),
                            INDEX idx_artist (artist_id)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'''
                    ]
                    
                    for table_query in tables:
                        await cursor.execute(table_query)
                    
                    await cursor.execute("SET sql_notes = 1;")
                    await conn.commit()
                    return True
                    
                except Exception as e:
                    await conn.rollback()
                    self.logger.error(f"Table creation failed: {e}")
                    return False
                finally:
                    await cursor.execute("SET sql_notes = 1;")  # Ensure this is always reset

    async def validate_connection(self) -> bool:
        """Test if the connection works"""
        if not self.pool:
            return False
            
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    result = await cursor.fetchone()
                    return result[0] == 1
        except Exception as e:
            self.logger.error(f"Connection validation failed: {e}")
            return False
    async def store_artist(self, discord_id: str, name: str) -> int:
        """Store a new artist and return their ID"""
        query = '''
            INSERT INTO artists (discord_id, name)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE name=VALUES(name)
        '''
        cursor = await self.execute_query(query, (discord_id, name))
        return cursor.lastrowid

    async def store_artwork(self, artist_id: int, image_url: str, 
                          title: Optional[str] = None, 
                          description: Optional[str] = None) -> int:
        """Store artwork and return its ID"""
        query = '''
            INSERT INTO artworks (artist_id, image_url, title, description)
            VALUES (%s, %s, %s, %s)
        '''
        cursor = await self.execute_query(query, (artist_id, image_url, title, description))
        return cursor.lastrowid

    async def store_palette(self, artwork_id: int, colors: List[Dict[str, Union[str, float]]]) -> None:
        """Store color palette for an artwork"""
        query = '''
            INSERT INTO color_palettes (artwork_id, hex_code, dominance_rank, coverage)
            VALUES (%s, %s, %s, %s)
        '''
        # Prepare batch insert
        palette_data = [
            (artwork_id, color['hex'], idx + 1, color.get('percentage'))
            for idx, color in enumerate(colors)
        ]
        
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.executemany(query, palette_data)
                await conn.commit()

    async def close(self) -> None:
        """Cleanup resources when stopping"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None
            self.logger.info("Database connections closed")
    async def get_or_create_artist(self, discord_id: str, name: str) -> dict:
        """Get or create artist record"""
        artist_id = await self.store_artist(discord_id, name)
        return {'id': artist_id, 'discord_id': discord_id, 'name': name}

    async def full_submission_pipeline(self, artist_id: int, image_url: str, palette: List[dict], metadata: dict) -> bool:
        """Complete artwork storage workflow"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Store artwork
                    artwork_id = await self.store_artwork(
                    artist_id=artist_id,
                    image_url=image_url,
                    title=metadata.get('title'),
                    description=metadata.get('description')
                )
                
                # Store palette
                    await self.store_palette(artwork_id, palette)
                
                    return True
        except Exception as e:
            self.logger.error(f"Submission pipeline failed: {e}")
            return False
    