"""
Team Member Database
SQLite database setup and schema for team members, teams, and boards with many-to-many relationships
"""
import sqlite3
import os
from typing import Optional, List, Dict, Any, Tuple
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    """
    Get database file path from environment variable or use default.
    
    Environment variable: TEAM_MEMBER_DB_PATH
    Default: data/team_members.db (relative to project root)
    
    Returns:
        Path to the database file
    """
    # Check for custom path from environment variable
    custom_path = os.getenv('TEAM_MEMBER_DB_PATH')
    
    if custom_path:
        db_path = Path(custom_path)
        # If path is relative, make it relative to project root
        if not db_path.is_absolute():
            project_root = Path(__file__).parent.parent
            db_path = project_root / db_path
        logger.info(f"Using custom database path: {db_path}")
        return db_path
    else:
        # Default path: data/team_members.db relative to project root
        project_root = Path(__file__).parent.parent
        db_path = project_root / "data" / "team_members.db"
        return db_path


# Database file path (lazy evaluation)
DB_FILE = get_db_path()


def get_db_connection() -> sqlite3.Connection:
    """Get database connection, creating directory if needed"""
    # Ensure parent directory exists
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row  # Enable column access by name
    return conn


def init_database():
    """Initialize database schema with all tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Create members table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                level TEXT NOT NULL,
                capacity_days_per_sprint REAL DEFAULT 5.0,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create teams table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create member_teams junction table (many-to-many)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS member_teams (
                member_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                role TEXT,
                capacity_allocation REAL DEFAULT 1.0,
                is_active BOOLEAN DEFAULT 1,
                PRIMARY KEY (member_id, team_id),
                FOREIGN KEY (member_id) REFERENCES members(id) ON DELETE CASCADE,
                FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
            )
        """)
        
        # Create boards table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                jira_board_id INTEGER UNIQUE,
                name TEXT NOT NULL,
                project_key TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create team_boards junction table (many-to-many)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS team_boards (
                team_id INTEGER NOT NULL,
                board_id INTEGER NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                PRIMARY KEY (team_id, board_id),
                FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
                FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE
            )
        """)
        
        # Create indexes for better query performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_member_teams_member ON member_teams(member_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_member_teams_team ON member_teams(team_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_team_boards_team ON team_boards(team_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_team_boards_board ON team_boards(board_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_members_email ON members(email)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_teams_name ON teams(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_boards_jira_id ON boards(jira_board_id)")
        
        conn.commit()
        logger.info(f"✅ Database initialized: {DB_FILE}")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Failed to initialize database: {str(e)}")
        raise
    finally:
        conn.close()


def check_database_ready() -> Tuple[bool, str]:
    """
    Check if the database is ready and accessible.
    
    Returns:
        tuple: (is_ready: bool, message: str)
        - is_ready: True if database is accessible and properly initialized
        - message: Status message describing the database state
    """
    try:
        # Check if we can get a connection
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if required tables exist
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name IN ('members', 'teams', 'boards', 'member_teams', 'team_boards')
        """)
        tables = {row[0] for row in cursor.fetchall()}
        
        required_tables = {'members', 'teams', 'boards', 'member_teams', 'team_boards'}
        missing_tables = required_tables - tables
        
        if missing_tables:
            conn.close()
            return False, f"Database missing required tables: {', '.join(missing_tables)}"
        
        # Test write access by doing a simple query
        cursor.execute("SELECT COUNT(*) FROM members")
        cursor.fetchone()
        
        # Test that we can write (check if directory is writable)
        try:
            # Try to create a test file in the same directory
            test_file = DB_FILE.parent / ".db_write_test"
            test_file.touch()
            test_file.unlink()
        except PermissionError:
            conn.close()
            return False, f"Database directory is not writable: {DB_FILE.parent}"
        
        conn.close()
        return True, f"Database ready at {DB_FILE}"
        
    except sqlite3.Error as e:
        return False, f"Database error: {str(e)}"
    except PermissionError as e:
        return False, f"Permission denied accessing database: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error checking database: {str(e)}"


def ensure_database_ready() -> None:
    """
    Ensure database is ready and accessible, initializing if necessary.
    Raises RuntimeError if database cannot be made ready.
    """
    is_ready, message = check_database_ready()
    
    if not is_ready:
        # Try to initialize the database
        logger.warning(f"Database not ready: {message}. Attempting to initialize...")
        try:
            init_database()
            # Verify it's ready now
            is_ready, message = check_database_ready()
            if not is_ready:
                raise RuntimeError(f"Failed to initialize database: {message}")
            logger.info(f"✅ Database initialized and ready: {message}")
        except Exception as e:
            raise RuntimeError(f"Failed to ensure database is ready: {str(e)}")
    else:
        logger.info(f"✅ Database ready: {message}")


# Initialize database on module import
init_database()


