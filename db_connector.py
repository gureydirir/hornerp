import os
import sqlite3
import datetime

# Try to import psycopg2 for Postgres
try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("RENDER")

class SafeCursor:
    def __init__(self, cursor, db_type):
        self.cursor = cursor
        self.db_type = db_type

    def execute(self, sql, params=None):
        if self.db_type == 'postgres':
            # Basic conversion: replace ? with %s
            # Note: This is a simple replacements. String literals containing ? will break.
            # But for this app, it's likely fine.
            sql = sql.replace('?', '%s')
        
        try:
            if params:
                return self.cursor.execute(sql, params)
            return self.cursor.execute(sql)
        except Exception as e:
            print(f"SQL Error ({self.db_type}): {e} | Query: {sql}")
            raise e

    def fetchone(self): return self.cursor.fetchone()
    def fetchall(self): return self.cursor.fetchall()
    def close(self): return self.cursor.close()
    
    @property
    def description(self): return self.cursor.description

    @property
    def rowcount(self): return self.cursor.rowcount
    
    @property
    def lastrowid(self): 
         return getattr(self.cursor, 'lastrowid', None)

class SafeConnection:
    def __init__(self, conn, db_type):
        self.conn = conn
        self.db_type = db_type
    
    def cursor(self):
        return SafeCursor(self.conn.cursor(), self.db_type)
        
    def commit(self): return self.conn.commit()
    def close(self): return self.conn.close()
    def rollback(self): return self.conn.rollback()

    def execute(self, sql, params=None):
        # Support for conn.execute() which sqlite3 allows but psycopg2 doesn't
        c = self.cursor()
        c.execute(sql, params)
        return c

class DBHandler:
    @staticmethod
    def get_connection():
        """Returns a database connection (SQLite or Postgres) wrapped in SafeConnection."""
        if DATABASE_URL and HAS_POSTGRES:
            # Postgres (Cloud / Render)
            try:
                conn = psycopg2.connect(DATABASE_URL, sslmode='require')
                return SafeConnection(conn, 'postgres')
            except Exception as e:
                print(f"Postgres Connection Error: {e}")
                return None
        else:
            # SQLite (Local)
            conn = sqlite3.connect("horn.db", timeout=30)
            return SafeConnection(conn, 'sqlite')

    @staticmethod
    def get_placeholder():
        """Returns '?' for SQLite or '%s' for Postgres."""
        if DATABASE_URL and HAS_POSTGRES:
            return "%s"
        return "?"
    
    @staticmethod
    def get_auto_id_sql():
        """Returns the SQL type for Auto Increment ID."""
        if DATABASE_URL and HAS_POSTGRES:
            return "SERIAL PRIMARY KEY"
        return "INTEGER PRIMARY KEY AUTOINCREMENT"

def get_pak_time():
    # Helper for timezone (used across app)
    # Pakistan Standard Time is UTC+5
    tz = datetime.timezone(datetime.timedelta(hours=5))
    return datetime.datetime.now(tz)
