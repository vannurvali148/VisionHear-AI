
import os
import pymysql
from contextlib import contextmanager
from urllib.parse import urlparse, unquote


# ==========================================
# DATABASE CONFIGURATION
# ==========================================

def get_db_config():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is missing"
        )

    parsed = urlparse(database_url)

    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": unquote(parsed.path.lstrip("/")),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False
    }


# ==========================================
# MYSQL CURSOR WRAPPER
# ==========================================

class MySQLCursor:

    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        self.cursor.execute(sql, params or ())
        return self

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    @property
    def rowcount(self):
        return self.cursor.rowcount


# ==========================================
# MYSQL CONNECTION WRAPPER
# ==========================================

class MySQLConnection:

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=None):
        cursor = self.connection.cursor()
        sql = sql.replace("?", "%s")
        cursor.execute(sql, params or ())
        return cursor

    def cursor(self):
        return MySQLCursor(self.connection.cursor())


# ==========================================
# DATABASE CONNECTION
# ==========================================

@contextmanager
def get_connection():

    raw_connection = pymysql.connect(**get_db_config())
    connection = MySQLConnection(raw_connection)

    try:
        yield connection
        raw_connection.commit()

    except Exception:
        raw_connection.rollback()
        raise

    finally:
        raw_connection.close()


# ==========================================
# INITIALIZE DATABASE TABLES
# ==========================================

def init_db():

    tables = [

        # USERS
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            full_name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role VARCHAR(50) NOT NULL DEFAULT 'student',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,

        # EYE TESTS
        """
        CREATE TABLE IF NOT EXISTS eye_tests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            status VARCHAR(50) DEFAULT 'in_progress',
            accuracy FLOAT DEFAULT NULL,
            average_response_time FLOAT DEFAULT NULL,
            test_mode VARCHAR(50) DEFAULT 'without',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME DEFAULT NULL,
            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,

        # EYE RESPONSES
        """
        CREATE TABLE IF NOT EXISTS eye_responses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            test_id INT NOT NULL,
            question_number INT NOT NULL,
            response VARCHAR(255),
            is_correct TINYINT(1) DEFAULT 0,
            response_time FLOAT DEFAULT 0,
            FOREIGN KEY (test_id)
                REFERENCES eye_tests(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,

        # HEARING TESTS
        """
        CREATE TABLE IF NOT EXISTS hearing_tests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            status VARCHAR(50) DEFAULT 'in_progress',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME DEFAULT NULL,
            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,

        # HEARING RESPONSES
        """
        CREATE TABLE IF NOT EXISTS hearing_responses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            test_id INT NOT NULL,
            ear VARCHAR(20),
            frequency_hz INT,
            response VARCHAR(50),
            response_time FLOAT DEFAULT 0,
            intensity_level VARCHAR(50),
            intensity_percent FLOAT,
            FOREIGN KEY (test_id)
                REFERENCES hearing_tests(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,

        # AI ANALYSIS
        """
        CREATE TABLE IF NOT EXISTS ai_analysis (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            test_type VARCHAR(50),
            pattern_label VARCHAR(255),
            model_name VARCHAR(255),
            analysis_details LONGTEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,

        # ACTIVITY LOGS
        """
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            activity VARCHAR(255) NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,

        # ADMIN REQUESTS
        """
        CREATE TABLE IF NOT EXISTS admin_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            college_name VARCHAR(255) NOT NULL,
            college_id VARCHAR(255) NOT NULL,
            reason TEXT NOT NULL,
            proof_filename VARCHAR(255) NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            reviewed_by INT DEFAULT NULL,
            reviewed_at DATETIME DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id)
                REFERENCES users(id),
            FOREIGN KEY (reviewed_by)
                REFERENCES users(id)
                ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,

        # SYSTEM SETTINGS
        """
        CREATE TABLE IF NOT EXISTS system_settings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            setting_key VARCHAR(255) NOT NULL UNIQUE,
            setting_value TEXT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    ]

    with get_connection() as conn:
        cursor = conn.cursor()

        for table_sql in tables:
            cursor.execute(table_sql)
