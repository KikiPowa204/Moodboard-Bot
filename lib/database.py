import aiomysql
import os
import logging
from urllib.parse import urlparse
from typing import Optional, Dict, List, Union

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
        """Initialize connection pool"""
        if self.pool is not None:
            self.logger.warning("Connection pool already exists")
            return
            
        await self._create_connection()
        await self.init_db()  # Initialize tables on startup
        self.logger.info(f"Pool initialized. Autocommit: {self.pool.autocommit}")

    async def _create_connection(self) -> None:
        """Create MySQL connection pool"""
        try:
            config = self._parse_public_url()
            
            self.pool = await aiomysql.create_pool(
                host=config['host'],
                port=config['port'],
                user=config['user'],
                password=config['password'],
                db=config['db'],
                minsize=5,
                maxsize=10,
                connect_timeout=10,
                autocommit=False,
                cursorclass=aiomysql.DictCursor,  # Return results as dictionaries
                use_unicode=True,
                charset='utf8mb4',
                # ↓ This forces PyMySQL usage ↓
                connector=aiomysql.connectors.PyMySQLConnector
            )
            self.logger.info(f"Connected to MySQL at {config['host']}:{config['port']}")
        except Exception as e:
            self.logger.error("Connection failed", exc_info=True)
            raise ConnectionError(f"MySQL connection failed: {e}")

    async def execute_query(self, query: str, args: Optional[tuple] = None) -> aiomysql.Cursor:
        """Execute a single query with parameters"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute(query, args or ())
                    await conn.commit()
                    return cursor
                except Exception as e:
                    await conn.rollback()
                    self.logger.error(f"Query failed: {query}", exc_info=True)
                    raise

    async def init_db(self) -> None:
        """Initialize database tables"""
        tables = {
            'artists': '''
                CREATE TABLE IF NOT EXISTS artists (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    discord_id VARCHAR(255) UNIQUE NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''',
            'artworks': '''
                CREATE TABLE IF NOT EXISTS artworks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    artist_id INT NOT NULL,
                    image_url TEXT NOT NULL,
                    title VARCHAR(255),
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (artist_id) REFERENCES artists(id),
                    INDEX idx_artist (artist_id)
                )
            ''',
            'color_palettes': '''
                CREATE TABLE IF NOT EXISTS color_palettes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    artwork_id INT NOT NULL,
                    hex_code VARCHAR(7) NOT NULL,
                    dominance_rank TINYINT NOT NULL,
                    coverage DECIMAL(5,2),
                    FOREIGN KEY (artwork_id) REFERENCES artworks(id),
                    CONSTRAINT valid_hex CHECK (hex_code REGEXP '^#[0-9A-F]{6}$'),
                    INDEX idx_artwork (artwork_id),
                    INDEX idx_color (hex_code)
                )
            '''
        }

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                for table_name, ddl in tables.items():
                    try:
                        await cursor.execute(ddl)
                        self.logger.info(f"Table {table_name} initialized")
                    except Exception as e:
                        self.logger.error(f"Failed to create {table_name}", exc_info=True)
                        raise

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
        """Clean up connection pool"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            self.logger.info("Connection pool closed")
    # Add these new methods to your MySQLStorage class
async def get_or_create_artist(self, discord_id: str, name: str) -> dict:
    """Get or create artist record"""
    artist_id = await self.store_artist(discord_id, name)
    return {'id': artist_id, 'discord_id': discord_id, 'name': name}

async def full_submission_pipeline(self, artist_id: int, image_url: str, 
                                 palette: List[dict], metadata: dict) -> bool:
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
    
mysql_storage= MySQLStorage