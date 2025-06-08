import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, render_template, abort, flash, request, jsonify
import psycopg2 # Changed from google.cloud.spanner
from psycopg2.extras import RealDictCursor # For dictionary-like rows
import humanize 
import uuid
import traceback
from dateutil import parser 
from routes import ally_bp 

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a_default_secret_key_for_dev") 
app.register_blueprint(ally_bp)

load_dotenv()

# --- PostgreSQL Configuration (Dockerized) ---
DB_NAME = os.environ.get("POSTGRES_DB", "graphdb")
DB_USER = os.environ.get("POSTGRES_USER", "myuser")
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "mypassword")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost") # This should be your Docker service name if running Flask in Docker
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

# --- Application Configuration ---
APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = os.environ.get("APP_PORT","8080")
Maps_API_KEY = os.environ.get("Maps_API_KEY") # Still using Google Maps API
Maps_MAP_KEY = os.environ.get('Maps_MAP_ID')

# --- Database Connection Initialization ---
conn = None # Renamed `db` to `conn` for PostgreSQL connection object

def get_db_connection():
    """Establishes and returns a connection to the PostgreSQL database."""
    global conn # Declare conn as global to modify it
    if conn is not None and not conn.closed:
        # Check if the connection is still healthy
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
        except psycopg2.OperationalError:
            print("Existing DB connection is stale, attempting to reconnect.")
            conn = None # Invalidate stale connection

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
    except Exception as e:
        print(f"An unexpected error occurred during PostgreSQL initialization: {e}")
        return None

# Attempt initial connection
get_db_connection()

# --- Utility Function for Database Operations ---

def run_query(sql_query, params=None):
    """
    Executes a SQL query against the PostgreSQL database.

    Args:
        sql_query (str): The SQL query string.
        params (dict, optional): Dictionary of query parameters. Defaults to None.
                                 For psycopg2, parameters should be passed as a dictionary
                                 when using named placeholders (e.g., %(param_name)s).

    Returns:
        list[dict]: A list of dictionaries representing the rows, or None if an error occurs.
                    Returns an empty list if no results are found.
    """
    global conn
    if conn is None or conn.closed:
        conn = get_db_connection() # Try to re-establish connection if lost
        if conn is None:
            print("Error: Database connection is not available.")
            flash("Database connection not available.", "danger")
            return [] # Return empty list if connection fails

    results_list = []
    print(f"--- Executing SQL ---")
    print(f"SQL: {sql_query.strip()}")
    if params:
        print(f"Params: {params}")
    print("----------------------")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql_query, params)
            if cur.description: # Check if there are results to fetch
                results_list = cur.fetchall()
            # Convert psycopg2.RealDictRow to regular dicts for consistency
            results_list = [dict(row) for row in results_list]
        conn.commit() # Commit changes for DML statements (INSERT, UPDATE, DELETE)

    except psycopg2.Error as pg_err:
        print(f"PostgreSQL Error ({type(pg_err).__name__}): {pg_err}")
        traceback.print_exc()
        conn.rollback() # Rollback the transaction in case of error
        flash(f"Database error: {pg_err}", "danger")
        return []
    except Exception as e:
        print(f"An unexpected error occurred during query execution or processing: {e}")
        traceback.print_exc()
        flash(f"An unexpected server error occurred while fetching data.", "danger")
        # Do not raise 'e' here if you want to handle it gracefully in routes
        return []

    print(f"Query successful, fetched {len(results_list)} rows.")
    return results_list

# --- Data Retrieval Functions using PostgreSQL ---

def get_all_posts_with_author_db():
    """Fetch all posts and join with author information from PostgreSQL."""
    sql = """
        SELECT
            p.post_id, p.author_id, p.text, p.sentiment, p.post_timestamp,
            author.name AS author_name
        FROM Post AS p
        JOIN Person AS author ON p.author_id = author.person_id
        ORDER BY p.post_timestamp DESC;
    """
    # No `expected_fields` needed as RealDictCursor gives dicts with column names
    results = run_query(sql)
    # Convert datetime objects to ISO strings for JSON serialization if needed
    for row in results:
        if isinstance(row.get('post_timestamp'), datetime):
            row['post_timestamp'] = row['post_timestamp'].isoformat()
    return results

def get_person_db(person_id):
    """Fetch a single person's details from PostgreSQL."""
    sql = """
        SELECT person_id, name, age
        FROM Person
        WHERE person_id = %(person_id)s;
    """
    params = {"person_id": person_id}
    results = run_query(sql, params=params)
    return results[0] if results else None

def get_posts_by_person_db(person_id):
    """Fetch posts written by a specific person from PostgreSQL."""
    sql = """
        SELECT
            p.post_id, p.author_id, p.text, p.sentiment, p.post_timestamp,
            author.name AS author_name
        FROM Post AS p
        JOIN Person AS author ON p.author_id = author.person_id
        WHERE p.author_id = %(person_id)s
        ORDER BY p.post_timestamp DESC;
    """
    params = {"person_id": person_id}
    results = run_query(sql, params=params)
    # Convert datetime objects to ISO strings for JSON serialization if needed
    for row in results:
        if isinstance(row.get('post_timestamp'), datetime):
            row['post_timestamp'] = row['post_timestamp'].isoformat()
    return results

def get_friends_db(person_id):
    """Fetch friends of a specific person from PostgreSQL."""
    # This query needs to select from Person directly for the friend's details
    # The WITH clause correctly identifies friend_ids from both sides of the friendship.
    sql = """
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
    return run_query(sql, params=params)


def get_all_events_with_attendees_db():
    """Fetch all events and their attendees from PostgreSQL."""
    # Get all events first
    event_sql = """
        SELECT event_id, name, event_date, description
        FROM Event
        ORDER BY event_date DESC
        LIMIT 50;
    """
    events = run_query(event_sql)
    if not events:
        return []

    # Convert datetime objects to ISO strings for JSON serialization if needed
    for event in events:
        if isinstance(event.get('event_date'), datetime):
            event['event_date'] = event['event_date'].isoformat()

    events_with_attendees = {event['event_id']: {'details': event, 'attendees': []} for event in events}
    event_ids = list(events_with_attendees.keys())

    if not event_ids:
        return []

    # Fetch attendees for all relevant events
    # Use array parameter for IN clause in PostgreSQL
    attendee_sql = """
        SELECT
            a.event_id,
            p.person_id, p.name
        FROM Attendance AS a
        JOIN Person AS p ON a.person_id = p.person_id
        WHERE a.event_id = ANY(%(event_ids)s)
        ORDER BY a.event_id, p.name;
    """
    params = {"event_ids": event_ids}
    all_attendees = run_query(attendee_sql, params=params)

    for attendee in all_attendees:
        event_id = attendee['event_id']
        if event_id in events_with_attendees:
            events_with_attendees[event_id]['attendees'].append(attendee)

    return [events_with_attendees[event['event_id']] for event in events]

def get_event_details_with_locations_attendees_db(event_id):
    """
    Fetch full details for a single event, including its description,
    locations, and attendees from PostgreSQL.
    """
    # Ensure connection is active
    global conn
    if conn is None or conn.closed:
        conn = get_db_connection()
        if conn is None:
            raise ConnectionError("PostgreSQL database connection not initialized.")

    event_details = {}

    # 1. Fetch Event basic details
    event_sql = """
        SELECT event_id, name, description, event_date
        FROM Event
        WHERE event_id = %(event_id)s;
    """
    params = {"event_id": event_id}
    event_result = run_query(event_sql, params=params)

    if not event_result:
        return None # Event not found
    event_details = event_result[0]

    # Convert event_date to ISO format
    if isinstance(event_details.get('event_date'), datetime):
        event_details['event_date'] = event_details['event_date'].isoformat()

    # 2. Fetch Event Locations
    locations_sql = """
        SELECT l.location_id, l.name, l.description, l.latitude, l.longitude, l.address
        FROM Location AS l
        JOIN EventLocation AS el ON l.location_id = el.location_id
        WHERE el.event_id = %(event_id)s
        ORDER BY l.name;
    """
    event_details["locations"] = run_query(locations_sql, params=params)

    # Ensure latitude/longitude are floats
    for loc in event_details.get("locations", []):
        if loc.get("latitude") is not None: loc["latitude"] = float(loc["latitude"])
        if loc.get("longitude") is not None: loc["longitude"] = float(loc["longitude"])

    # 3. Fetch Event Attendees
    attendees_sql = """
        SELECT p.person_id, p.name
        FROM Person AS p
        JOIN Attendance AS a ON p.person_id = a.person_id
        WHERE a.event_id = %(event_id)s
        ORDER BY p.name;
    """
    event_details["attendees"] = run_query(attendees_sql, params=params)

    return event_details


# --- Custom Jinja Filter ---
@app.template_filter('humanize_datetime')
def _jinja2_filter_humanize_datetime(value, default="just now"):
    """
    Convert a datetime object to a human-readable relative time string.
    e.g., '5 minutes ago', '2 hours ago', '3 days ago'
    """
    if not value:
        return default
   
    dt_object = None
    if isinstance(value, str):
        try:
            # Attempt to parse ISO 8601 format.
            # .replace('Z', '+00:00') handles UTC 'Z' suffix for fromisoformat.
            dt_object = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            # Fallback to dateutil.parser for more general string formats
            try:
                dt_object = parser.parse(value)
            except (parser.ParserError, TypeError, ValueError) as e:
                app.logger.warning(f"Could not parse date string '{value}' in humanize_datetime: {e}")
                return str(value) # Return original string if unparseable
    elif isinstance(value, datetime):
        dt_object = value
    else:
        # If not a string or datetime, return its string representation
        return str(value)

    if dt_object is None: # Should have been handled, but as a safeguard
        app.logger.warning(f"Date value '{value}' resulted in None dt_object in humanize_datetime.")
        return str(value)

    now = datetime.now(timezone.utc)
    # Use dt_object for all datetime operations from here
    if dt_object.tzinfo is None or dt_object.tzinfo.utcoffset(dt_object) is None:
        # If dt_object is naive, assume it's UTC
        dt_object = dt_object.replace(tzinfo=timezone.utc)
    else:
        # Convert aware dates to UTC
        dt_object = dt_object.astimezone(timezone.utc)

    try:
        return humanize.naturaltime(now - dt_object)
    except TypeError:
        # Fallback or handle error if date calculation fails
        return dt_object.strftime("%Y-%m-%d %H:%M")


def get_person_by_name_db(name):
    """Fetch a person's ID by their name from PostgreSQL."""
    global conn
    if conn is None or conn.closed:
        conn = get_db_connection()
        if conn is None:
            print("Error: Database connection is not available.")
            raise ConnectionError("PostgreSQL database connection not initialized.")

    sql = "SELECT person_id FROM Person WHERE name = %(name)s LIMIT 1;"
    params = {"name": name}
    try:
        results = run_query(sql, params=params)
        return results[0]['person_id'] if results else None
    except Exception as e:
        print(f"Error fetching person by name '{name}': {e}")
        raise e

# --- Helper function to insert a post ---
def add_post_db(post_id, author_id, text, sentiment=None):
    """Inserts a new post into the PostgreSQL database."""
    global conn
    if conn is None or conn.closed:
        conn = get_db_connection()
        if conn is None:
            print("Error: Database connection is not available for insert.")
            raise ConnectionError("PostgreSQL database connection not initialized.")

    try:
        with conn.cursor() as cur:
            sql = """
                INSERT INTO Post (post_id, author_id, text, sentiment, post_timestamp, create_time)
                VALUES (%(post_id)s, %(author_id)s, %(text)s, %(sentiment)s, %(post_timestamp)s, NOW() AT TIME ZONE 'UTC');
            """
            params = {
                "post_id": post_id,
                "author_id": author_id,
                "text": text,
                "sentiment": sentiment,
                "post_timestamp": datetime.now(timezone.utc)
            }
            cur.execute(sql, params)
        conn.commit()
        print(f"Successfully inserted post_id: {post_id}")
        return True
    except Exception as e:
        print(f"Error inserting post (id: {post_id}): {e}")
        conn.rollback() # Rollback on error
        return False # Indicate failure

def add_full_event_with_details_db(event_id, event_name, description, event_date, locations_data, attendee_ids):
    """
    Inserts a new event with its title, description, multiple locations,
    and its first attendee into PostgreSQL within a transaction.

    Args:
        event_id (str): The unique ID for the new event.
        event_name (str): Name of the event (maps to Event.name).
        description (str): Description of the event.
        event_date (datetime): Date/time of the event (timezone-aware recommended).
        locations_data (list[dict]): A list of location dictionaries. Each dict should contain:
                                     'name', 'description', 'latitude', 'longitude', 'address'.
        attendee_ids (list[str]): A list of person_ids for the attendees.

    Returns:
        bool: True if the transaction was successful, False otherwise.
    """
    global conn
    if conn is None or conn.closed:
        conn = get_db_connection()
        if conn is None:
            print("Error: Database connection is not available for full event insert.")
            raise ConnectionError("PostgreSQL database connection not initialized.")

    try:
        with conn.cursor() as cur:
            # Insert into Event table
            event_sql = """
                INSERT INTO Event (event_id, name, description, event_date, create_time)
                VALUES (%(event_id)s, %(name)s, %(description)s, %(event_date)s, NOW() AT TIME ZONE 'UTC');
            """
            cur.execute(event_sql, {
                "event_id": event_id,
                "name": event_name,
                "description": description,
                "event_date": event_date
            })
            print(f"Transaction attempting to insert event_id: {event_id}")

            # Insert Locations and EventLocation links
            for loc_data in locations_data:
                location_id = str(uuid.uuid4())
                location_sql = """
                    INSERT INTO Location (location_id, name, description, latitude, longitude, address, create_time)
                    VALUES (%(location_id)s, %(name)s, %(description)s, %(latitude)s, %(longitude)s, %(address)s, NOW() AT TIME ZONE 'UTC');
                """
                cur.execute(location_sql, {
                    "location_id": location_id,
                    "name": loc_data.get("name"),
                    "description": loc_data.get("description"),
                    "latitude": float(loc_data.get("latitude", 0.0)),
                    "longitude": float(loc_data.get("longitude", 0.0)),
                    "address": loc_data.get("address")
                })
                print(f"Transaction attempting to insert location_id: {location_id} for event {event_id}")

                event_location_sql = """
                    INSERT INTO EventLocation (event_id, location_id, create_time)
                    VALUES (%(event_id)s, %(location_id)s, NOW() AT TIME ZONE 'UTC');
                """
                cur.execute(event_location_sql, {"event_id": event_id, "location_id": location_id})
                print(f"Transaction attempting to link event {event_id} with location {location_id}")

            # Insert each attendee into Attendance table
            if attendee_ids:
                attendance_values = []
                for attendee_id_to_add in attendee_ids:
                    attendance_values.append({
                        "event_id": event_id,
                        "person_id": attendee_id_to_add,
                        "attendance_time": datetime.now(timezone.utc)
                    })
                
                # Using executemany for multiple insertions for efficiency
                attendance_sql = """
                    INSERT INTO Attendance (event_id, person_id, attendance_time)
                    VALUES (%(event_id)s, %(person_id)s, %(attendance_time)s);
                """
                cur.executemany(attendance_sql, attendance_values)
                print(f"Transaction attempting to insert attendees {attendee_ids} for event {event_id} into Attendance")
        
        conn.commit() # Commit the entire transaction
        print(f"Successfully inserted event {event_id} with details and attendees {attendee_ids}")
        return True
    except Exception as e:
        print(f"Error inserting full event (event_id: {event_id}, attendee_ids: {attendee_ids}): {e}")
        traceback.print_exc() # Log detailed error
        conn.rollback() # Rollback on error
        return False # Indicate failure

# --- Routes ---
@app.route('/')
def home():
    """Home page: Shows all posts and the events panel."""
    all_posts = []
    all_events_attendance = []

    # Ensure database connection is attempted before loading data
    if conn is None or conn.closed:
        get_db_connection() # Try to establish connection
        if conn is None:
            flash("Database connection not available. Cannot load page data.", "danger")
            return render_template(
                'index.html',
                posts=[],
                all_events_attendance=[],
                Maps_api_key=Maps_API_KEY,
                Maps_map_id=Maps_MAP_KEY
            )

    try:
        all_posts = get_all_posts_with_author_db()
        all_events_attendance = get_all_events_with_attendees_db()
    except Exception as e:
         flash(f"Failed to load page data: {e}", "danger")
         all_posts = []
         all_events_attendance = []

    return render_template(
        'index.html',
        posts=all_posts,
        all_events_attendance=all_events_attendance,
        Maps_api_key=Maps_API_KEY,
        Maps_map_id=Maps_MAP_KEY
    )


@app.route('/person/<string:person_id>')
def person_profile(person_id):
    """Person profile page, fetching data from PostgreSQL."""
    if conn is None or conn.closed:
        get_db_connection()
        if conn is None:
            flash("Database connection not available. Cannot load profile.", "danger")
            abort(503)

    person = None # Initialize outside try block
    try:
        person = get_person_db(person_id)
        if not person:
            abort(404)

        person_posts = get_posts_by_person_db(person_id)
        friends = get_friends_db(person_id)
        all_events_attendance = get_all_events_with_attendees_db()

    except Exception as e:
         flash(f"Failed to load profile data: {e}", "danger")
         return render_template('person.html', person=person, person_posts=[], friends=[], all_events_attendance=[], error=True)


    return render_template(
        'person.html',
        person=person,
        person_posts=person_posts,
        friends=friends,
        all_events_attendance=all_events_attendance
    )

@app.route('/event/<string:event_id>')
def event_detail_page(event_id):
    """Event detail page showing description, locations on a map, and attendees."""
    if conn is None or conn.closed:
        get_db_connection()
        if conn is None:
            flash("Database connection not available. Cannot load event details.", "danger")
            abort(503)

    if not Maps_API_KEY:
        flash("Google Maps API Key is not configured. Map functionality will be disabled.", "warning")

    event_data = None
    try:
        event_data = get_event_details_with_locations_attendees_db(event_id)
        if not event_data:
            abort(404)
    except Exception as e:
        flash(f"Failed to load event data: {e}", "danger")
        print(f"Error fetching event {event_id}: {e}")
        traceback.print_exc()
        return render_template('event_detail.html', event=None, error=True, Maps_api_key=Maps_API_KEY)

    return render_template('event_detail.html', event=event_data, Maps_api_key=Maps_API_KEY)


@app.route('/api/posts', methods=['POST'])
def add_post_api():
    """
    API endpoint to add a new post.
    Expects JSON body: {"author_name": "...", "text": "...", "sentiment": "..." (optional)}
    """
    if conn is None or conn.closed:
        get_db_connection()
        if conn is None:
            return jsonify({"error": "Database connection not available"}), 503

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON payload"}), 400
    if 'author_name' not in data or 'text' not in data:
        return jsonify({"error": "Missing 'author_name' or 'text' in request body"}), 400

    author_name = data['author_name']
    text = data['text']
    sentiment = data.get('sentiment')

    if not isinstance(author_name, str) or not author_name.strip():
         return jsonify({"error": "'author_name' must be a non-empty string"}), 400
    if not isinstance(text, str) or not text.strip():
         return jsonify({"error": "'text' must be a non-empty string"}), 400
    if sentiment is not None and not isinstance(sentiment, str):
         return jsonify({"error": "'sentiment' must be a string if provided"}), 400

    try:
        author_id = get_person_by_name_db(author_name)
        if not author_id:
            return jsonify({"error": f"Author '{author_name}' not found"}), 404

        new_post_id = str(uuid.uuid4())

        success = add_post_db(
            post_id=new_post_id,
            author_id=author_id,
            text=text,
            sentiment=sentiment
        )

        if success:
            post_data = {
                "message": "Post added successfully",
                "post_id": new_post_id,
                "author_id": author_id,
                "author_name": author_name,
                "text": text,
                "sentiment": sentiment,
                "post_timestamp": datetime.now(timezone.utc).isoformat()
            }
            return jsonify(post_data), 201
        else:
            return jsonify({"error": "Failed to save post to the database"}), 500

    except ConnectionError as e:
         print(f"ConnectionError during post add: {e}")
         return jsonify({"error": "Database connection error during operation"}), 503
    except Exception as e:
        print(f"Unexpected error processing add post request: {e}")
        traceback.print_exc()
        return jsonify({"error": "An internal server error occurred"}), 500


@app.route('/api/events', methods=['POST'])
def add_event_api():
    """
    API endpoint to add a new event and its first attendee.
    Expects JSON body: {
        "event_name": "...",
        "description": "...",
        "event_date": "YYYY-MM-DDTHH:MM:SSZ" or "YYYY-MM-DDTHH:MM:SS+HH:MM",
        "locations": [...],
        "attendee_names": ["...", "..."]
    }
    """
    if conn is None or conn.closed:
        get_db_connection()
        if conn is None:
            return jsonify({"error": "Database connection not available"}), 503

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON payload"}), 400

    required_fields = ["event_name", "description", "event_date", "locations", "attendee_names"]
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    event_name = data['event_name'] 
    description = data['description']
    event_date_str = data['event_date']
    locations_data = data['locations']
    attendee_names = data['attendee_names']

    if not isinstance(event_name, str) or not event_name.strip(): 
         return jsonify({"error": "'event_name' must be a non-empty string"}), 400 
    if not isinstance(description, str):
         return jsonify({"error": "'description' must be a string"}), 400
    if not isinstance(event_date_str, str) or not event_date_str.strip():
         return jsonify({"error": "'event_date' must be a non-empty string"}), 400
    if not isinstance(attendee_names, list) or not attendee_names:
         return jsonify({"error": "'attendee_names' must be a non-empty list of strings"}), 400
    for name in attendee_names:
        if not isinstance(name, str) or not name.strip():
            return jsonify({"error": "Each name in 'attendee_names' must be a non-empty string"}), 400
    if not isinstance(locations_data, list):
        return jsonify({"error": "'locations' must be a list"}), 400
    if not locations_data: 
        return jsonify({"error": "'locations' list cannot be empty"}), 400

    for i, loc in enumerate(locations_data):
        if not isinstance(loc, dict):
            return jsonify({"error": f"Each item in 'locations' must be an object (error at index {i})"}), 400
        loc_req_fields = ["name", "latitude", "longitude"]
        missing_loc_fields = [f for f in loc_req_fields if f not in loc or not str(loc[f]).strip()]
        if missing_loc_fields:
            return jsonify({"error": f"Location at index {i} missing required fields or has empty values: {', '.join(missing_loc_fields)}"}), 400
        try:
            float(loc["latitude"])
            float(loc["longitude"])
        except (ValueError, TypeError):
            return jsonify({"error": f"Location at index {i} has invalid latitude/longitude. Must be numbers."}), 400
        if "description" in loc and not isinstance(loc["description"], str):
            return jsonify({"error": f"Location at index {i} 'description' must be a string if provided."}), 400
        if "address" in loc and not isinstance(loc["address"], str):
            return jsonify({"error": f"Location at index {i} 'address' must be a string if provided."}), 400

    try:
        event_date = datetime.fromisoformat(event_date_str.replace('Z', '+00:00'))
        if event_date.tzinfo is None or event_date.tzinfo.utcoffset(event_date) is None:
             print(f"Warning: Received naive datetime string '{event_date_str}'. Assuming UTC.")
             event_date = event_date.replace(tzinfo=timezone.utc)
        else:
             event_date = event_date.astimezone(timezone.utc)

    except ValueError as e:
        return jsonify({"error": f"Invalid timestamp format for 'event_date'. Use ISO 8601 (e.g., YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DDTHH:MM:SS+HH:MM). Details: {e}"}), 400

    try:
        attendee_ids_to_add = []
        processed_attendees_info = []
        for attendee_name_str in attendee_names:
            attendee_id = get_person_by_name_db(attendee_name_str)
            if not attendee_id:
                return jsonify({"error": f"Attendee '{attendee_name_str}' not found"}), 404
            attendee_ids_to_add.append(attendee_id)
            processed_attendees_info.append({"id": attendee_id, "name": attendee_name_str})

        if not attendee_ids_to_add:
            return jsonify({"error": "No valid attendees found"})
        
        # 2. Generate a unique ID for the new event
        new_event_id = str(uuid.uuid4())

        # 3. Insert the event and all attendees atomically
        success = add_full_event_with_details_db(
            event_id=new_event_id,
            event_name=event_name,
            description=description,
            event_date=event_date,
            locations_data=locations_data,
            attendee_ids=attendee_ids_to_add,
        )

        if success:
            # 4. Return a success response
            event_data = {
                "message": "Event and attendees added successfully",
                "event_id": new_event_id,
                "event_name": event_name,
                "description": description,
                "event_date": event_date.isoformat(), # Return in ISO format
                "locations": locations_data, # Echo back the locations provided
                "attendees": processed_attendees_info # List of {id, name}
            }
            return jsonify(event_data), 201 # 201 Created status code
        else:
            # Insertion failed (error logged in helper function)
            return jsonify({"error": "Failed to save event and attendee to the database"}), 500 # Internal Server Error

    except ConnectionError as e:
         print(f"ConnectionError during event add: {e}")
         return jsonify({"error": "Database connection error during operation"}), 503
    except Exception as e:
        # Catch other unexpected errors
        print(f"Unexpected error processing add event request: {e}")
        traceback.print_exc()
        return jsonify({"error": "An internal server error occurred"}), 500


# --- Error Handlers ---
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404 # You'll need to create 404.html

@app.errorhandler(500)
def internal_server_error(e):
     # Log the error e
     print(f"Internal Server Error: {e}")
     return render_template('500.html'), 500 # You'll need to create 500.html

@app.errorhandler(503)
def service_unavailable(e):
     # Log the error e
     print(f"Service Unavailable Error: {e}")
     return render_template('503.html'), 503 # You'll need to create 503.html


if __name__ == '__main__':
    # Check if db connection was successful before running
    # The 'conn' variable is set globally by get_db_connection
    if conn is None or conn.closed:
        print("\n--- Cannot start Flask app: PostgreSQL database connection failed during initialization. ---")
        print("--- Please check your Docker setup, database credentials, and network connectivity. ---")
    else:
        print("\n--- Starting Flask Development Server ---")
        # Use debug=True only in development! It reloads code and provides better error pages.
        # Use host='0.0.0.0' to make it accessible on your network (e.g., from a VM)
        app.run(debug=True, host=APP_HOST, port=APP_PORT)