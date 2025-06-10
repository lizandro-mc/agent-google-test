import os
import traceback
from datetime import datetime
import json
import psycopg2
from psycopg2.extras import RealDictCursor

# --- PostgreSQL Configuration ---
# Ensure these match the values in your docker-compose.yml
DB_NAME = os.environ.get("POSTGRES_DB", "graphdb")
DB_USER = os.environ.get("POSTGRES_USER", "myuser")
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "mypassword")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

def get_db_connection():
    """Establishes and returns a connection to the PostgreSQL database."""
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
        print(f"Error: Could not connect to the PostgreSQL database: {e}")
        return None

# --- Utility Function (Specific for SQL Queries) ---

def run_query(conn, sql_query, params=None):
    """
    Executes a standard SQL query in PostgreSQL.

    Args:
        conn: The psycopg2 database connection object.
        sql_query (str): The SQL query string.
        params (dict, optional): Dictionary of parameters for the query.

    Returns:
        list[dict]: A list of dictionaries representing the rows, or None if an error occurs.
    """
    if not conn:
        print("Error: Database connection is not available.")
        return None

    results_list = []
    print("--- Executing SQL Query ---")
    # print(f"SQL: {sql_query.strip()}") # Uncomment for detailed logging
    
    try:
        # Use RealDictCursor to get results directly as dictionaries
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql_query, params)
            results = cur.fetchall()
            results_list = [dict(row) for row in results]

    except psycopg2.Error as pg_err:
        print(f"PostgreSQL query error ({type(pg_err).__name__}): {pg_err}")
        conn.rollback() # Rollback the transaction in case of error
        return None
    except Exception as e:
        print(f"An unexpected error occurred during query execution: {e}")
        traceback.print_exc()
        return None

    return results_list


# --- Data Retrieval Functions using SQL ---

def get_person_attended_events_json(conn, person_id):
    """
    Retrieves events a specific person attended using SQL.

    Args:
        conn: The database connection object.
        person_id (str): The ID of the person.

    Returns:
        list[dict] or None: List of event dictionaries with dates in ISO format,
                           or None if an error occurs.
    """
    # SQL query that joins Person, Attendance, and Event to find the events.
    sql_query = """
        SELECT
            e.event_id,
            e.name,
            e.event_date,
            a.attendance_time
        FROM Person p
        JOIN Attendance a ON p.person_id = a.person_id
        JOIN Event e ON a.event_id = e.event_id
        WHERE p.person_id = %(person_id)s
        ORDER BY e.event_date DESC;
    """
    params = {"person_id": person_id}
    
    results = run_query(conn, sql_query, params=params)

    if results is None:
        return None

    # Convert datetime objects to ISO formatted strings
    for event in results:
        for key, value in event.items():
            if isinstance(value, datetime):
                event[key] = value.isoformat()

    return results


def get_all_posts_json(conn, limit=100):
    """
    Retrieves all available posts with the author's name using SQL.

    Args:
        conn: The database connection object.
        limit (int): Maximum number of posts to retrieve.

    Returns:
        list[dict] or None: List of post dictionaries with dates in ISO format,
                           or None if an error occurs.
    """
    # SQL query that joins Post and Person to get the author's name.
    sql_query = """
        SELECT
            p.post_id,
            p.author_id,
            p.text,
            p.sentiment,
            p.post_timestamp,
            author.name AS author_name
        FROM Post p
        JOIN Person author ON p.author_id = author.person_id
        ORDER BY p.post_timestamp DESC
        LIMIT %(limit)s;
    """
    params = {"limit": limit}

    results = run_query(conn, sql_query, params=params)

    if results is None:
        return None

    # Convert datetime objects to ISO formatted strings
    for post in results:
        for key, value in post.items():
            if isinstance(value, datetime):
                post[key] = value.isoformat()

    return results


def get_person_friends_json(conn, person_id):
    """
    Retrieves the friends of a specific person using SQL.

    Args:
        conn: The database connection object.
        person_id (str): The ID of the person.

    Returns:
        list[dict] or None: List of friend dictionaries ({person_id, name}),
                           or None if an error occurs.
    """
    # More complex SQL query that searches both "columns" of the Friendship table
    # and then joins with Person to get friend details.
    sql_query = """
        WITH friend_ids AS (
            SELECT person_id_b AS friend_id FROM Friendship WHERE person_id_a = %(person_id)s
            UNION
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

    results = run_query(conn, sql_query, params=params)

    # No date conversion needed here
    return results


# --- Usage Example (if executed directly) ---
if __name__ == "__main__":
    db_conn = get_db_connection()

    if db_conn:
        print("\n--- Testing Data Retrieval Functions with PostgreSQL ---")
        
        # Get a valid person ID from the database to use in tests
        test_person_id = None
        try:
            with db_conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT person_id, name FROM Person WHERE name = 'Alice' LIMIT 1;")
                test_person = cur.fetchone()
                if test_person:
                    test_person_id = test_person['person_id']
                    print(f"Test person found: {test_person['name']} (ID: {test_person_id})")
                else:
                    cur.execute("SELECT person_id FROM Person LIMIT 1;")
                    result = cur.fetchone()
                    if result:
                        test_person_id = result['person_id']
        except psycopg2.Error as e:
            print(f"Could not retrieve a test person: {e}")
        
        db_conn.commit() # Close the read-only transaction

        if test_person_id:
            print(f"\n1. Getting events attended by person with ID: {test_person_id}")
            attended_events = get_person_attended_events_json(db_conn, test_person_id)
            if attended_events is not None:
                print(json.dumps(attended_events, indent=2))
            else:
                print("Failed to retrieve attended events.")

            print("\n2. Getting all posts (limit 10)")
            all_posts = get_all_posts_json(db_conn, limit=10)
            if all_posts is not None:
                print(json.dumps(all_posts, indent=2))
            else:
                print("Failed to retrieve all posts.")

            print(f"\n3. Getting friends of person with ID: {test_person_id}")
            friends = get_person_friends_json(db_conn, test_person_id)
            if friends is not None:
                print(json.dumps(friends, indent=2))
            else:
                print("Failed to retrieve friends.")
        else:
            print("\nCould not find a person ID in the database to run tests.")
        
        # Close the connection at the end
        db_conn.close()
        print("\nDatabase connection closed.")

    else:
        print("\nCannot run examples: PostgreSQL database connection was not established.")