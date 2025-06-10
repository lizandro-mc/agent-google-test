import os
import json
import pprint
import traceback
import requests
from dotenv import load_dotenv
import uuid # For generating unique session IDs

load_dotenv()

# --- Configuration for Local Orchestrator Agent ---
# Define the base URL of your local orchestrator service
ORCHESTRATOR_BASE_URL = os.environ.get('ORCHESTRATOR_BASE_URL', 'http://adk_platform:8000')

# --- Dummy Agent Proxy (Replaces Vertex AI Agent Engine) ---
class LocalOrchestratorAgentProxy:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session_id = None # To store the active session ID

    def _create_session(self, user_id: str):
        """
        Creates or updates a session for the given user.
        The session ID is generated if not already set for this proxy instance.
        """
        if not self.session_id:
            self.session_id = f"s_{uuid.uuid4().hex}" # Generate a unique session ID if not already existing

        session_url = f"{self.base_url}/apps/orchestrate/users/{user_id}/sessions/{self.session_id}"
        headers = {'Content-Type': 'application/json'}
        payload = {"state": {"initial_state": "true"}} # You can pass initial state data here

        print(f"--- Creating/Updating Session: POST {session_url} with payload {payload} ---")
        try:
            response = requests.post(session_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            session_data = response.json()
            print(f"--- Session created/updated successfully: {session_data.get('id')} ---")
            return session_data.get('id')
        except requests.exceptions.RequestException as e:
            print(f"Error creating/updating session: {e}")
            raise

    def stream_query(self, user_id: str, message: str):
        """
        Sends a message to the orchestrator's /run endpoint within a session
        and yields streaming responses.
        """
        # Ensure a session is active before running the query
        if not self.session_id:
            try:
                self._create_session(user_id)
            except Exception as e:
                yield {"content": {"parts": [{"text": f"Error: Failed to establish session: {e}"}]}}
                return

        run_url = f"{self.base_url}/run"
        headers = {'Content-Type': 'application/json'}

        # --- MODIFIED PAYLOAD STRUCTURE FOR /run ENDPOINT ---
        payload = {
            "app_name": "orchestrate", # As confirmed by your expected payload structure
            "user_id": user_id,
            "session_id": self.session_id,
            "new_message": {
                "role": "user",
                "parts": [
                    {
                        "text": message
                    }
                ]
            }
        }
        # --- END MODIFIED PAYLOAD STRUCTURE ---

        print(f"--- Sending POST request to orchestrator /run endpoint: {run_url} ---")
        print(f"--- Payload: {json.dumps(payload, indent=2)} ---")

        try:
            with requests.post(run_url, headers=headers, json=payload, stream=True, timeout=300) as response:
                response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)

                # --- FIX: Accumulate the entire response content and parse as a single JSON array ---
                full_response_content = ""
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        full_response_content += chunk.decode('utf-8')

                print(f"--- Received full raw response from /run: {full_response_content[:500]}... ---") # Log beginning for debug

                try:
                    all_events = json.loads(full_response_content)
                    if not isinstance(all_events, list):
                        print(f"Warning: Expected a list of events, but received a {type(all_events)}. Attempting to wrap it if it's a single dict.")
                        if isinstance(all_events, dict):
                            all_events = [all_events] # Wrap single dict in a list
                        else:
                            # If it's not a list or a dict, we can't process it as events
                            yield {"content": {"parts": [{"text": f"Error: Unexpected non-JSON or non-list response from orchestrator: {full_response_content}"}]}}
                            return

                    for event in all_events:
                        yield event # Yield each individual event from the parsed list
                except json.JSONDecodeError as e:
                    print(f"Error decoding full JSON response from /run: {e}")
                    yield {"content": {"parts": [{"text": f"Error: Failed to decode orchestrator response as JSON. Details: {e}. Raw: {full_response_content}"}]}}
                except Exception as e:
                    print(f"Unexpected error processing all_events: {e}")
                    yield {"content": {"parts": [{"text": f"Error: Unexpected internal processing error: {e}"}]}}

        except requests.exceptions.ConnectionError as e:
            print(f"Connection Error to orchestrator at {self.base_url}: {e}")
            yield {"content": {"parts": [{"text": f"Error: Could not connect to orchestrator: {e}"}]}}
        except requests.exceptions.Timeout:
            print(f"Timeout connecting to orchestrator at {self.base_url}")
            yield {"content": {"parts": [{"text": f"Error: Timeout connecting to orchestrator."}]}}
        except requests.exceptions.RequestException as e:
            # Enhanced error handling to print response body for 4xx/5xx errors
            error_message = f"Request Exception during call to orchestrator /run: {e}"
            print(error_message)

            if isinstance(e, requests.exceptions.HTTPError):
                try:
                    error_details = e.response.json() # Try to parse JSON error
                    print(f"Server error details (JSON): {json.dumps(error_details, indent=2)}")
                    yield {"content": {"parts": [{"text": f"Error: Request to orchestrator /run failed: {e}. Details: {json.dumps(error_details)}"}]}}
                except (json.JSONDecodeError, AttributeError):
                    # If not JSON, print raw text
                    print(f"Server error details (raw text): {e.response.text}")
                    yield {"content": {"parts": [{"text": f"Error: Request to orchestrator /run failed: {e}. Details: {e.response.text}"}]}}
            else:
                yield {"content": {"parts": [{"text": f"Error: Request to orchestrator /run failed: {e}"}]}}
        except Exception as e:
            print(f"Unexpected error in LocalOrchestratorAgentProxy stream_query: {e}")
            traceback.print_exc()
            yield {"content": {"parts": [{"text": f"Error: Unexpected error calling orchestrator: {e}"}]}}


# Initialize your local agent proxy
local_agent_proxy = LocalOrchestratorAgentProxy(ORCHESTRATOR_BASE_URL)

def call_agent_for_plan(user_name, planned_date, location_n_perference, selected_friend_names_list):
    user_id = str(user_name)

    yield {"type": "thought", "data": f"--- IntrovertAlly Agent Call Initiated (Local Orchestrator) ---"}
    yield {"type": "thought", "data": f"User: {user_name}"}
    yield {"type": "thought", "data": f"Planned Date: {planned_date}"}
    yield {"type": "thought", "data": f"Location/Preference: {location_n_perference}"}
    yield {"type": "thought", "data": f"Selected Friends: {', '.join(selected_friend_names_list)}"}
    yield {"type": "thought", "data": f"Initiating plan for {user_name} on {planned_date} regarding '{location_n_perference}' with friends: {', '.join(selected_friend_names_list)}."}

    selected_friend_names_str = ', '.join(selected_friend_names_list)

    # Constructing an example for the prompt, e.g., ["Alice", "Bob"]
    friends_list_example_for_prompt = json.dumps(selected_friend_names_list)

    prompt_message = f"""Plan a personalized night out for {user_name} with friends {selected_friend_names_str} on {planned_date}, with the location or preference being "{location_n_perference}".

    Analyze friend interests (if possible, use Instavibe profiles or summarized interests) to create a tailored plan. Ensure the plan includes the date {planned_date}.

    Output the entire plan in a SINGLE, COMPLETE JSON object with the following structure. **CRITICAL: The FINAL RESPONSE MUST BE ONLY THIS JSON. If any fields are missing or unavailable, INVENT them appropriately to complete the JSON structure. Do not return any conversational text or explanations. Just the raw, valid JSON.**

    {{
    "friends_name_list": {friends_list_example_for_prompt}, // Array of strings: {selected_friend_names_str}
    "event_name": "string",        // Concise, descriptive name for the event (e.g., "{selected_friend_names_str}'s Night Out")
    "event_date": "{planned_date}", // Date in ISO 8601 format.
    "event_description": "string", // Engaging summary of planned activities.
    "locations_and_activities": [  // Array detailing each step of the plan.
        {{
        "name": "string",          // Name of the place, venue, or activity.
        "latitude": 12.345,        // Approximate latitude (e.g., 34.0522) or null if not available.
        "longitude": -67.890,      // Approximate longitude (e.g., -118.2437) or null if not available.
        "address": "string or null", // Physical address if available, otherwise null.
        "description": "string"    // Description of this location/activity.
        }}
        // Add more location/activity objects as needed.
    ],
    "post_to_go_out": "string"     // Short, catchy, and exciting text message from {user_name} to invite friends.
    }}
    """

    print(f"--- Sending Prompt to Agent ---")
    print(prompt_message)
    yield {"type": "thought", "data": f"Sending detailed planning prompt to local orchestrator agent for {user_name}'s event."}

    accumulated_json_str = ""

    yield {"type": "thought", "data": f"--- Local Agent Response Stream Starting ---"}
    try:
        # Use the local_agent_proxy instead of agent_engine
        for event_idx, event in enumerate(
            local_agent_proxy.stream_query(
                user_id=user_id,
                message=prompt_message,
            )
        ):
            print(f"\n--- Event {event_idx} Received from Local Agent ---") # Console
            pprint.pprint(event) # Console
            try:
                # --- MODIFIED: Handle 'content' being a list or a dict ---
                content_data = event.get('content') # Get content, could be dict or list

                parts = []
                if isinstance(content_data, dict):
                    parts = content_data.get('parts', [])
                elif isinstance(content_data, list):
                    # If 'content' itself is the list of parts, use it directly
                    parts = content_data
                elif content_data is not None:
                    # If content_data is not a dict, list, or None, convert it to a single part list
                    # This catches cases where 'content' is just a string directly
                    parts = [{"text": str(content_data)}]

                if not parts:
                    pass # Avoid too much noise for empty events

                for part_idx, part in enumerate(parts):
                    if isinstance(part, dict):
                        text = part.get('text')
                        if text:
                            yield {"type": "thought", "data": f"Agent: \"{text}\""}
                            accumulated_json_str += text
                        else:
                            # If your local agent returns tool calls, you'd process them here
                            function_call = part.get('functionCall') # Corrected key for function calls
                            function_response = part.get('functionResponse') # Corrected key for function responses

                            if function_call:
                                yield {"type": "thought", "data": f"Agent is considering using a tool: {function_call.get('name', 'Unnamed tool')} with args: {function_call.get('args', {})}"}
                            if function_response:
                                yield {"type": "thought", "data": f"Agent received output from tool '{function_response.get('name', 'Unnamed tool')}': {function_response.get('response', {})}"}
                    elif isinstance(part, str): # Handle cases where a part is just a string
                        yield {"type": "thought", "data": f"Agent: \"{part}\""}
                        accumulated_json_str += part
                    else:
                        yield {"type": "thought", "data": f"Warning: Unrecognized part type at event {event_idx}, part {part_idx}: {type(part)} - {part}"}
            except Exception as e_inner:
                yield {"type": "thought", "data": f"Error processing agent event part {event_idx}: {str(e_inner)} - Raw Event: {event}"}

    except Exception as e_outer:
        yield {"type": "thought", "data": f"Critical error during local agent stream query: {str(e_outer)}"}
        yield {"type": "error", "data": {"message": f"Error during local agent interaction: {str(e_outer)}", "raw_output": accumulated_json_str}}
        return # Stop generation

    yield {"type": "thought", "data": f"--- End of Local Agent Response Stream ---"}

    # Attempt to extract JSON if it's wrapped in markdown
    if "```json" in accumulated_json_str:
        print("Detected JSON in markdown code block. Extracting...")

        try:
            # Extract content between ```json and ```
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
            yield {"type": "thought", "data": f"Failed to parse the local agent's output as a valid plan. Error: {e}"}
            yield {"type": "thought", "data": f"Raw output received: {accumulated_json_str}"}
            yield {"type": "error", "data": {"message": f"JSON parsing error: {e}", "raw_output": accumulated_json_str}}
    else:
        yield {"type": "thought", "data": "Local agent did not provide any text content in its response."}
        yield {"type": "error", "data": {"message": "Local agent returned no content.", "raw_output": ""}}


def post_plan_event(user_name, confirmed_plan, edited_invite_message, agent_session_user_id): # Added agent_session_user_id back
    """
    Delegates event and post creation to the local orchestrator agent.
    Yields 'thought' events for logging.
    """
    user_id = str(agent_session_user_id) # Use the provided agent_session_user_id for consistency with the orchestrator session
    
    yield {"type": "thought", "data": f"--- Post Plan Event Agent Call Initiated (Local Orchestrator) ---"}
    yield {"type": "thought", "data": f"User performing action: {user_name}"}
    yield {"type": "thought", "data": f"Received Confirmed Plan (event_name): {confirmed_plan.get('event_name', 'N/A')}"}
    yield {"type": "thought", "data": f"Received Invite Message: {edited_invite_message[:100]}..."} # Log a preview
    yield {"type": "thought", "data": f"Initiating process to post event and invite for {user_name} via local orchestrator."}

    prompt_message = f"""
    You are an Orchestrator assistant for the Instavibe platform. User '{user_name}' has finalized an event plan and wants to:
    1. Create the event on Instavibe.
    2. Create an invite post for this event on Instavibe.

    You have tools like `list_remote_agents` to discover available specialized agents and `send_task(agent_name: str, message: str)` to delegate tasks to them.
    Your primary role is to understand the user's overall goal, identify the necessary steps, select the most appropriate remote agent(s) for those steps, and then send them clear instructions.

    Confirmed Plan:
    ```json
    {json.dumps(confirmed_plan, indent=2)}
    ```

    Invite Message (this is the exact text for the post content):
    "{edited_invite_message}"

    Your explicit tasks are, in this exact order:

    TASK 1: Create the Event on Instavibe.
    - First, identify a suitable remote agent that is capable of creating events on the Instavibe platform. You should use your `list_remote_agents` tool if you need to refresh your knowledge of available agents and their capabilities.
    - Once you have selected an appropriate agent, you MUST use your tool to instruct that agent to create the event.
    - The `message` you send to the agent for this task should be a clear, natural language instruction. This message MUST include all necessary details for event creation, derived from the "Confirmed Plan" JSON:
        - Event Name: "{confirmed_plan.get('event_name', 'Unnamed Event')}"
        - Event Description: "{confirmed_plan.get('event_description', 'No description provided.')}"
        - Event Date: "{confirmed_plan.get('event_date', 'MISSING_EVENT_DATE_IN_PLAN')}" (ensure this is in a standard date/time format like ISO 8601)
        - Locations: {json.dumps(confirmed_plan.get('locations_and_activities', []))} (describe these locations clearly to the agent)
        - Attendees: {json.dumps(list(set(confirmed_plan.get('friends_name_list', []) + [user_name])))} (this list includes the user '{user_name}' and their friends)
    - Narrate your thought process: which agent you are selecting (or your criteria if you can't name it), and the natural language message you are formulating for the tool to create the event.
    - After the tool call is complete, briefly acknowledge its success based on the tool's response.

    TASK 2: Create the Invite Post on Instavibe.
    - Only after TASK 1 (event creation) is confirmed as successful, you MUST use your tool again.
    - The `message` you send to the agent for this task should be a clear, natural language instruction to create a post. This message MUST include:
        - The author of the post: "{user_name}"
        - The content of the post: The "Invite Message" provided above ("{edited_invite_message}")
        - An instruction to associate this post with the event created in TASK 1 (e.g., by referencing its name: "{confirmed_plan.get('event_name', 'Unnamed Event')}").
        - Indicate the sentiment is "positive" as it's an invitation.
    - Narrate the natural language message you are formulating for the `send_task` tool to create the post.
    - After the `send_task` tool call is (simulated as) complete, briefly acknowledge its success.

    IMPORTANT INSTRUCTIONS FOR YOUR BEHAVIOR:
    - Your primary role here is to orchestrate these two actions by selecting an appropriate remote agent and sending it clear, natural language instructions via your tool.
    - Your responses during this process should be a stream of consciousness, primarily narrating your agent selection (if applicable), the formulation of your natural language messages for , and their outcomes.
    - Do NOT output any JSON yourself. Your output must be plain text only, describing your actions.
    - Conclude with a single, friendly success message confirming that you have (simulated) instructing the remote agent to create both the event and the post. For example: "Alright, I've instructed the appropriate Instavibe agent to create the event '{confirmed_plan.get('event_name', 'Unnamed Event')}' and to make the invite post for {user_name}!"
    """

    yield {"type": "thought", "data": f"Sending posting instructions to local agent for {user_name}'s event."}
    print(f"prompt_message: {prompt_message}")

    accumulated_response_text = ""

    try:
        # Use the local_agent_proxy instead of agent_engine
        for event_idx, event in enumerate(
            local_agent_proxy.stream_query(
                user_id=user_id, # Use the user_id derived from agent_session_user_id
                message=prompt_message,
            )
        ):
            print(f"\n--- Post Event - Local Agent Event {event_idx} Received ---") # Console
            pprint.pprint(event) # Console
            try:
                # --- MODIFIED: Handle 'content' being a list or a dict ---
                content_data = event.get('content') # Get content, could be dict or list

                parts = []
                if isinstance(content_data, dict):
                    parts = content_data.get('parts', [])
                elif isinstance(content_data, list):
                    # If 'content' itself is the list of parts, use it directly
                    parts = content_data
                elif content_data is not None:
                    # If content_data is not a dict, list, or None, convert it to a single part list
                    # This catches cases where 'content' is just a string directly
                    parts = [{"text": str(content_data)}]

                for part_idx, part in enumerate(parts):
                    if isinstance(part, dict):
                        text = part.get('text')
                        if text:
                            yield {"type": "thought", "data": f"Agent: \"{text}\""}
                            accumulated_response_text += text
                        # Handle tool calls and responses if your orchestrator sends them during this phase
                        function_call = part.get('functionCall')
                        function_response = part.get('functionResponse')

                        if function_call:
                            yield {"type": "thought", "data": f"Agent is considering using a tool for posting: {function_call.get('name', 'Unnamed tool')}."}
                        if function_response:
                            yield {"type": "thought", "data": f"Agent received output from tool '{function_response.get('name', 'Unnamed tool')}' during posting."}
                    elif isinstance(part, str): # Handle cases where a part is just a string
                        yield {"type": "thought", "data": f"Agent: \"{part}\""}
                        accumulated_response_text += part
                    else:
                        yield {"type": "thought", "data": f"Warning: Unrecognized part type at event {event_idx}, part {part_idx} during posting: {type(part)} - {part}"}
            except Exception as e_inner:
                yield {"type": "thought", "data": f"Error processing agent event part {event_idx} during posting: {str(e_inner)} - Raw Event: {event}"}

    except Exception as e_outer:
        yield {"type": "thought", "data": f"Critical error during local agent stream query for posting: {str(e_outer)}"}
        yield {"type": "error", "data": {"message": f"Error during local agent interaction for posting: {str(e_outer)}", "raw_output": accumulated_response_text}}
        return # Stop generation if there's a major error

    yield {"type": "thought", "data": f"--- End of Local Agent Response Stream for Posting ---"}
    yield {"type": "posting_finished", "data": {"success": True, "message": "Local agent has finished processing the event and post creation."}}