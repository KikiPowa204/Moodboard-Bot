import aiomysql
import os
import logging
from urllib.parse import urlparse
from typing import Any, Optional, Dict, List, Union
from mysql.connector import connect, Error  # Import MySQL connector
import asyncio
import os
import aiomysql
import logging
import asyncio
from urllib.parse import urlparse
from typing import Optional, Dict, Union

class MySQLStorage:
    def __init__(self):
        self.pool = None
        self.logger = logging.getLogger(__name__)
        self.connection_timeout = 30
        self.max_retries = 3
        self.retry_delay = 2

    def _parse_db_config(self) -> Dict[str, Union[str, int]]:
        """Parse and validate database configuration from environment"""
        url = os.getenv('MYSQL_PUBLIC_URL')
        if not url:
            raise ValueError("MYSQL_PUBLIC_URL environment variable not set")

        try:
            parsed = urlparse(url)
            return {
                'host': parsed.hostname,
                'port': parsed.port or 3306,
                'user': parsed.username,
                'password': parsed.password,
                'db': parsed.path.lstrip('/')
            }
        except Exception as e:
            self.logger.error(f"Failed to parse database URL: {e}")
            raise ValueError("Invalid database URL format") from e

    async def initialize(self) -> bool:
        """Initialize connection pool with retry logic"""
        for attempt in range(self.max_retries):
            try:
                if self.pool:
                    return True

                config = self._parse_db_config()
                self.logger.info(f"Connection attempt {attempt + 1}/{self.max_retries} to {config['host']}")

                self.pool = await aiomysql.create_pool(
                    host=config['host'],
                    port=config['port'],
                    user=config['user'],
                    password=config['password'],
                    db=config['db'],
                    minsize=1,
                    maxsize=5,
                    connect_timeout=self.connection_timeout,
                    autocommit=False,
                    cursorclass=aiomysql.DictCursor
                )

                if await self._verify_connection():
                    self.logger.info("✅ Database connection established")
                    return True

            except aiomysql.OperationalError as e:
                self.logger.warning(f"Connection error (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    raise ConnectionError(f"Failed to connect after {self.max_retries} attempts: {e}")
                await asyncio.sleep(self.retry_delay)
            except Exception as e:
                self.logger.error(f"Unexpected error during initialization: {e}")
                raise

        return False

    async def _verify_connection(self) -> bool:
        """Thoroughly verify the database connection"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Test basic query
                    await cursor.execute("SELECT 1 AS test_value")
                    result = await cursor.fetchone()
                    if result['test_value'] != 1:
                        raise ValueError("Connection test failed")
                    
                    # Verify database access
                    await cursor.execute("SELECT DATABASE() AS db_name")
                    db_info = await cursor.fetchone()
                    self.logger.debug(f"Connected to database: {db_info['db_name']}")
                    return True
        except Exception as e:
            self.logger.error(f"Connection verification failed: {e}")
            await self.close()
            return False

    async def init_db(self) -> bool:
        """Initialize database tables with proper relationships"""
        if not self.pool:
            await self._create_connection()

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute("SET sql_notes = 0;")
                    await conn.begin()
                    
                    # Table creation queries
                    tables = [
                        '''CREATE TABLE IF NOT EXISTS submitters (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            submitter_id VARCHAR(255) UNIQUE NOT NULL,
                            name VARCHAR(255) NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
                        
                        '''CREATE TABLE IF NOT EXISTS artists (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            artist_name VARCHAR(255) NOT NULL,
                            social_media_link TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_artist_name (artist_name)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
                        
                        '''CREATE TABLE IF NOT EXISTS artworks (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            submitter_id INT NOT NULL,
                            artist_id INT NOT NULL,
                            image_url TEXT NOT NULL,
                            title VARCHAR(255),
                            description TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (submitter_id) REFERENCES submitters(id),
                            FOREIGN KEY (artist_id) REFERENCES artists(id),
                            INDEX idx_artist (artist_id),
                            INDEX idx_submitter (submitter_id)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
                    
                        '''CREATE TABLE IF NOT EXISTS color_palettes (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            artwork_id INT NOT NULL,
                            hex_code VARCHAR(7) NOT NULL,
                            dominance_rank TINYINT NOT NULL,
                            coverage DECIMAL(5,2),
                            FOREIGN KEY (artwork_id) REFERENCES artworks(id),
                            CONSTRAINT valid_hex CHECK (hex_code REGEXP '^#[0-9A-F]{6}$'),
                            INDEX idx_artwork (artwork_id),
                            INDEX idx_color (hex_code)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''',
                        
                        '''CREATE TABLE IF NOT EXISTS artwork_tags (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            artwork_id INT NOT NULL,
                            tag VARCHAR(50) NOT NULL,
                            FOREIGN KEY (artwork_id) REFERENCES artworks(id),
                            INDEX idx_tag (tag),
                            UNIQUE KEY unique_artwork_tag (artwork_id, tag)
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
                    await cursor.execute("SET sql_notes = 1;")

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

    async def get_or_create_submitter(self, submitter_id: str, name: str):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Try to get existing submitter
                await cursor.execute(
                    "SELECT * FROM submitters WHERE submitter_id = %s",
                    (submitter_id,)
                )
                submitter = await cursor.fetchone()
                
                if not submitter:
                    # Create new submitter
                    await cursor.execute(
                        """INSERT INTO submitters 
                        (submitter_id, name) 
                        VALUES (%s, %s)""",
                        (submitter_id, name)
                    )
                    await conn.commit()
                    return {'id': cursor.lastrowid, 'submitter_id': submitter_id, 'name': name}
                
                return submitter

    async def get_or_create_artist(self, artist_name: str, social_media_link:str):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Get existing artist
                await cursor.execute(
                    "SELECT * FROM artists WHERE artist_name = %s",
                (artist_name,)
            )
                artist = await cursor.fetchone()
            
                if not artist:
                # Create new artist with whatever fields were provided
                    await cursor.execute(
                    """INSERT INTO artists (artist_name, social_media_link)
                    VALUES (%s, %s)""",
                    (artist_name, social_media_link)
                )
                    await conn.commit()
                    return {
                    'id': cursor.lastrowid,
                    'name': artist_name,
                    'social_media_link': social_media_link
                }
            
            # Update social media if provided and different
                if social_media_link and artist.get('social_media_link') != social_media_link:
                    await cursor.execute(
                    "UPDATE artists SET social_media_link = %s WHERE id = %s",
                    (social_media_link, artist['id'])
                )
                    await conn.commit()
                    artist['social_media_link'] = social_media_link
            
                return artist
    async def get_artworks_by_artist(self, artist_id: int, limit: int, offset: int):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                """SELECT * FROM artworks 
                WHERE artist_id = %s 
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s""",
                (artist_id, limit, offset)
            )
                return await cursor.fetchall()
    async def create_artwork(self, submitter_id: int, artist_id: int, image_url: str, 
                             title: str, description: str, tags: List[str]):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """INSERT INTO artworks 
                    (submitter_id, artist_id, image_url, title, description) 
                    VALUES (%s, %s, %s, %s, %s)""",
                    (submitter_id, artist_id, image_url, title, description)
                )
                artwork_id = cursor.lastrowid
                
                # Store tags
                for tag in tags:
                    await cursor.execute(
                        """INSERT INTO artwork_tags 
                        (artwork_id, tag) 
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE tag=tag""",
                        (artwork_id, tag.lower())
                    )
                
                await conn.commit()
                return artwork_id    

    async def store_artist(self, artist_name: str, social_media_link: str) -> int:
        """Store a new artist and return their ID"""
        query = '''
            INSERT INTO artists (artist_name, social_media_link)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE name=VALUES(name)
        '''
        cursor = await self.execute_query(query, (artist_name, social_media_link))
        return cursor.lastrowid
#
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
    async def get_artwork_palette(self, artwork_id: int):
        """Get palette with nuclear-grade type validation"""
        query = '''
            SELECT hex_code, dominance_rank, coverage
            FROM color_palettes
            WHERE artwork_id = %s
        '''
    
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, (artwork_id,))
                raw_data = await cursor.fetchall()
            
                validated_palette = []
                for color in raw_data:
                    try:
                        # Convert EVERY field with safety checks
                        hex_code = str(color['hex_code']) if color.get('hex_code') else '#000000'
                    
                        # Dominance rank must be convertable to int
                        try:
                            dom_rank = int(float(color['dominance_rank']))
                        except:
                            dom_rank = 999  # Default high value for invalid entries
                    
                        # Coverage must be convertable to float
                        try:
                            coverage = float(color['coverage']) if color.get('coverage') is not None else 0.0
                        except:
                            coverage = 0.0
                    
                        validated_palette.append({
                            'hex_code': hex_code,
                            'dominance_rank': dom_rank,
                            'coverage': coverage
                        })
                    except Exception as e:
                        self.logger.error(f"Corrupt color data skipped: {color} - {e}")
                        continue
            
                # Now sort with guaranteed valid types
                return sorted(
                    validated_palette,
                    key=lambda x: (
                        x['dominance_rank'],
                        -x['coverage']  # Secondary sort by coverage descending
                    )
                )
    async def close(self) -> None:
        """Cleanup resources when stopping"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None
            self.logger.info("Database connections closed")

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
    