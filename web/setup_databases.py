import os
import uuid
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateutil_parser
import time
import sys
import psycopg2
from psycopg2 import extras

# --- Configuration ---
DB_NAME = os.environ.get("POSTGRES_DB", "graphdb")
DB_USER = os.environ.get("POSTGRES_USER", "myuser")
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "mypassword")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")

def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        print("Database connection successful.")
        return conn
    except psycopg2.OperationalError as e:
        print(f"Error: Could not connect to PostgreSQL database: {e}")
        print("Please ensure the Docker container is running and accessible.")
        return None

def run_ddl_statements(conn, ddl_list, operation_description):
    """Helper function to run DDL statements and handle potential errors."""
    if not conn:
        print(f"Skipping DDL ({operation_description}) - database connection not available.")
        return False
        
    print(f"\n--- Running DDL: {operation_description} ---")
    
    # We will drop tables to ensure a clean slate on each run for this script
    drop_statements = [
        "DROP TABLE IF EXISTS EventLocation, Mention, Attendance, Friendship, Post, Event, Person, Location CASCADE;"
    ]
    
    with conn.cursor() as cur:
        try:
            print("Dropping existing tables for a clean setup...")
            for stmt in drop_statements:
                cur.execute(stmt)
            print("Existing tables dropped.")

            print("Creating new tables and indexes...")
            for i, stmt in enumerate(ddl_list):
                print(f"  Executing: {stmt.strip()}")
                cur.execute(stmt)
            
            conn.commit()
            print(f"DDL operation '{operation_description}' completed successfully.")
            return True
        except psycopg2.Error as e:
            print(f"ERROR during DDL '{operation_description}': {type(e).__name__} - {e}")
            conn.rollback() # Rollback changes on error
            return False

def setup_base_schema_and_indexes(conn):
    """Creates the base relational tables and associated indexes for PostgreSQL."""
    ddl_statements = [
        # --- 1. Base Tables ---
        """
        CREATE TABLE Location (
            location_id VARCHAR(36) PRIMARY KEY,
            name TEXT,
            description TEXT,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            address TEXT,
            create_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE Person (
            person_id VARCHAR(36) PRIMARY KEY,
            name TEXT,
            age INTEGER,
            create_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE Event (
            event_id VARCHAR(36) PRIMARY KEY,
            name TEXT,
            description TEXT,
            event_date TIMESTAMPTZ,
            create_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE Post (
            post_id VARCHAR(36) PRIMARY KEY,
            author_id VARCHAR(36) NOT NULL REFERENCES Person(person_id),
            text TEXT,
            sentiment VARCHAR(50),
            post_timestamp TIMESTAMPTZ,
            create_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE Friendship (
            person_id_a VARCHAR(36) NOT NULL REFERENCES Person(person_id),
            person_id_b VARCHAR(36) NOT NULL REFERENCES Person(person_id),
            friendship_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (person_id_a, person_id_b)
        )
        """,
        """
        CREATE TABLE Attendance (
            person_id VARCHAR(36) NOT NULL REFERENCES Person(person_id),
            event_id VARCHAR(36) NOT NULL REFERENCES Event(event_id),
            attendance_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (person_id, event_id)
        )
        """,
        """
        CREATE TABLE Mention (
            post_id VARCHAR(36) NOT NULL REFERENCES Post(post_id),
            mentioned_person_id VARCHAR(36) NOT NULL REFERENCES Person(person_id),
            mention_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (post_id, mentioned_person_id)
        )
        """,
        """
        CREATE TABLE EventLocation (
            event_id VARCHAR(36) NOT NULL REFERENCES Event(event_id),
            location_id VARCHAR(36) NOT NULL REFERENCES Location(location_id),
            create_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (event_id, location_id)
        )
        """,
        # --- 2. Indexes ---
        "CREATE INDEX ON Person(name)",
        "CREATE INDEX ON Event(event_date DESC)",
        "CREATE INDEX ON Post(post_timestamp DESC)",
        "CREATE INDEX ON Post(author_id, post_timestamp DESC)",
        "CREATE INDEX ON Friendship(person_id_b, person_id_a)",
        "CREATE INDEX ON Attendance(event_id, person_id)",
        "CREATE INDEX ON Mention(mentioned_person_id, post_id)",
        "CREATE INDEX ON EventLocation(location_id, event_id)",
    ]
    return run_ddl_statements(conn, ddl_statements, "Create Base Tables and Indexes")


# --- Data Generation / Insertion ---
def generate_uuid(): return str(uuid.uuid4())

def insert_relational_data(conn):
    """Generates and inserts the curated data into the new relational tables."""
    if not conn: 
        print("Skipping data insertion - db connection unavailable.")
        return False
    print("\n--- Defining Fixed Curated Data for Relational Insertion ---")

    people_map = {} # name -> id
    event_map = {}  # name -> id
    # post_map is not strictly needed if we don't refer back to posts by internal ref later
    locations_map = {} # (name, lat, lon) -> location_id to avoid duplicate locations

    people_rows = []
    events_rows = []
    posts_rows = []
    friendship_rows = []
    attendance_rows = []
    mention_rows = []
    locations_rows = [] # For Location table
    event_locations_rows = [] # For EventLocation table

    now = datetime.now(timezone.utc)

    # 1. Prepare People Data
    people_data = {
        "Alice": {"age": 30}, "Bob": {"age": 28}, "Charlie": {"age": 35}, "Diana": {"age": 29},
        "Ethan": {"age": 31}, "Fiona": {"age": 27}, "George": {"age": 40}, "Hannah": {"age": 33},
        "Ian": {"age": 25}, "Julia": {"age": 38}, "Kevin": {"age": 22}, "Laura": {"age": 45},
        "Mike": {"age": 36}, "Nora": {"age": 29}, "Oscar": {"age": 32}
    }
    print(f"Preparing {len(people_data)} people.")
    print(f"Preparing {len(people_data)} people.")
    for name, data in people_data.items():
        person_id = generate_uuid()
        people_map[name] = person_id
        people_rows.append((person_id, name, data.get("age")))

    # 2. Prepare Events Data
    event_data = {
        "Charity Bake Sale": {"date": (now - timedelta(days=6, hours=4)).isoformat(), "description": "Support local charities by buying delicious baked goods. All proceeds go to a good cause.", "locations": [{"name": "Community Hall - Main Room", "description": "Cakes, pies, and cookies.", "latitude": 34.052235, "longitude": -118.243683, "address": "123 Main St, Anytown"}, {"name": "Community Hall - Patio", "description": "Brownies and beverages.", "latitude": 34.052000, "longitude": -118.243500, "address": "123 Main St, Anytown (Patio)"}]},
        "Tech Meetup: Future of AI": {"date": (now - timedelta(days=5, hours=10)).isoformat(), "description": "A deep dive into the future of Artificial Intelligence, with guest speakers from leading tech companies.", "locations": [{"name": "Innovation Hub Auditorium", "description": "Main presentations and Q&A.", "latitude": 37.774929, "longitude": -122.419418, "address": "456 Tech Ave, San Francisco"}]},
        "Central Park Picnic": {"date": (now - timedelta(days=4, hours=6)).isoformat(), "description": "A casual picnic in the park. Bring your own food and blankets!", "locations": [{"name": "Great Lawn - North End", "description": "Look for the blue balloons.", "latitude": 40.782864, "longitude": -73.965355, "address": "Central Park, New York"}]},
        "Indie Film Screening": {"date": (now - timedelta(days=3, hours=12)).isoformat(), "description": "Screening of 'The Lighthouse Keeper', followed by a Q&A with the director.", "locations": [{"name": "Art House Cinema", "description": "Screen 2.", "latitude": 34.090000, "longitude": -118.360000, "address": "789 Movie Ln, Los Angeles"}]},
        "Neighborhood Potluck": {"date": (now - timedelta(days=2, hours=8)).isoformat(), "description": "Share your favorite dish with your neighbors. Fun for the whole family.", "locations": [{"name": "Greenwood Park Pavilion", "description": "Covered area near the playground.", "latitude": 47.606209, "longitude": -122.332069, "address": "101 Park Rd, Seattle"}]},
        "Escape Room: The Lost Temple": {"date": (now - timedelta(days=1, hours=5)).isoformat(), "description": "Can you solve the puzzles and escape the Lost Temple in 60 minutes?", "locations": [{"name": "Enigma Escapes", "description": "The Lost Temple room.", "latitude": 30.267153, "longitude": -97.743057, "address": "321 Puzzle Pl, Austin"}]},
        "Music in the Park Festival": {"date": (now - timedelta(days=0, hours=18)).isoformat(), "description": "A two-day music festival featuring local bands and artists across multiple stages.", "locations": [{"name": "Main Stage - Meadow", "description": "Headline acts.", "latitude": 34.0600, "longitude": -118.2500, "address": "City Park, Meadow Area"}, {"name": "Acoustic Tent - By The Lake", "description": "Intimate performances.", "latitude": 34.0615, "longitude": -118.2520, "address": "City Park, Lakeside"}, {"name": "Food Truck Alley - East Path", "description": "Various food vendors.", "latitude": 34.0590, "longitude": -118.2480, "address": "City Park, East Pathway"}]}
    }
    print(f"Preparing {len(event_data)} events.")
    for name, data in event_data.items():
        event_id = generate_uuid()
        event_map[name] = event_id
        try:
            ts_str = data.get("date")
            if not ts_str: continue
            ts = dateutil_parser.isoparse(ts_str)
            events_rows.append((event_id, name, data.get("description"), ts))

            if "locations" in data and isinstance(data["locations"], list):
                for loc_detail in data["locations"]:
                    loc_key_tuple = (loc_detail["name"], loc_detail["latitude"], loc_detail["longitude"])
                    if loc_key_tuple not in locations_map:
                        location_id = generate_uuid()
                        locations_map[loc_key_tuple] = location_id
                        locations_rows.append((
                            location_id, loc_detail["name"], loc_detail.get("description"),
                            loc_detail["latitude"], loc_detail["longitude"], loc_detail.get("address")
                        ))
                    else:
                        location_id = locations_map[loc_key_tuple]
                    event_locations_rows.append((event_id, location_id))
        except (TypeError, ValueError, OverflowError) as e:
            print(f"Warning: Could not parse date for event '{name}' (value: {data.get('date')}, error: {e}), skipping.")


    # 3. Prepare Friendships Data
    friendship_data = [("Alice", "Bob"), ("Alice", "Charlie"), ("Alice", "Hannah"), ("Alice", "Fiona"), ("Bob", "Diana"), ("Bob", "Ian"), ("Charlie", "Diana"), ("Charlie", "Ethan"), ("Diana", "Fiona"), ("Ethan", "Fiona"), ("Ethan", "George"), ("Ethan", "Ian"), ("Fiona", "Hannah"), ("Fiona", "Julia"), ("Fiona", "Ian"), ("Fiona", "Kevin"), ("Fiona", "Laura"), ("Fiona", "Mike"), ("Fiona", "Nora"), ("Fiona", "Oscar"), ("George", "Hannah"), ("George", "Ian"), ("Hannah", "Julia"), ("Ian", "Kevin"), ("Julia", "Kevin"), ("Julia", "Laura"), ("Kevin", "Mike"), ("Laura", "Nora"), ("Mike", "Oscar"), ("Nora", "Oscar")] # Removed one ("Oscar", "Nora") from original list which was a duplicate pair after sorting
    unique_friendship_pairs = set()
    print(f"Preparing friendships from {len(friendship_data)} potential pairs.")
    for p1_name, p2_name in friendship_data:
        if p1_name in people_map and p2_name in people_map:
            id1, id2 = people_map[p1_name], people_map[p2_name]
            if id1 == id2: continue
            person_id_a, person_id_b = tuple(sorted((id1, id2)))
            if (person_id_a, person_id_b) not in unique_friendship_pairs:
                friendship_rows.append((person_id_a, person_id_b))
                unique_friendship_pairs.add((person_id_a, person_id_b))


    # 4. Prepare Attendance Data
    attendance_data = [("Alice", "Charity Bake Sale"), ("Alice", "Tech Meetup: Future of AI"), ("Bob", "Charity Bake Sale"), ("Bob", "Central Park Picnic"), ("Charlie", "Tech Meetup: Future of AI"), ("Diana", "Central Park Picnic"), ("Diana", "Indie Film Screening"), ("Ethan", "Tech Meetup: Future of AI"), ("Ethan", "Neighborhood Potluck"), ("Fiona", "Central Park Picnic"), ("Fiona", "Escape Room: The Lost Temple"), ("George", "Neighborhood Potluck"), ("George", "Escape Room: The Lost Temple"), ("Hannah", "Charity Bake Sale"), ("Hannah", "Indie Film Screening"), ("Ian", "Tech Meetup: Future of AI"), ("Ian", "Neighborhood Potluck"), ("Julia", "Central Park Picnic"), ("Julia", "Escape Room: The Lost Temple"), ("Kevin", "Indie Film Screening"), ("Laura", "Neighborhood Potluck")]
    print(f"Preparing {len(attendance_data)} attendance records.")
    for person_name, event_name in attendance_data:
        if person_name in people_map and event_name in event_map:
            attendance_rows.append((people_map[person_name], event_map[event_name]))

    # 5. Prepare Posts and Mentions Data
    # --- PASTE FULL posts_data list here ---
    posts_data = [
        {"person": "Alice", "text": "Great discussion at the AI meetup! Learned so much.", "sentiment": "positive", "mention": "Ethan", "days_ago": 5, "hours_ago": 8},
        {"person": "Alice", "text": "Feeling the pressure for this project deadline. Need more coffee.", "sentiment": "negative", "mention": None, "days_ago": 1, "hours_ago": 2},
        {"person": "Alice", "text": "The bake sale was fun! Happy to support a good cause.", "sentiment": "positive", "mention": "Hannah", "days_ago": 6, "hours_ago": 2},
        {"person": "Alice", "text": "Trying out a new vegetarian chili recipe tonight.", "sentiment": "neutral", "mention": None, "days_ago": 0, "hours_ago": 3},
        {"person": "Alice", "text": "Weekend coding session in progress. Making headway!", "sentiment": "positive", "mention": None, "days_ago": 2, "hours_ago": 10},
        {"person": "Alice", "text": "Anyone read any good non-fiction lately? Looking for recommendations.", "sentiment": "neutral", "mention": "Bob", "days_ago": 8, "hours_ago": 5},
        {"person": "Alice", "text": "Reflecting on the AI ethics panel from the meetup. Important stuff.", "sentiment": "neutral", "mention": None, "days_ago": 4, "hours_ago": 15},
        {"person": "Alice", "text": "My basil plant is thriving! Small victories.", "sentiment": "positive", "mention": None, "days_ago": 3, "hours_ago": 9},
        {"person": "Alice", "text": "Ugh, debugging this legacy code is painful.", "sentiment": "negative", "mention": None, "days_ago": 7, "hours_ago": 6},
        {"person": "Alice", "text": "Planning a weekend hike if the weather holds up.", "sentiment": "positive", "mention": "Charlie", "days_ago": 1, "hours_ago": 18},
        {"person": "Alice", "text": "Discovered a great new podcast about behavioral economics.", "sentiment": "positive", "mention": None, "days_ago": 10, "hours_ago": 11},
        {"person": "Alice", "text": "Just finished 'Klara and the Sun'. Beautifully written.", "sentiment": "positive", "mention": "Fiona", "days_ago": 9, "hours_ago": 14},
        {"person": "Alice", "text": "Why is finding a good plumber so difficult?", "sentiment": "negative", "mention": None, "days_ago": 12, "hours_ago": 7},
        {"person": "Alice", "text": "Contemplating a career shift... maybe something more creative?", "sentiment": "neutral", "mention": None, "days_ago": 11, "hours_ago": 20},
        {"person": "Alice", "text": "Made some progress on my Spanish lessons today!", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 8},
        {"person": "Bob", "text": "Lovely picnic today! Perfect weather and company.", "sentiment": "positive", "mention": "Diana", "days_ago": 4, "hours_ago": 2},
        {"person": "Bob", "text": "Ugh, the traffic this morning was brutal.", "sentiment": "negative", "mention": None, "days_ago": 1, "hours_ago": 14},
        {"person": "Bob", "text": "Just finished reading 'Project Hail Mary'. Absolutely fantastic!", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 5},
        {"person": "Bob", "text": "The bake sale goodies were delicious! Thanks @Alice!", "sentiment": "positive", "mention": "Alice", "days_ago": 6, "hours_ago": 1},
        {"person": "Bob", "text": "Trying to get back into a regular workout routine.", "sentiment": "neutral", "mention": None, "days_ago": 2, "hours_ago": 12},
        {"person": "Bob", "text": "Anyone have tips for dealing with noisy upstairs neighbors?", "sentiment": "negative", "mention": None, "days_ago": 9, "hours_ago": 6},
        {"person": "Bob", "text": "Exploring the new exhibit at the art museum this weekend.", "sentiment": "positive", "mention": "Ian", "days_ago": 3, "hours_ago": 19},
        {"person": "Bob", "text": "That feeling when your code compiles on the first try!", "sentiment": "positive", "mention": None, "days_ago": 7, "hours_ago": 11},
        {"person": "Bob", "text": "Thinking about the philosophical implications of the simulation hypothesis.", "sentiment": "neutral", "mention": None, "days_ago": 11, "hours_ago": 8},
        {"person": "Bob", "text": "Made homemade pizza tonight. Success!", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 2},
        {"person": "Bob", "text": "Why does laundry pile up so fast?", "sentiment": "negative", "mention": None, "days_ago": 5, "hours_ago": 16},
        {"person": "Bob", "text": "Looking forward to the long weekend.", "sentiment": "positive", "mention": None, "days_ago": 10, "hours_ago": 9},
        {"person": "Bob", "text": "Discovered a hidden gem of a bookstore downtown.", "sentiment": "positive", "mention": None, "days_ago": 13, "hours_ago": 13},
        {"person": "Bob", "text": "Trying to learn basic Japanese. It's harder than it looks!", "sentiment": "neutral", "mention": None, "days_ago": 8, "hours_ago": 17},
        {"person": "Bob", "text": "Sometimes a simple walk in the park is all you need.", "sentiment": "positive", "mention": None, "days_ago": 1, "hours_ago": 7},
        {"person": "Charlie", "text": "Mind blown by the possibilities discussed at the AI meetup.", "sentiment": "positive", "mention": "Ethan", "days_ago": 5, "hours_ago": 7},
        {"person": "Charlie", "text": "Trying out that new Italian place downtown tonight.", "sentiment": "neutral", "mention": "Diana", "days_ago": 0, "hours_ago": 4},
        {"person": "Charlie", "text": "Finally finished the presentation deck. Relief!", "sentiment": "positive", "mention": None, "days_ago": 2, "hours_ago": 6},
        {"person": "Charlie", "text": "Weekend project: building a birdhouse.", "sentiment": "positive", "mention": None, "days_ago": 3, "hours_ago": 11},
        {"person": "Charlie", "text": "Is it just me, or are streaming service interfaces getting worse?", "sentiment": "negative", "mention": None, "days_ago": 8, "hours_ago": 9},
        {"person": "Charlie", "text": "Enjoying a quiet morning with coffee and the newspaper.", "sentiment": "positive", "mention": None, "days_ago": 1, "hours_ago": 15},
        {"person": "Charlie", "text": "Thinking about the future of remote work.", "sentiment": "neutral", "mention": None, "days_ago": 10, "hours_ago": 12},
        {"person": "Charlie", "text": "That AI meetup really sparked some ideas for my own work.", "sentiment": "positive", "mention": "Alice", "days_ago": 4, "hours_ago": 14},
        {"person": "Charlie", "text": "My attempt at sourdough bread was... interesting. Need practice.", "sentiment": "neutral", "mention": None, "days_ago": 6, "hours_ago": 10},
        {"person": "Charlie", "text": "Looking for recommendations for a good tailor.", "sentiment": "neutral", "mention": None, "days_ago": 12, "hours_ago": 8},
        {"person": "Charlie", "text": "The fall colors are starting to show. Beautiful time of year.", "sentiment": "positive", "mention": None, "days_ago": 7, "hours_ago": 13},
        {"person": "Charlie", "text": "Frustrated with customer service hold times today.", "sentiment": "negative", "mention": None, "days_ago": 1, "hours_ago": 5},
        {"person": "Charlie", "text": "Planning a visit to see family next month.", "sentiment": "positive", "mention": None, "days_ago": 9, "hours_ago": 16},
        {"person": "Charlie", "text": "Re-watching 'The Office' for the nth time. Still hilarious.", "sentiment": "positive", "mention": None, "days_ago": 13, "hours_ago": 7},
        {"person": "Charlie", "text": "Contemplating the ethics of data privacy in modern apps.", "sentiment": "neutral", "mention": None, "days_ago": 11, "hours_ago": 19},
        {"person": "Diana", "text": "That indie film was so moving. Highly recommend 'The Lighthouse Keeper'.", "sentiment": "positive", "mention": "Hannah", "days_ago": 3, "hours_ago": 10},
        {"person": "Diana", "text": "Can this rain stop already? My plants are drowning.", "sentiment": "negative", "mention": None, "days_ago": 1, "hours_ago": 10},
        {"person": "Diana", "text": "The picnic @Bob organized was lovely! So relaxing.", "sentiment": "positive", "mention": "Bob", "days_ago": 4, "hours_ago": 1},
        {"person": "Diana", "text": "Trying to declutter my apartment. It's a slow process.", "sentiment": "neutral", "mention": None, "days_ago": 2, "hours_ago": 8},
        {"person": "Diana", "text": "Excited to try the Italian place @Charlie mentioned!", "sentiment": "positive", "mention": "Charlie", "days_ago": 0, "hours_ago": 2},
        {"person": "Diana", "text": "Feeling creatively inspired after visiting the gallery.", "sentiment": "positive", "mention": None, "days_ago": 7, "hours_ago": 14},
        {"person": "Diana", "text": "My favorite coffee shop changed their beans. Not sure how I feel.", "sentiment": "negative", "mention": None, "days_ago": 9, "hours_ago": 12},
        {"person": "Diana", "text": "Working on my pottery skills. Made a slightly lopsided bowl!", "sentiment": "positive", "mention": "Fiona", "days_ago": 6, "hours_ago": 7},
        {"person": "Diana", "text": "Does anyone else find online meetings exhausting?", "sentiment": "negative", "mention": None, "days_ago": 11, "hours_ago": 6},
        {"person": "Diana", "text": "Planning a weekend trip to the coast soon.", "sentiment": "positive", "mention": None, "days_ago": 10, "hours_ago": 15},
        {"person": "Diana", "text": "Just finished a challenging puzzle. So satisfying!", "sentiment": "positive", "mention": None, "days_ago": 5, "hours_ago": 9},
        {"person": "Diana", "text": "Thinking about volunteering at the animal shelter.", "sentiment": "positive", "mention": None, "days_ago": 13, "hours_ago": 11},
        {"person": "Diana", "text": "Why are Mondays always so... Monday-ish?", "sentiment": "negative", "mention": None, "days_ago": 8, "hours_ago": 13},
        {"person": "Diana", "text": "Enjoying the simple pleasure of a good cup of tea.", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 6},
        {"person": "Diana", "text": "The film screening had such a great Q&A session afterwards.", "sentiment": "positive", "mention": "Kevin", "days_ago": 3, "hours_ago": 5},
        {"person": "Ethan", "text": "The potluck was delicious! So many amazing dishes.", "sentiment": "positive", "mention": "George", "days_ago": 2, "hours_ago": 5},
        {"person": "Ethan", "text": "Feeling stressed about my presentation tomorrow. Wish me luck!", "sentiment": "negative", "mention": None, "days_ago": 0, "hours_ago": 12},
        {"person": "Ethan", "text": "Anyone else find prompt engineering fascinating? #AI", "sentiment": "neutral", "mention": "Alice", "days_ago": 4, "hours_ago": 10},
        {"person": "Ethan", "text": "Great points at the AI meetup, @Charlie!", "sentiment": "positive", "mention": "Charlie", "days_ago": 5, "hours_ago": 6},
        {"person": "Ethan", "text": "Weekend hike was invigorating! Much needed nature time.", "sentiment": "positive", "mention": None, "days_ago": 3, "hours_ago": 14},
        {"person": "Ethan", "text": "My internet connection has been so unstable lately.", "sentiment": "negative", "mention": None, "days_ago": 1, "hours_ago": 9},
        {"person": "Ethan", "text": "Trying to learn Python for data analysis. Steep learning curve!", "sentiment": "neutral", "mention": None, "days_ago": 8, "hours_ago": 11},
        {"person": "Ethan", "text": "Nice catching up with @Ian at the potluck!", "sentiment": "positive", "mention": "Ian", "days_ago": 2, "hours_ago": 3},
        {"person": "Ethan", "text": "Experimenting with sous vide cooking. Game changer!", "sentiment": "positive", "mention": None, "days_ago": 7, "hours_ago": 7},
        {"person": "Ethan", "text": "Why do software updates always happen at the worst times?", "sentiment": "negative", "mention": None, "days_ago": 10, "hours_ago": 6},
        {"person": "Ethan", "text": "Looking forward to the tech conference next month.", "sentiment": "positive", "mention": None, "days_ago": 9, "hours_ago": 18},
        {"person": "Ethan", "text": "Discovered some amazing street art on my walk today.", "sentiment": "positive", "mention": "Fiona", "days_ago": 6, "hours_ago": 13},
        {"person": "Ethan", "text": "Feeling a bit overwhelmed with work this week.", "sentiment": "negative", "mention": None, "days_ago": 4, "hours_ago": 7},
        {"person": "Ethan", "text": "Reading 'Thinking, Fast and Slow'. Mind-bending stuff.", "sentiment": "positive", "mention": None, "days_ago": 12, "hours_ago": 15},
        {"person": "Ethan", "text": "Just booked flights for a vacation! So excited.", "sentiment": "positive", "mention": None, "days_ago": 11, "hours_ago": 10},
        {"person": "Fiona", "text": "We escaped! 'The Lost Temple' was challenging but super fun.", "sentiment": "positive", "mention": "Julia", "days_ago": 1, "hours_ago": 3},
        {"person": "Fiona", "text": "Looking forward to a relaxing weekend. Maybe some hiking?", "sentiment": "positive", "mention": "Ethan", "days_ago": 0, "hours_ago": 6},
        {"person": "Fiona", "text": "Loved the picnic vibes! Thanks for organizing, @Diana!", "sentiment": "positive", "mention": "Diana", "days_ago": 4, "hours_ago": 0},
        {"person": "Fiona", "text": "Trying my hand at watercolor painting. It's harder than it looks!", "sentiment": "neutral", "mention": "Laura", "days_ago": 2, "hours_ago": 9},
        {"person": "Fiona", "text": "Great catching up with @Hannah today!", "sentiment": "positive", "mention": "Hannah", "days_ago": 3, "hours_ago": 7},
        {"person": "Fiona", "text": "Feeling inspired after browsing a local craft fair.", "sentiment": "positive", "mention": "Nora", "days_ago": 7, "hours_ago": 10},
        {"person": "Fiona", "text": "My commute felt extra long today. Ugh.", "sentiment": "negative", "mention": None, "days_ago": 5, "hours_ago": 13},
        {"person": "Fiona", "text": "Anyone have good recommendations for fantasy novels?", "sentiment": "neutral", "mention": "Ian", "days_ago": 9, "hours_ago": 11},
        {"person": "Fiona", "text": "Made some killer guacamole for game night!", "sentiment": "positive", "mention": "Kevin", "days_ago": 6, "hours_ago": 5},
        {"person": "Fiona", "text": "Thinking about the concept of 'ikigai'. Interesting.", "sentiment": "neutral", "mention": "Mike", "days_ago": 11, "hours_ago": 14},
        {"person": "Fiona", "text": "So many emails to catch up on after the long weekend.", "sentiment": "negative", "mention": None, "days_ago": 8, "hours_ago": 15},
        {"person": "Fiona", "text": "Planning a board game night soon! Who's in? @Oscar?", "sentiment": "positive", "mention": "Oscar", "days_ago": 10, "hours_ago": 8},
        {"person": "Fiona", "text": "The escape room puzzles were clever! @George, we should try another.", "sentiment": "positive", "mention": "George", "days_ago": 1, "hours_ago": 1},
        {"person": "Fiona", "text": "Enjoying the crisp autumn air on my walk.", "sentiment": "positive", "mention": "Alice", "days_ago": 12, "hours_ago": 16},
        {"person": "Fiona", "text": "Trying to be more mindful throughout the day.", "sentiment": "neutral", "mention": None, "days_ago": 13, "hours_ago": 9},
        {"person": "George", "text": "Great turnout at the potluck! Good food, good company.", "sentiment": "positive", "mention": "Ian", "days_ago": 2, "hours_ago": 4},
        {
            "person": "Fiona",
            "text": "The 'Music in the Park' festival was amazing! The main stage had great sound, and the food truck area near the fountain was bustling. @Julia, you missed out!",
            "sentiment": "positive",
            "mention": "Julia",
            "days_ago": 0, "hours_ago": 20
        },
        {"person": "George", "text": "Tried that new artisanal coffee shop. It was... okay. Overpriced?", "sentiment": "neutral", "mention": None, "days_ago": 4, "hours_ago": 16},
        {"person": "George", "text": "The escape room was a blast! @Fiona, great suggestion!", "sentiment": "positive", "mention": "Fiona", "days_ago": 1, "hours_ago": 2},
        {"person": "George", "text": "Working on some woodworking projects this weekend.", "sentiment": "positive", "mention": None, "days_ago": 3, "hours_ago": 12},
        {"person": "George", "text": "My back is killing me after yard work yesterday.", "sentiment": "negative", "mention": None, "days_ago": 0, "hours_ago": 10},
        {"person": "George", "text": "Reading a fascinating biography about Churchill.", "sentiment": "positive", "mention": None, "days_ago": 8, "hours_ago": 7},
        {"person": "George", "text": "The potluck chili seemed to be a hit! Thanks @Ethan!", "sentiment": "positive", "mention": "Ethan", "days_ago": 2, "hours_ago": 1},
        {"person": "George", "text": "Dealing with insurance paperwork is the worst.", "sentiment": "negative", "mention": None, "days_ago": 10, "hours_ago": 11},
        {"person": "George", "text": "Looking forward to the football game tonight.", "sentiment": "positive", "mention": None, "days_ago": 6, "hours_ago": 6},
        {"person": "George", "text": "Thinking about the changing landscape of the tech industry.", "sentiment": "neutral", "mention": None, "days_ago": 11, "hours_ago": 15},
        {"person": "George", "text": "Enjoyed catching up with @Hannah at the potluck.", "sentiment": "positive", "mention": "Hannah", "days_ago": 2, "hours_ago": 2},
        {"person": "George", "text": "Why is finding decent parking downtown such a nightmare?", "sentiment": "negative", "mention": None, "days_ago": 7, "hours_ago": 9},
        {"person": "George", "text": "Planning a fishing trip for next month.", "sentiment": "positive", "mention": None, "days_ago": 13, "hours_ago": 14},
        {"person": "George", "text": "Trying to cut back on screen time. It's a challenge.", "sentiment": "neutral", "mention": None, "days_ago": 5, "hours_ago": 18},
        {"person": "George", "text": "Simple pleasures: a good cup of coffee and a quiet house.", "sentiment": "positive", "mention": None, "days_ago": 1, "hours_ago": 16},
        {"person": "Hannah", "text": "The bake sale raised a good amount for the shelter! Thanks to everyone who came.", "sentiment": "positive", "mention": "Alice", "days_ago": 6, "hours_ago": 3},
        {"person": "Hannah", "text": "My upstairs neighbors sound like they're bowling up there.", "sentiment": "negative", "mention": None, "days_ago": 1, "hours_ago": 13},
        {"person": "Hannah", "text": "That indie film @Diana recommended was excellent!", "sentiment": "positive", "mention": "Diana", "days_ago": 3, "hours_ago": 8},
        {"person": "Hannah", "text": "Spent the afternoon volunteering at the community garden.", "sentiment": "positive", "mention": None, "days_ago": 2, "hours_ago": 7},
        {"person": "Hannah", "text": "Feeling grateful for good friends. @Fiona, always great chatting!", "sentiment": "positive", "mention": "Fiona", "days_ago": 4, "hours_ago": 6},
        {"person": "Hannah", "text": "Trying to learn calligraphy. My hand hurts!", "sentiment": "neutral", "mention": None, "days_ago": 8, "hours_ago": 10},
        {"person": "Hannah", "text": "This rainy weather makes me want to curl up with a book.", "sentiment": "neutral", "mention": None, "days_ago": 0, "hours_ago": 9},
        {"person": "Hannah", "text": "Disappointed that my favorite local bakery closed down.", "sentiment": "negative", "mention": None, "days_ago": 10, "hours_ago": 7},
        {"person": "Hannah", "text": "Made some progress on the quilt I'm working on.", "sentiment": "positive", "mention": "Julia", "days_ago": 7, "hours_ago": 15},
        {"person": "Hannah", "text": "Looking forward to the farmers market this weekend.", "sentiment": "positive", "mention": None, "days_ago": 5, "hours_ago": 11},
        {"person": "Hannah", "text": "Why are printer ink cartridges so expensive?", "sentiment": "negative", "mention": None, "days_ago": 12, "hours_ago": 9},
        {"person": "Hannah", "text": "Enjoyed the thoughtful discussion after the film screening.", "sentiment": "positive", "mention": "Kevin", "days_ago": 3, "hours_ago": 4},
        {"person": "Hannah", "text": "Thinking about the importance of local community initiatives.", "sentiment": "positive", "mention": "George", "days_ago": 9, "hours_ago": 14},
        {"person": "Hannah", "text": "Just finished a great yoga session. Feeling centered.", "sentiment": "positive", "mention": None, "days_ago": 1, "hours_ago": 17},
        {"person": "Hannah", "text": "Contemplating the beauty of imperfection in handmade crafts.", "sentiment": "neutral", "mention": None, "days_ago": 11, "hours_ago": 12},
        {"person": "Ian", "text": "Still processing the AI ethics discussion from the meetup.", "sentiment": "neutral", "mention": "Alice", "days_ago": 5, "hours_ago": 5},
        {"person": "Ian", "text": "Potluck food coma is real. So worth it though.", "sentiment": "positive", "mention": "Ethan", "days_ago": 2, "hours_ago": 2},
        {"person": "Ian", "text": "Great catching up with @George at the potluck!", "sentiment": "positive", "mention": "George", "days_ago": 2, "hours_ago": 1},
        {"person": "Ian", "text": "Trying to fix a bug in my code that's driving me crazy.", "sentiment": "negative", "mention": None, "days_ago": 0, "hours_ago": 7},
        {"person": "Ian", "text": "Exploring the city's bike trails this weekend.", "sentiment": "positive", "mention": "Bob", "days_ago": 3, "hours_ago": 10},
        {"person": "Ian", "text": "Anyone else obsessed with mechanical keyboards?", "sentiment": "positive", "mention": None, "days_ago": 7, "hours_ago": 12},
        {"person": "Ian", "text": "My internet provider is having an outage. Fun.", "sentiment": "negative", "mention": None, "days_ago": 9, "hours_ago": 9},
        {"person": "Ian", "text": "Listening to some classic rock while coding.", "sentiment": "positive", "mention": None, "days_ago": 1, "hours_ago": 11},
        {"person": "Ian", "text": "Thinking about the future of open-source software.", "sentiment": "neutral", "mention": None, "days_ago": 11, "hours_ago": 13},
        {"person": "Ian", "text": "Made some surprisingly good instant ramen hacks.", "sentiment": "positive", "mention": "Kevin", "days_ago": 6, "hours_ago": 8},
        {"person": "Ian", "text": "Looking forward to the new sci-fi movie coming out.", "sentiment": "positive", "mention": None, "days_ago": 10, "hours_ago": 14},
        {"person": "Ian", "text": "Why is finding parking near the office so impossible?", "sentiment": "negative", "mention": None, "days_ago": 4, "hours_ago": 11},
        {"person": "Ian", "text": "Good chat about fantasy novels, @Fiona!", "sentiment": "positive", "mention": "Fiona", "days_ago": 8, "hours_ago": 16},
        {"person": "Ian", "text": "Trying out a new Linux distribution on an old laptop.", "sentiment": "neutral", "mention": None, "days_ago": 13, "hours_ago": 6},
        {"person": "Ian", "text": "Sometimes you just need a day to do absolutely nothing.", "sentiment": "positive", "mention": None, "days_ago": 5, "hours_ago": 15},
        {"person": "Julia", "text": "That escape room was tough! Barely made it out.", "sentiment": "positive", "mention": "Fiona", "days_ago": 1, "hours_ago": 2},
        {"person": "Julia", "text": "Making progress on learning guitar! Finally nailed the F chord.", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 11},
        {"person": "Julia", "text": "Enjoyed the picnic in the park. Such a lovely day.", "sentiment": "positive", "mention": "Bob", "days_ago": 4, "hours_ago": 3},
        {"person": "Julia", "text": "Working on a complex knitting pattern. Wish me luck!", "sentiment": "neutral", "mention": "Hannah", "days_ago": 2, "hours_ago": 10},
        {"person": "Julia", "text": "Feeling a bit under the weather today.", "sentiment": "negative", "mention": None, "days_ago": 5, "hours_ago": 7},
        {"person": "Julia", "text": "Reading 'Circe' by Madeline Miller. So captivating!", "sentiment": "positive", "mention": "Laura", "days_ago": 8, "hours_ago": 14},
        {"person": "Julia", "text": "Trying out a new Thai recipe tonight.", "sentiment": "positive", "mention": None, "days_ago": 3, "hours_ago": 6},
        {"person": "Julia", "text": "Why is adulting mostly just figuring out what to eat for dinner?", "sentiment": "negative", "mention": None, "days_ago": 10, "hours_ago": 9},
        {"person": "Julia", "text": "Looking forward to visiting the botanical gardens.", "sentiment": "positive", "mention": None, "days_ago": 7, "hours_ago": 16},
        {"person": "Julia", "text": "Thinking about the balance between work and personal life.", "sentiment": "neutral", "mention": None, "days_ago": 12, "hours_ago": 11},
        {"person": "Julia", "text": "Great teamwork in the escape room, @George!", "sentiment": "positive", "mention": "George", "days_ago": 1, "hours_ago": 0},
        {"person": "Julia", "text": "My computer decided to update right before a meeting. Perfect timing.", "sentiment": "negative", "mention": None, "days_ago": 6, "hours_ago": 12},
        {"person": "Julia", "text": "Planning a cozy weekend with books and tea.", "sentiment": "positive", "mention": "Kevin", "days_ago": 9, "hours_ago": 19},
        {"person": "Julia", "text": "Discovered some beautiful yarn at the local craft store.", "sentiment": "positive", "mention": None, "days_ago": 13, "hours_ago": 8},
        {"person": "Julia", "text": "Contemplating the beauty of a well-organized spreadsheet.", "sentiment": "neutral", "mention": None, "days_ago": 11, "hours_ago": 18},
        {"person": "Kevin", "text": "The film screening was intense. 'The Lighthouse Keeper' will stick with me.", "sentiment": "neutral", "mention": "Diana", "days_ago": 3, "hours_ago": 9},
        {"person": "Kevin", "text": "Trying a new vegetarian lasagna recipe tonight. Fingers crossed!", "sentiment": "neutral", "mention": None, "days_ago": 0, "hours_ago": 5},
        {"person": "Kevin", "text": "Finally beat that challenging level in Elden Ring!", "sentiment": "positive", "mention": None, "days_ago": 2, "hours_ago": 4},
        {"person": "Kevin", "text": "My ramen hack turned out pretty good! Thanks for the tip @Ian!", "sentiment": "positive", "mention": "Ian", "days_ago": 5, "hours_ago": 14},
        {"person": "Kevin", "text": "Feeling overwhelmed by job applications.", "sentiment": "negative", "mention": None, "days_ago": 1, "hours_ago": 8},
        {"person": "Kevin", "text": "Exploring some indie games on Steam.", "sentiment": "positive", "mention": None, "days_ago": 7, "hours_ago": 17},
        {"person": "Kevin", "text": "Why does my phone battery drain so quickly?", "sentiment": "negative", "mention": None, "days_ago": 9, "hours_ago": 13},
        {"person": "Kevin", "text": "Looking forward to game night! @Fiona, bring the snacks!", "sentiment": "positive", "mention": "Fiona", "days_ago": 4, "hours_ago": 19},
        {"person": "Kevin", "text": "Thinking about learning how to DJ.", "sentiment": "neutral", "mention": None, "days_ago": 11, "hours_ago": 11},
        {"person": "Kevin", "text": "Made some decent progress on my coding bootcamp assignments.", "sentiment": "positive", "mention": None, "days_ago": 6, "hours_ago": 14},
        {"person": "Kevin", "text": "The cost of concert tickets is getting ridiculous.", "sentiment": "negative", "mention": None, "days_ago": 10, "hours_ago": 16},
        {"person": "Kevin", "text": "Planning a movie marathon weekend.", "sentiment": "positive", "mention": "Mike", "days_ago": 8, "hours_ago": 18},
        {"person": "Kevin", "text": "Discovered a cool retro arcade downtown.", "sentiment": "positive", "mention": None, "days_ago": 13, "hours_ago": 10},
        {"person": "Kevin", "text": "Trying to understand blockchain technology. It's complex!", "sentiment": "neutral", "mention": None, "days_ago": 12, "hours_ago": 14},
        {"person": "Kevin", "text": "Sometimes you just need pizza.", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 1},
        {"person": "Laura", "text": "Such a cozy vibe at the potluck. Nice to chat with everyone.", "sentiment": "positive", "mention": "Julia", "days_ago": 2, "hours_ago": 3},
        {"person": "Laura", "text": "Finished 'Klara and the Sun'. What a beautiful, melancholic book.", "sentiment": "positive", "mention": "Alice", "days_ago": 3, "hours_ago": 16},
        {"person": "Laura", "text": "Spent the morning gardening. Feeling peaceful.", "sentiment": "positive", "mention": None, "days_ago": 1, "hours_ago": 14},
        {"person": "Laura", "text": "My favorite tea shop has a new seasonal blend!", "sentiment": "positive", "mention": "Nora", "days_ago": 4, "hours_ago": 9},
        {"person": "Laura", "text": "Dealing with a mountain of emails after being off.", "sentiment": "negative", "mention": None, "days_ago": 7, "hours_ago": 8},
        {"person": "Laura", "text": "Reading poetry by Mary Oliver. So insightful.", "sentiment": "positive", "mention": None, "days_ago": 9, "hours_ago": 15},
        {"person": "Laura", "text": "Trying out watercolor painting. @Fiona, any tips?", "sentiment": "neutral", "mention": "Fiona", "days_ago": 5, "hours_ago": 10},
        {"person": "Laura", "text": "Why is finding comfortable *and* stylish shoes so hard?", "sentiment": "negative", "mention": None, "days_ago": 11, "hours_ago": 7},
        {"person": "Laura", "text": "Looking forward to a quiet weekend of reading.", "sentiment": "positive", "mention": None, "days_ago": 6, "hours_ago": 18},
        {"person": "Laura", "text": "Thinking about the passage of time and changing seasons.", "sentiment": "neutral", "mention": None, "days_ago": 13, "hours_ago": 12},
        {"person": "Laura", "text": "Enjoyed the conversation at the potluck, @Ethan!", "sentiment": "positive", "mention": "Ethan", "days_ago": 2, "hours_ago": 0},
        {"person": "Laura", "text": "My attempts at baking macarons were a disaster.", "sentiment": "negative", "mention": None, "days_ago": 8, "hours_ago": 12},
        {"person": "Laura", "text": "Planning a visit to the library soon.", "sentiment": "positive", "mention": None, "days_ago": 10, "hours_ago": 18},
        {"person": "Laura", "text": "Discovered a charming little antique shop.", "sentiment": "positive", "mention": None, "days_ago": 12, "hours_ago": 13},
        {"person": "Laura", "text": "Contemplating the simple beauty of a well-brewed cup of tea.", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 16},
        {"person": "Mike", "text": "Thinking about taking up pottery. Seems like a relaxing hobby.", "sentiment": "positive", "mention": "Oscar", "days_ago": 3, "hours_ago": 18},
        {"person": "Mike", "text": "Weekend vibes starting now!", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 2},
        {"person": "Mike", "text": "Just finished a tough workout at the gym.", "sentiment": "positive", "mention": None, "days_ago": 1, "hours_ago": 12},
        {"person": "Mike", "text": "My fantasy football team is doing terribly.", "sentiment": "negative", "mention": None, "days_ago": 4, "hours_ago": 8},
        {"person": "Mike", "text": "Trying out a new barbecue rub recipe this weekend.", "sentiment": "positive", "mention": None, "days_ago": 2, "hours_ago": 14},
        {"person": "Mike", "text": "Anyone have recommendations for good action movies?", "sentiment": "neutral", "mention": "Kevin", "days_ago": 8, "hours_ago": 16},
        {"person": "Mike", "text": "Dealing with car repairs. Always expensive.", "sentiment": "negative", "mention": None, "days_ago": 6, "hours_ago": 9},
        {"person": "Mike", "text": "Looking forward to watching the game tonight.", "sentiment": "positive", "mention": None, "days_ago": 5, "hours_ago": 5},
        {"person": "Mike", "text": "Thinking about the strategy behind successful team management.", "sentiment": "neutral", "mention": None, "days_ago": 11, "hours_ago": 16},
        {"person": "Mike", "text": "Made some killer burgers on the grill.", "sentiment": "positive", "mention": None, "days_ago": 7, "hours_ago": 6},
        {"person": "Mike", "text": "Why are meetings scheduled right before lunch?", "sentiment": "negative", "mention": None, "days_ago": 10, "hours_ago": 13},
        {"person": "Mike", "text": "Planning a camping trip for next month.", "sentiment": "positive", "mention": "Fiona", "days_ago": 9, "hours_ago": 10},
        {"person": "Mike", "text": "Discovered a great local brewery.", "sentiment": "positive", "mention": None, "days_ago": 13, "hours_ago": 5},
        {"person": "Mike", "text": "Trying to get better at time management.", "sentiment": "neutral", "mention": None, "days_ago": 12, "hours_ago": 18},
        {"person": "Mike", "text": "Sometimes a cold beer after work is just perfect.", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 4},
        {"person": "Nora", "text": "Enjoying a quiet evening with a cup of tea and a good book.", "sentiment": "neutral", "mention": "Laura", "days_ago": 1, "hours_ago": 6},
        {"person": "Nora", "text": "Thinking of you @Laura! Hope you're having a good week.", "sentiment": "positive", "mention": "Laura", "days_ago": 3, "hours_ago": 15},
        {"person": "Nora", "text": "Spent the afternoon bird watching in the park.", "sentiment": "positive", "mention": None, "days_ago": 2, "hours_ago": 11},
        {"person": "Nora", "text": "My favorite podcast released a new episode!", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 8},
        {"person": "Nora", "text": "Feeling frustrated with a bureaucratic process.", "sentiment": "negative", "mention": None, "days_ago": 5, "hours_ago": 9},
        {"person": "Nora", "text": "Reading about sustainable living practices.", "sentiment": "positive", "mention": None, "days_ago": 8, "hours_ago": 13},
        {"person": "Nora", "text": "Trying out a new herbal tea blend.", "sentiment": "neutral", "mention": None, "days_ago": 4, "hours_ago": 12},
        {"person": "Nora", "text": "Why is junk mail still a thing?", "sentiment": "negative", "mention": None, "days_ago": 10, "hours_ago": 10},
        {"person": "Nora", "text": "Looking forward to the craft fair next weekend. @Fiona, are you going?", "sentiment": "positive", "mention": "Fiona", "days_ago": 7, "hours_ago": 18},
        {"person": "Nora", "text": "Thinking about the importance of quiet contemplation.", "sentiment": "neutral", "mention": None, "days_ago": 12, "hours_ago": 10},
        {"person": "Nora", "text": "Enjoyed the peaceful atmosphere at the library today.", "sentiment": "positive", "mention": None, "days_ago": 6, "hours_ago": 15},
        {"person": "Nora", "text": "My allergies are acting up today.", "sentiment": "negative", "mention": None, "days_ago": 1, "hours_ago": 15},
        {"person": "Nora", "text": "Planning a visit to a national park.", "sentiment": "positive", "mention": "Oscar", "days_ago": 9, "hours_ago": 17},
        {"person": "Nora", "text": "Discovered a lovely little shop selling handmade soaps.", "sentiment": "positive", "mention": None, "days_ago": 13, "hours_ago": 15},
        {"person": "Nora", "text": "Contemplating the changing colors of the leaves.", "sentiment": "neutral", "mention": None, "days_ago": 11, "hours_ago": 9},
        {"person": "Oscar", "text": "Planning a weekend getaway to the mountains. Need some fresh air!", "sentiment": "positive", "mention": "Nora", "days_ago": 1, "hours_ago": 19},
        {"person": "Oscar", "text": "Just saw @Mike's post about pottery - maybe I should join him?", "sentiment": "neutral", "mention": "Mike", "days_ago": 3, "hours_ago": 17},
        {"person": "Oscar", "text": "Finished assembling the new bookshelf. Success!", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 10},
        {"person": "Oscar", "text": "My favorite sports team lost again. Disappointing.", "sentiment": "negative", "mention": None, "days_ago": 4, "hours_ago": 5},
        {"person": "Oscar", "text": "Trying out stargazing with a new telescope.", "sentiment": "positive", "mention": None, "days_ago": 2, "hours_ago": 1},
        {"person": "Oscar", "text": "Anyone have recommendations for good historical fiction?", "sentiment": "neutral", "mention": "Laura", "days_ago": 8, "hours_ago": 19},
        {"person": "Oscar", "text": "Dealing with a leaky faucet. Plumbing is not my strong suit.", "sentiment": "negative", "mention": None, "days_ago": 6, "hours_ago": 11},
        {"person": "Oscar", "text": "Looking forward to board game night! @Fiona, what are we playing?", "sentiment": "positive", "mention": "Fiona", "days_ago": 5, "hours_ago": 12},
        {"person": "Oscar", "text": "Thinking about the impact of automation on the job market.", "sentiment": "neutral", "mention": None, "days_ago": 11, "hours_ago": 8},
        {"person": "Oscar", "text": "Made some excellent French press coffee this morning.", "sentiment": "positive", "mention": None, "days_ago": 7, "hours_ago": 19},
        {"person": "Oscar", "text": "Why are online forms always so poorly designed?", "sentiment": "negative", "mention": None, "days_ago": 10, "hours_ago": 14},
        {"person": "Oscar", "text": "Planning a hiking trip for the fall.", "sentiment": "positive", "mention": None, "days_ago": 9, "hours_ago": 13},
        {"person": "Oscar", "text": "Discovered a great podcast about unsolved mysteries.", "sentiment": "positive", "mention": None, "days_ago": 13, "hours_ago": 4},
        {"person": "Oscar", "text": "Trying to learn chess strategy. It's fascinating!", "sentiment": "neutral", "mention": None, "days_ago": 12, "hours_ago": 17},
        {"person": "Oscar", "text": "Sometimes a quiet evening at home is the best.", "sentiment": "positive", "mention": None, "days_ago": 0, "hours_ago": 3},
    ] # <-- Make sure this contains the full list
    #---------------------------------------------

    print(f"Preparing {len(posts_data)} posts and associated mentions.")
    for post_info in posts_data:
        author_name = post_info["person"]
        if author_name not in people_map: continue
        
        author_id = people_map[author_name]
        post_id = generate_uuid()
        post_ts = now - timedelta(days=post_info["days_ago"], hours=post_info["hours_ago"])
        
        posts_rows.append((
            post_id, author_id, post_info["text"], post_info["sentiment"], post_ts
        ))
        
        mentioned_name = post_info.get("mention")
        if mentioned_name and mentioned_name in people_map:
            mentioned_id = people_map[mentioned_name]
            mention_rows.append((post_id, mentioned_id))

    print(f"Prepared {len(posts_rows)} post rows, {len(mention_rows)} mention rows, {len(locations_rows)} location rows, and {len(event_locations_rows)} event-location link rows.")



   # --- Database Insertion ---
    print("\n--- Inserting Data into PostgreSQL ---")
    try:
        with conn.cursor() as cur:
            # Using executemany for efficient bulk inserts
            print(f"Inserting {len(locations_rows)} locations...")
            extras.execute_values(cur, "INSERT INTO Location (location_id, name, description, latitude, longitude, address) VALUES %s", locations_rows)
            
            print(f"Inserting {len(people_rows)} people...")
            extras.execute_values(cur, "INSERT INTO Person (person_id, name, age) VALUES %s", people_rows)
            
            print(f"Inserting {len(events_rows)} events...")
            extras.execute_values(cur, "INSERT INTO Event (event_id, name, description, event_date) VALUES %s", events_rows)
            
            print(f"Inserting {len(posts_rows)} posts...")
            extras.execute_values(cur, "INSERT INTO Post (post_id, author_id, text, sentiment, post_timestamp) VALUES %s", posts_rows)
            
            print(f"Inserting {len(friendship_rows)} friendships...")
            extras.execute_values(cur, "INSERT INTO Friendship (person_id_a, person_id_b) VALUES %s", friendship_rows)
            
            print(f"Inserting {len(attendance_rows)} attendance records...")
            extras.execute_values(cur, "INSERT INTO Attendance (person_id, event_id) VALUES %s", attendance_rows)
            
            print(f"Inserting {len(mention_rows)} mentions...")
            extras.execute_values(cur, "INSERT INTO Mention (post_id, mentioned_person_id) VALUES %s", mention_rows)

            print(f"Inserting {len(event_locations_rows)} event-location links...")
            extras.execute_values(cur, "INSERT INTO EventLocation (event_id, location_id) VALUES %s", event_locations_rows)

        conn.commit()
        print("\nData insertion completed successfully.")
        return True
    except psycopg2.Error as e:
        print(f"ERROR during data insertion: {e}")
        conn.rollback()
        return False



def main():
    """Main function to orchestrate schema setup and data insertion."""
    start_time = time.time()
    db_conn = get_db_connection()

    if not db_conn:
        sys.exit(1) # Exit if no database connection

    # Step 1: Create the relational schema
    if not setup_base_schema_and_indexes(db_conn):
        print("Halting script due to schema setup failure.")
        db_conn.close()
        sys.exit(1)
        
    # Step 2: Insert the data
    if not insert_relational_data(db_conn):
        print("Halting script due to data insertion failure.")
        db_conn.close()
        sys.exit(1)

    db_conn.close()
    end_time = time.time()
    print(f"\n--- Script finished successfully in {end_time - start_time:.2f} seconds ---")


if __name__ == "__main__":
    main()