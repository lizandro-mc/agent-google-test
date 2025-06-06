# main.py

import os
import json
import functions_framework
from flask import request, jsonify
from vertexai import agent_engines
from dotenv import load_dotenv
import pprint

# Load environment variables (useful for local testing)
load_dotenv()

# --- INITIAL AGENT CONFIGURATION ---
try:
    ORCHESTRATE_AGENT_ID = os.environ.get('ORCHESTRATE_AGENT_ID')
    if not ORCHESTRATE_AGENT_ID:
        raise ValueError("The ORCHESTRATE_AGENT_ID environment variable is not set.")
    agent_engine = agent_engines.get(ORCHESTRATE_AGENT_ID)
except Exception as e:
    print(f"CRITICAL ERROR initializing agent: {e}")
    agent_engine = None

# ===============================================================
# PASTE YOUR TWO ORIGINAL FUNCTIONS HERE (UNCHANGED)
# call_agent_for_plan(...) and post_plan_event(...)
# ===============================================================
def call_agent_for_plan(user_name, planned_date, location_n_perference, selected_friend_names_list):
    # ... (Paste your full, unchanged call_agent_for_plan function here)
    # ... (The code is long, so I'm omitting it here for clarity, but YOU MUST paste it)
    user_id = str(user_name)
    yield {"type": "thought", "data": f"--- IntrovertAlly Agent Call Initiated ---"}
    # ... the rest of your function ...
    
def post_plan_event(user_name, confirmed_plan, edited_invite_message, agent_session_user_id):
    # ... (Paste your full, unchanged post_plan_event function here)
    # ... (The code is long, so I'm omitting it here for clarity, but YOU MUST paste it)
    yield {"type": "thought", "data": f"--- Post Plan Event Agent Call Initiated ---"}
    # ... the rest of your function ...

# ===============================================================
# API ENTRY POINT (HTTP Cloud Function)
# ===============================================================

@functions_framework.http
def api_handler(req):
    """
    Main function that routes requests to the /plan or /post endpoints.
    Returns a single JSON response at the end.
    """
    # CORS configuration to allow your frontend to connect
    headers = {
        'Access-Control-Allow-Origin': '*', # In production, change this to your domain
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    }

    if req.method == 'OPTIONS':
        return ('', 204, headers)

    if agent_engine is None:
        response = jsonify({"error": "The server could not initialize the AI agent."})
        response.status_code = 500
        response.headers.extend(headers)
        return response

    # --- API ROUTER ---
    path = req.path
    if path == '/plan':
        response = handle_plan_request(req)
    elif path == '/post':
        response = handle_post_request(req)
    else:
        response = jsonify({"error": "Endpoint not found. Use /plan or /post."})
        response.status_code = 404
    
    response.headers.extend(headers)
    return response

def handle_plan_request(req):
    """
    Handles /plan, waits for the final result, and returns a single JSON.
    """
    if req.method != 'POST':
        return jsonify({"error": "POST method is required."}), 405
    
    data = request.get_json()
    # ... (data extraction and validation same as before)
    user_name = data.get('user_name')
    # ... (rest of the variables)

    # Call your function and look for the final result
    final_result = None
    error_result = None
    for event in call_agent_for_plan(user_name, data.get('planned_date'), data.get('location_n_perference'), data.get('selected_friend_names_list', [])):
        if event.get('type') == 'plan_complete':
            final_result = event.get('data')
            break  # We found the result, we can stop
        elif event.get('type') == 'error':
            error_result = event.get('data')
            break
            
    if final_result:
        return jsonify(final_result)
    elif error_result:
        return jsonify({"error": "The agent encountered an error", "details": error_result}), 500
    else:
        return jsonify({"error": "The agent did not return a complete plan."}), 500

def handle_post_request(req):
    """
    Handles /post, waits for the final result, and returns a single JSON.
    """
    if req.method != 'POST':
        return jsonify({"error": "POST method is required."}), 405
        
    data = request.get_json()
    # ... (data extraction and validation same as before)

    # Call your function and look for the final result
    final_result = None
    error_result = None
    for event in post_plan_event(data.get('user_name'), data.get('confirmed_plan'), data.get('edited_invite_message'), data.get('agent_session_user_id')):
        if event.get('type') == 'posting_finished':
            final_result = event.get('data')
            break
        elif event.get('type') == 'error':
            error_result = event.get('data')
            break
            
    if final_result:
        return jsonify(final_result)
    elif error_result:
        return jsonify({"error": "The agent encountered an error while posting", "details": error_result}), 500
    else:
        return jsonify({"error": "The agent did not confirm the posting was finished."}), 500