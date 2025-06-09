# postgres_data_fetchers.py

import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
import traceback
from datetime import datetime, timezone
import json # For example usage (e.g., printing data)

load_dotenv()

# --- PostgreSQL Configuration ---
# Environment variables should be set in your .env file or Docker Compose
DB_NAME = os.environ.get("POSTGRES_DB", "graphdb")
DB_USER = os.environ.get("POSTGRES_USER", "myuser")
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "mypassword")
DB_HOST = os.environ.get("POSTGRES_HOST", "postgres") # 'postgres' is the service name in docker-compose.yml
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

# --- Database Connection Initialization ---
# Using a global connection object for simplicity.
# In a larger application, consider implementing a connection pool for better performance and resource management.
conn = None

def get_db_connection():
    """Establishes and returns a connection to the PostgreSQL database."""
    global conn
    # Check if an existing connection is still healthy
    if conn is not None and not conn.closed:
        try:
            # Attempt a simple query to check connection health
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn # Connection is healthy, return it
        except psycopg2.OperationalError:
            print("Existing DB connection is stale or lost, attempting to reconnect.")
            conn = None # Invalidate stale connection

    # Try to establish a new connection
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        print("Successfully connected to the PostgreSQL database.")
        return conn
    except psycopg2.OperationalError as e:
        print(f"Error: Could not connect to the PostgreSQL database. Please ensure the database server is running and accessible. Details: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during PostgreSQL initialization: {e}")
        return None

# Attempt initial connection when the module is imported
get_db_connection()


def run_query(sql_query: str, params: dict = None) -> list[dict]:
    """
    Executes a SQL query against the PostgreSQL database.
    Uses RealDictCursor to return rows as dictionaries with column names as keys.

    Args:
        sql_query (str): The SQL query string.
        params (dict, optional): A dictionary of parameters to pass to the query.
                                 Uses named placeholders (e.g., %(param_name)s) in the SQL string.
                                 Defaults to None.

    Returns:
        list[dict]: A list of dictionaries, where each dictionary represents a row.
                    Returns an empty list if no results are found or if an error occurs.
    """
    global conn
    if conn is None or conn.closed:
        conn = get_db_connection() # Attempt to re-establish connection if it's closed or None
        if conn is None:
            print("Error: Database connection is not available for query execution.")
            return [] # Return empty list if connection cannot be established

    results_list = []
    print(f"--- Executing SQL ---")
    print(f"SQL: {sql_query.strip()}")
    if params:
        print(f"Params: {params}")
    print("----------------------")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql_query, params)
            if cur.description: # Check if the query returned any rows (e.g., SELECT statements)
                results_list = cur.fetchall()
        
        # Commit changes if the query was a DML (INSERT, UPDATE, DELETE)
        # For SELECT statements, commit is typically a no-op but harmless.
        conn.commit() 

    except psycopg2.Error as pg_err:
        print(f"PostgreSQL Query Error ({type(pg_err).__name__}): {pg_err}")
        traceback.print_exc()
        conn.rollback() # Rollback the transaction in case of an error
        return []
    except Exception as e:
        print(f"An unexpected error occurred during query execution or processing: {e}")
        traceback.print_exc()
        return []

    print(f"Query successful, fetched {len(results_list)} rows.")
    return results_list


# --- Data Fetchers (Translated from Spanner Graph to PostgreSQL SQL) ---

def get_person_attended_events(person_id: str) -> list[dict]:
    """
    Fetches events attended by a specific person using standard SQL.
    This query translates the Spanner Graph pattern (p:Person)-[att:Attended]->(e:Event).
    """
    sql = """
        SELECT
            e.event_id,
            e.name,
            e.event_date,
            a.attendance_time
        FROM Event AS e
        JOIN Attendance AS a ON e.event_id = a.event_id
        JOIN Person AS p ON a.person_id = p.person_id
        WHERE p.person_id = %(person_id)s
        ORDER BY e.event_date DESC;
    """
    params = {"person_id": person_id}
    results = run_query(sql, params=params)

    # Ensure datetimes are converted to ISO strings for consistent output
    for event in results: # 'results' will always be a list, even if empty or on error
        if isinstance(event.get('event_date'), datetime):
            event['event_date'] = event['event_date'].isoformat()
        if isinstance(event.get('attendance_time'), datetime):
            event['attendance_time'] = event['attendance_time'].isoformat()
    return results


def get_person_id_by_name(name: str) -> str | None:
    """
    Fetches the person_id for a given name using standard SQL.
    Returns the ID of the *first* match if names are duplicated.
    """
    sql = """
        SELECT person_id
        FROM Person
        WHERE name = %(name)s
        LIMIT 1;
    """
    params = {"name": name}
    results = run_query(sql, params=params)

    if results:
        return results[0].get('person_id')
    else:
        return None


def get_person_posts(person_id: str) -> list[dict]:
    """
    Fetches posts written by a specific person using standard SQL.
    This query translates the Spanner Graph pattern (author:Person)-[w:Wrote]->(post:Post).
    """
    sql = """
        SELECT
            p.post_id,
            p.author_id,
            p.text,
            p.sentiment,
            p.post_timestamp,
            a.name AS author_name
        FROM Post AS p
        JOIN Person AS a ON p.author_id = a.person_id
        WHERE p.author_id = %(person_id)s
        ORDER BY p.post_timestamp DESC;
    """
    params = {"person_id": person_id}
    results = run_query(sql, params=params)

    for post in results: # 'results' will always be a list, even if empty or on error
        if isinstance(post.get('post_timestamp'), datetime):
            post['post_timestamp'] = post['post_timestamp'].isoformat()
    return results


def get_person_friends(person_id: str) -> list[dict]:
    """
    Fetches friends for a specific person using standard SQL (handles bidirectional friendships).
    This query translates the Spanner Graph pattern (p:Person {person_id: @person_id})-[f:Friendship]-(friend:Person).
    """
    sql = """
        WITH friend_ids AS (
            -- Friends where the given person is person_id_a
            SELECT person_id_b AS friend_id FROM Friendship WHERE person_id_a = %(person_id)s
            UNION
            -- Friends where the given person is person_id_b
            SELECT person_id_a AS friend_id FROM Friendship WHERE person_id_b = %(person_id)s
        )
        SELECT
            p.person_id,
            p.name
        FROM Person p
        JOIN friend_ids f ON p.person_id = f.friend_id
        ORDER BY p.name;
    """
    params = {"person_id": person_id}
    results = run_query(sql, params=params)
        
    return results # 'results' will always be a list, even if empty or on error

# Example Usage (for testing this file independently if needed)
if __name__ == "__main__":
    print("--- Testing PostgreSQL Data Fetchers ---")

    # Ensure a connection is established for testing
    if get_db_connection() is None:
        print("Failed to connect to PostgreSQL. Cannot run tests.")
        exit(1)

    # Example: Add some dummy data if your DB is empty for testing.
    # In a real application, you would typically have a separate script for initial data
    # or use migrations.
    try:
        run_query("""
            INSERT INTO Person (person_id, name, age) VALUES ('test_user_1', 'Alice Smith', 30) ON CONFLICT (person_id) DO NOTHING;
            INSERT INTO Person (person_id, name, age) VALUES ('test_user_2', 'Bob Johnson', 25) ON CONFLICT (person_id) DO NOTHING;
            INSERT INTO Person (person_id, name, age) VALUES ('test_user_3', 'Charlie Brown', 35) ON CONFLICT (person_id) DO NOTHING;
            INSERT INTO Post (post_id, author_id, text, post_timestamp, sentiment) VALUES ('post_1', 'test_user_1', 'Hello world!', NOW(), 'positive') ON CONFLICT (post_id) DO NOTHING;
            INSERT INTO Post (post_id, author_id, text, post_timestamp, sentiment) VALUES ('post_2', 'test_user_1', 'Another post.', NOW(), 'neutral') ON CONFLICT (post_id) DO NOTHING;
            -- FIXED INSERT for Event: Added 'description' value
            INSERT INTO Event (event_id, name, event_date, description) VALUES ('event_1', 'Concert Night', NOW(), 'A fantastic evening of live music.') ON CONFLICT (event_id) DO NOTHING;
            INSERT INTO Event (event_id, name, event_date, description) VALUES ('event_2', 'Tech Meetup', NOW(), 'Discussion on the latest tech trends.') ON CONFLICT (event_id) DO NOTHING;
            INSERT INTO Attendance (event_id, person_id, attendance_time) VALUES ('event_1', 'test_user_1', NOW()) ON CONFLICT (event_id, person_id) DO NOTHING;
            INSERT INTO Attendance (event_id, person_id, attendance_time) VALUES ('event_1', 'test_user_2', NOW()) ON CONFLICT (event_id, person_id) DO NOTHING;
            INSERT INTO Friendship (person_id_a, person_id_b) VALUES ('test_user_1', 'test_user_2') ON CONFLICT (person_id_a, person_id_b) DO NOTHING;
        """)
        print("Dummy data inserted/ensured.")
    except Exception as e:
        print(f"Could not insert dummy data: {e}")

    # Test get_person_id_by_name
    print("\n--- Testing get_person_id_by_name ('Alice Smith') ---")
    alice_id = get_person_id_by_name("Alice Smith")
    print(f"Alice's ID: {alice_id}")
    if alice_id:
        # Test get_person_posts
        print(f"\n--- Testing get_person_posts for {alice_id} ---")
        posts = get_person_posts(alice_id)
        print(json.dumps(posts, indent=2))

        # Test get_person_attended_events
        print(f"\n--- Testing get_person_attended_events for {alice_id} ---")
        attended_events = get_person_attended_events(alice_id)
        print(json.dumps(attended_events, indent=2))

        # Test get_person_friends
        print(f"\n--- Testing get_person_friends for {alice_id} ---")
        friends = get_person_friends(alice_id)
        print(json.dumps(friends, indent=2))
    else:
        print("Alice Smith not found, skipping related tests.")

    # Close connection (important for single-file testing)
    if conn:
        conn.close()
        print("\nDatabase connection closed.")