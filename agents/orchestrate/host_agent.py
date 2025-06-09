import sys
import asyncio
import functools
import json
import uuid
import threading
from typing import List, Optional, Callable


from google.genai import types
import base64

from google.adk import Agent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.tool_context import ToolContext
from remote.remote_agent_connection import (
    RemoteAgentConnections,
    TaskUpdateCallback
)
from common.client import A2ACardResolver
from common.types import (
    AgentCard,
    Message,
    TaskState,
    Task,
    TaskSendParams,
    TextPart,
    DataPart,
    Part,
    TaskStatusUpdateEvent,
)


class HostAgent:
  """The orchestrate agent.

  This is the agent responsible for choosing which remote agents to send
  tasks to and coordinate their work.
  """

  def __init__(
      self,
      remote_agent_addresses: List[str],
      task_callback: TaskUpdateCallback | None = None
  ):
    self.task_callback = task_callback
    self.remote_agent_connections: dict[str, RemoteAgentConnections] = {}
    self.cards: dict[str, AgentCard] = {}
    # Attempt to resolve agent cards during initialization
    for address in remote_agent_addresses:
      try:
        card_resolver = A2ACardResolver(address)
        card = card_resolver.get_agent_card()
        remote_connection = RemoteAgentConnections(card)
        self.remote_agent_connections[card.name] = remote_connection
        self.cards[card.name] = card
        print(f"Successfully connected to remote agent: {card.name} at {address}")
      except Exception as e:
        print(f"Warning: Could not connect to remote agent at {address}. Error: {e}", file=sys.stderr)
    
    agent_info = []
    # Only list agents for which we successfully got a card
    for ra_card in self.cards.values():
      # Only include name and description for the LLM's understanding
      agent_info.append(json.dumps({"name": ra_card.name, "description": ra_card.description}))
    self.agents = '\n'.join(agent_info)
    if not self.agents:
        print("Warning: No remote agents could be resolved during initialization.", file=sys.stderr)
        self.agents = "No remote agents currently available."

  def register_agent_card(self, card: AgentCard):
    """Registers a new remote agent card, adding it to the list of available agents."""
    remote_connection = RemoteAgentConnections(card)
    self.remote_agent_connections[card.name] = remote_connection
    self.cards[card.name] = card
    agent_info = []
    for ra in self.list_remote_agents():
      agent_info.append(json.dumps(ra))
    self.agents = '\n'.join(agent_info)

  def create_agent(self) -> Agent:
    """Creates the ADK Agent instance for the orchestrator."""
    return Agent(
        model="gemini-2.0-flash",
        name="orchestrate_agent",
        instruction=self.root_instruction,
        before_model_callback=self.before_model_callback,
        description=(
            "This agent orchestrates the decomposition of the user request into"
            " tasks that can be performed by the child agents."
        ),
        tools=[
            self.list_remote_agents,
            self.send_task,
        ],
    )

  def root_instruction(self, context: ReadonlyContext) -> str:
        """The main instruction for the orchestrator agent's behavior."""
        current_agent = self.check_state(context)
        return f"""
        You are an expert AI Orchestrator. Your primary responsibility is to intelligently interpret user requests, plan the necessary sequence of actions if multiple steps are involved, and delegate them to the most appropriate specialized remote agents. You do not perform the tasks yourself but manage their assignment, sequence, and can monitor their status.

        **Core Workflow & Decision Making:**

        1.  **Understand User Intent & Complexity:**
            * Carefully analyze the user's request to determine the core task(s) they want to achieve. Pay close attention to keywords and the overall goal.
            * **Identify if the request requires a single agent or a sequence of actions from multiple agents.** For example, "Analyze John Doe's profile and then create a positive post about his recent event attendance" would require two agents in sequence.

        2.  **Agent Discovery & Selection (CRITICAL STEP):**
            * **Before making any assumptions about agent availability or capability, ALWAYS call `list_remote_agents()` first to get the most current and accurate list of available remote agents and their specific descriptions.** This is your primary source of truth for agent selection.
            * Based on the user's intent and the *actual output of `list_remote_agents()`*:
                * For **single-step requests**, select the single most appropriate agent.
                * For **multi-step requests**, identify all necessary agents and determine the logical order of their execution.

        3.  **Task Planning & Sequencing (for Multi-Step Requests):**
            * Before delegating, outline the sequence of agent tasks.
            * Identify dependencies: Does Agent B need information from Agent A's completed task?
            * Plan to execute tasks sequentially if there are dependencies, waiting for the completion of a prerequisite task before initiating the next one.

        4.  **Task Delegation & Management (EXECUTION PHASE):**
            * **To delegate *any* task (new or sequential), you MUST use the `send_task` tool.**
            * **NEVER assume an agent is not functioning unless a `send_task` call to that agent explicitly fails and returns an error message indicating a failure or unavailability.**
            * **For New Single Requests or the First Step in a Sequence:** Call `send_task(agent_name='<selected_agent_name>', message='<user_request_or_extracted_params>')`. The `message` argument must contain the user's original request or all necessary parameters formatted for the target agent.
            * **For Subsequent Steps in a Sequence:**
                * Wait for the preceding task to complete (you may need to use `check_pending_task_states` for monitoring, though `send_task` often returns status).
                * Once the prerequisite task is done, gather any necessary output from it.
                * Then, call `send_task` for the next agent in the sequence, providing it with relevant data obtained from the previous agent's task.
            * **For Ongoing Interactions with an Active Agent (within a single step):** If the user is providing follow-up information related to a task *currently assigned* to a specific agent, you would typically use `update_task` if available, or resend the relevant information via `send_task` with updated context. (Note: `update_task` is not currently in your tools, so focus on `send_task`).
            * **Monitoring:** Use `check_pending_task_states` to check the status of any delegated tasks, especially when managing sequences or if the user asks for an update. (Note: `check_pending_task_states` is not currently in your tools, but `send_task` provides immediate status).

        **Communication with User:**

        * When you delegate a task (or the first task in a sequence), clearly inform the user which remote agent is handling it.
        * For multi-step requests, you can optionally inform the user of the planned sequence (e.g., "Okay, first I'll ask the 'Social Profile Agent' to analyze the profile, and then I'll have the 'Instavibe Posting Agent' create the post.").
        * If waiting for a task in a sequence to complete, you can inform the user (e.g., "The 'Social Profile Agent' is currently processing. I'll proceed with the post once that's done.").
        * If the user's request is ambiguous, if necessary information is missing for any agent in the sequence, or if you are unsure about the plan, proactively ask the user for clarification.
        * Rely strictly on your tools and the information they provide.

        **Important Reminders:**
        * Always prioritize selecting the correct agent(s) based on their documented purpose.
        * Ensure all information required by the chosen remote agent is included in the `send_task` call, including outputs from previous agents if it's a sequential task.
        * Focus on the most recent parts of the conversation for immediate context, but maintain awareness of the overall goal, especially for multi-step requests.

        **Available Agents (discovered at startup):**
        {self.agents}

        Current active agent for this session: {current_agent['active_agent']}

        ---
        **ACTION INSTRUCTIONS:**
        Based on the user's request and the available agents, choose the most appropriate action:
        - **FIRST, if you are unsure about available agents or their capabilities, call `list_remote_agents()` to get the most accurate information.**
        - **THEN, if you have identified the appropriate agent(s) and the task message for the current step, call `send_task(agent_name='<AGENT_NAME>', message='<TASK_MESSAGE>')`.**
        - If you determine that no available agent can fulfill the request, or if you need more information from the user, respond directly to the user.
        """

  def check_state(self, context: ReadonlyContext):
    state = context.state
    if ('session_id' in state and
        'session_active' in state and
        state['session_active'] and
        'agent' in state):
      return {"active_agent": f'{state["agent"]}'}
    return {"active_agent": "None"}

  def before_model_callback(self, callback_context: CallbackContext, llm_request):
    state = callback_context.state
    if 'session_active' not in state or not state['session_active']:
      if 'session_id' not in state:
        state['session_id'] = str(uuid.uuid4())
      state['session_active'] = True

  def list_remote_agents(self) -> List[dict]:
    """Lists the available remote agents that this orchestrator can delegate tasks to.

    Returns:
      A list of dictionaries, where each dictionary contains the 'name' and 'description'
      of an available remote agent. This helps in selecting the most suitable agent for a task.
    """
    if not self.remote_agent_connections:
      return []

    remote_agent_info = []
    for card in self.cards.values():
      remote_agent_info.append(
          {"name": card.name, "description": card.description}
      )
    return remote_agent_info

  async def send_task(
      self,
      agent_name: str,
      message: str,
      tool_context: ToolContext # ADK framework injects this, LLM does not provide it
  ) -> List[str | DataPart]:
    """Sends a task to a specific remote agent for execution.

    This tool is used to delegate a user's request or a sub-task to a named remote agent.
    The orchestrator should provide a clear and concise message for the remote agent.

    Args:
      agent_name: The exact name of the remote agent to send the task to.
                  Refer to the output of `list_remote_agents()` for available names.
                  Example: "Planner Agent", "Social Profile Agent".
      message: The detailed request or task description for the remote agent.
               This should include all necessary information for the remote agent
               to understand and perform its task, extracted from the user's original request.

    Returns:
      A list of strings or DataParts representing the response from the remote agent.
      This response often contains the result or status of the delegated task.
    """
    if agent_name not in self.remote_agent_connections:
      raise ValueError(f"Agent '{agent_name}' not found. Please use `list_remote_agents()` to find valid names.")
    
    state = tool_context.state
    state['agent'] = agent_name # Track the active agent
    
    card = self.cards[agent_name]
    client = self.remote_agent_connections[agent_name]
    
    if not client:
      raise ValueError(f"A2A Client connection not available for agent '{agent_name}'.")
    
    # Ensure task ID and session ID are managed for continuity
    taskId = state.get('task_id', str(uuid.uuid4()))
    sessionId = state.get('session_id', str(uuid.uuid4()))
    
    messageId = str(uuid.uuid4()) # New message ID for this specific send_task call
    metadata = {'conversation_id': sessionId, 'message_id': messageId}
    if 'input_message_metadata' in state:
      metadata.update(**state['input_message_metadata'])

    request: TaskSendParams = TaskSendParams(
        id=taskId,
        sessionId=sessionId,
        message=Message(
            role="user",
            parts=[TextPart(text=message)],
            metadata=metadata,
        ),
        acceptedOutputModes=["text", "text/plain", "image/png"],
        metadata={'conversation_id': sessionId},
    )

    print(f"Orchestrator: Sending task to '{agent_name}' with message: '{message}' (Task ID: {taskId}, Session ID: {sessionId})", file=sys.stderr)
    
    task = await client.send_task(request, self.task_callback)

    response = []
    if task and task.status:
      state['session_active'] = task.status.state not in [
          TaskState.COMPLETED,
          TaskState.CANCELED,
          TaskState.FAILED,
          TaskState.UNKNOWN,
      ]
      
      # FIX START: Safely extract text from task.status.message for logging
      status_message_text = "None"
      if task.status.message and task.status.message.parts:
          for part in task.status.message.parts:
              if part.type == "text" and hasattr(part, 'text'):
                  status_message_text = part.text
                  break # Assuming you only want the first text part for the log
      print(f"Orchestrator: Task status from '{agent_name}' is {task.status.state}. Message: {status_message_text}", file=sys.stderr)
      # FIX END

      if task.status.state == TaskState.INPUT_REQUIRED:
        tool_context.actions.skip_summarization = True
        tool_context.actions.escalate = True
        response.append(f"The agent '{agent_name}' requires more input to proceed. Please provide further details.")
        # FIX START: Check for text part before appending to response
        if task.status.message and task.status.message.parts:
            for part in task.status.message.parts:
                if part.type == "text" and hasattr(part, 'text'):
                    response.append(part.text)
                    break # Assuming you only want the first text part
        # FIX END

      elif task.status.state == TaskState.CANCELED:
        # FIX START: Safely extract text for error message
        reason_text = "Unknown."
        if task.status.message and task.status.message.parts:
            for part in task.status.message.parts:
                if part.type == "text" and hasattr(part, 'text'):
                    reason_text = part.text
                    break
        raise ValueError(f"Agent '{agent_name}' task {task.id} was cancelled. Reason: {reason_text}")
        # FIX END
      elif task.status.state == TaskState.FAILED:
        # FIX START: Safely extract text for error message
        reason_text = "Unknown."
        if task.status.message and task.status.message.parts:
            for part in task.status.message.parts:
                if part.type == "text" and hasattr(part, 'text'):
                    reason_text = part.text
                    break
        raise ValueError(f"Agent '{agent_name}' task {task.id} failed. Reason: {reason_text}")
        # FIX END
      else: # Task is running, completed, etc.
          state['task_id'] = taskId # Keep the current task ID for follow-ups

    else:
      print(f"Warning: Received invalid task object or status from '{agent_name}'. Task: {task}", file=sys.stderr)
      state['session_active'] = False
      response.append(f"The remote agent '{agent_name}' did not return a valid task status. The task might not have been initiated successfully.")

    # This part was already correctly using convert_parts, which handles different part types.
    if task and task.status and task.status.message:
      response.extend(convert_parts(task.status.message.parts, tool_context))
    if task and task.artifacts:
      for artifact in task.artifacts:
        response.extend(convert_parts(artifact.parts, tool_context))
        
    return response

def convert_parts(parts: list[Part], tool_context: ToolContext) -> list[str | DataPart]:
  """Converts generic parts to types suitable for LLM output."""
  rval = []
  for p in parts:
    converted = convert_part(p, tool_context)
    if converted is not None:
        rval.append(converted)
  return rval

def convert_part(part: Part, tool_context: ToolContext):
  """Converts a single part object to a string or DataPart."""
  if part.type == "text":
    return part.text
  elif part.type == "data":
    return part.data
  elif part.type == "file":
    # Repackage A2A FilePart to google.genai Blob
    # Currently not considering plain text as files    
    file_id = part.file.name
    # Ensure bytes are present before decoding
    if part.file.bytes:
        try:
            file_bytes = base64.b64decode(part.file.bytes)
            file_part = types.Part(
              inline_data=types.Blob(
                mime_type=part.file.mimeType,
                data=file_bytes))
            tool_context.save_artifact(file_id, file_part)
            tool_context.actions.skip_summarization = True
            tool_context.actions.escalate = True
            return DataPart(data = {"artifact-file-id": file_id})
        except Exception as e:
            print(f"Error decoding file bytes for part {file_id}: {e}", file=sys.stderr)
            return f"Error processing file {file_id}: Invalid data."
    else:
        print(f"Warning: FilePart {file_id} has no bytes.", file=sys.stderr)
        return f"File {file_id} available, but no content."
  return f"Unknown part type: {part.type}"