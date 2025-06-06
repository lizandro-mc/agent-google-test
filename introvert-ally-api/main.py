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
# AGENT-CALLING LOGIC FUNCTIONS
# ===============================================================

def call_agent_for_plan(user_name, planned_date, location_n_perference, selected_friend_names_list):
    """
    Builds a prompt and calls the agent to generate an event plan.
    This is a generator function that yields progress events.
    """
    user_id = str(user_name)
    
    yield {"type": "thought", "data": f"--- IntrovertAlly Agent Call Initiated ---"}
    yield {"type": "thought", "data": f"Session ID for this run: {user_id}"}
    yield {"type": "thought", "data": f"User: {user_name}"}
    yield {"type": "thought", "data": f"Planned Date: {planned_date}"}
    yield {"type": "thought", "data": f"Location/Preference: {location_n_perference}"}
    yield {"type": "thought", "data": f"Selected Friends: {', '.join(selected_friend_names_list)}"}
    yield {"type": "thought", "data": f"Initiating plan for {user_name} on {planned_date} regarding '{location_n_perference}' with friends: {', '.join(selected_friend_names_list)}."}

    selected_friend_names_str = ', '.join(selected_friend_names_list)
    friends_list_example_for_prompt = json.dumps(selected_friend_names_list)

    prompt_message = f"""
    Plan a personalized night out for {user_name} with friends {selected_friend_names_str} on {planned_date}, with the location or preference being "{location_n_perference}".

    Analyze friend interests (if possible, use Instavibe profiles or summarized interests) to create a tailored plan. Ensure the plan includes the date {planned_date}.

    Output the entire plan in a SINGLE, COMPLETE JSON object with the following structure. **CRITICAL: THE FINAL RESPONSE MUST BE ONLY THIS JSON. If any fields are missing or unavailable, INVENT them appropriately to complete the JSON structure. Do not return any conversational text or explanations. Just the raw, valid JSON.**

    {{
      "friends_name_list": {friends_list_example_for_prompt},
      "event_name": "string",
      "event_date": "{planned_date}",
      "event_description": "string",
      "locations_and_activities": [
        {{
          "name": "string",
          "latitude": 12.345,
          "longitude": -67.890,
          "address": "string or null",
          "description": "string"
        }}
      ],
      "post_to_go_out": "string"
    }}
    """

    print(f"--- Sending Prompt to Agent ---") 
    print(prompt_message) 
    yield {"type": "thought", "data": f"Sending detailed planning prompt to agent for {user_name}'s event."}

    accumulated_json_str = ""

    yield {"type": "thought", "data": f"--- Agent Response Stream Starting ---"}
    try:
        for event_idx, event in enumerate(agent_engine.stream_query(user_id=user_id, message=prompt_message)):
            print(f"\n--- Event {event_idx} Received ---")
            pprint.pprint(event)
            try:
                content = event.get('content', {})
                parts = content.get('parts', [])
                
                for part_idx, part in enumerate(parts):
                    if isinstance(part, dict):
                        text = part.get('text')
                        if text:
                            yield {"type": "thought", "data": f"Agent: \"{text}\""}
                            accumulated_json_str += text
                        else:
                            tool_code = part.get('tool_code')
                            if tool_code:
                                yield {"type": "thought", "data": f"Agent is considering using a tool: {tool_code.get('name', 'Unnamed tool')}."}
            except Exception as e_inner:
                yield {"type": "thought", "data": f"Error processing agent event part {event_idx}: {str(e_inner)}"}

    except Exception as e_outer:
        yield {"type": "thought", "data": f"Critical error during agent stream query: {str(e_outer)}"}
        yield {"type": "error", "data": {"message": f"Error during agent interaction: {str(e_outer)}", "raw_output": accumulated_json_str}}
        return

    yield {"type": "thought", "data": f"--- End of Agent Response Stream ---"}

    if "```json" in accumulated_json_str:
        print("Detected JSON in markdown code block. Extracting...")
        try:
            json_block = accumulated_json_str.split("```json", 1)[1].rsplit("```", 1)[0].strip()
            accumulated_json_str = json_block
            print(f"Extracted JSON block: {accumulated_json_str}") 
        except IndexError:
            yield {"type": "thought", "data": "Could not extract JSON from markdown block, will attempt to parse the full response."}

    if accumulated_json_str:
        try:
            final_result_json = json.loads(accumulated_json_str)
            yield {"type": "plan_complete", "data": final_result_json}
        except json.JSONDecodeError as e:
            yield {"type": "thought", "data": f"Failed to parse the agent's output as a valid plan. Error: {e}"}
            yield {"type": "thought", "data": f"Raw output received: {accumulated_json_str}"}
            yield {"type": "error", "data": {"message": f"JSON parsing error: {e}", "raw_output": accumulated_json_str}}
    else:
        yield {"type": "thought", "data": "Agent did not provide any text content in its response."}
        yield {"type": "error", "data": {"message": "Agent returned no content.", "raw_output": ""}}

def post_plan_event(user_name, confirmed_plan, edited_invite_message, agent_session_user_id):
    """
    Builds a prompt and calls the agent to orchestrate posting an event.
    This is a generator function that yields progress events.
    """
    yield {"type": "thought", "data": f"--- Post Plan Event Agent Call Initiated ---"}
    yield {"type": "thought", "data": f"Agent Session ID for this run: {agent_session_user_id}"}
    yield {"type": "thought", "data": f"User performing action: {user_name}"}
    yield {"type": "thought", "data": f"Received Confirmed Plan (event_name): {confirmed_plan.get('event_name', 'N/A')}"}
    yield {"type": "thought", "data": f"Received Invite Message: {edited_invite_message[:100]}..."}
    yield {"type": "thought", "data": f"Initiating process to post event and invite for {user_name}."}

    prompt_message = f"""
    You are an Orchestrator assistant for the Instavibe platform. User '{user_name}' has finalized an event plan and wants to:
    1. Create the event on Instavibe.
    2. Create an invite post for this event on Instavibe.
    Your primary role is to understand the user's goal, identify steps, select appropriate remote agent(s), and send them clear instructions using your tools.

    Confirmed Plan:
    ```json
    {json.dumps(confirmed_plan, indent=2)}
    ```

    Invite Message (this is the exact text for the post content):
    "{edited_invite_message}"

    Your explicit tasks are, in this exact order:

    TASK 1: Create the Event on Instavibe.
    - Identify a suitable remote agent for creating events.
    - Use your tool to instruct that agent to create the event.
    - The `message` you send to the agent must be clear natural language and include all necessary details from the "Confirmed Plan" JSON.
    - Narrate your thought process and the message you are formulating for the tool.

    TASK 2: Create the Invite Post on Instavibe.
    - Only after TASK 1 is confirmed successful, use your tool again.
    - The `message` you send to the agent must be a clear instruction to create a post, including the author ('{user_name}'), the content ("{edited_invite_message}"), and an instruction to associate it with the new event.
    - Narrate the message you are formulating for the tool.

    IMPORTANT INSTRUCTIONS:
    - Your primary role is orchestration.
    - Your responses should be a stream of consciousness, narrating your actions.
    - Do NOT output any JSON yourself. Your output must be plain text only.
    - Conclude with a single, friendly success message confirming the tasks are done.
    """

    yield {"type": "thought", "data": f"Sending posting instructions to agent for {user_name}'s event."}
    print(f"prompt_message: {prompt_message}")
    
    accumulated_response_text = ""

    try:
        for event_idx, event in enumerate(agent_engine.stream_query(user_id=agent_session_user_id, message=prompt_message)):
            print(f"\n--- Post Event - Agent Event {event_idx} Received ---")
            pprint.pprint(event)
            try:
                content = event.get('content', {})
                parts = content.get('parts', [])
                for part_idx, part in enumerate(parts):
                    if isinstance(part, dict):
                        text = part.get('text')
                        if text:
                            yield {"type": "thought", "data": f"Agent: \"{text}\""}
                            accumulated_response_text += text
            except Exception as e_inner:
                yield {"type": "thought", "data": f"Error processing agent event part {event_idx} during posting: {str(e_inner)}"}

    except Exception as e_outer:
        yield {"type": "thought", "data": f"Critical error during agent stream query for posting: {str(e_outer)}"}
        yield {"type": "error", "data": {"message": f"Error during agent interaction for posting: {str(e_outer)}", "raw_output": accumulated_response_text}}
        return

    yield {"type": "thought", "data": f"--- End of Agent Response Stream for Posting ---"}
    yield {"type": "posting_finished", "data": {"success": True, "message": "Agent has finished processing the event and post creation."}}

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
        'Access-control-allow-headers': 'Content-Type',
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
    user_name = data.get('user_name')
    planned_date = data.get('planned_date')
    location_n_perference = data.get('location_n_perference')
    selected_friend_names_list = data.get('selected_friend_names_list', [])

    if not all([user_name, planned_date, location_n_perference]):
        return jsonify({"error": "Missing required parameters."}), 400

    final_result = None
    error_result = None
    for event in call_agent_for_plan(user_name, planned_date, location_n_perference, selected_friend_names_list):
        if event.get('type') == 'plan_complete':
            final_result = event.get('data')
            break
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
    user_name = data.get('user_name')
    confirmed_plan = data.get('confirmed_plan')
    edited_invite_message = data.get('edited_invite_message')
    agent_session_user_id = data.get('agent_session_user_id')

    if not all([user_name, confirmed_plan, edited_invite_message, agent_session_user_id]):
        return jsonify({"error": "Missing required parameters."}), 400

    final_result = None
    error_result = None
    for event in post_plan_event(user_name, confirmed_plan, edited_invite_message, agent_session_user_id):
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