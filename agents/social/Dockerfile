# /Users/linchr/Desktop/work/datecoach/agents/social/Dockerfile

# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# --- Dependency Installation ---
# Copy only the requirements file first to leverage Docker cache
COPY agents/social/requirements.txt /app/requirements.txt
COPY agents/a2a_common-0.1.0-py3-none-any.whl /app/a2a_common-0.1.0-py3-none-any.whl
RUN pip install --no-cache-dir -r requirements.txt


# --- Application Code ---
COPY agents/social /app/agents/social

# --- Environment ---
ENV PYTHONPATH=/app/agents 


# Make port 8080 available to the world outside this container
# Cloud Run uses the PORT env var, but EXPOSE is good practice.
EXPOSE 10001

# --- Run the application ---
# Run a2a_server.py when the container launches
# Use the module execution '-m' which works well with the PYTHONPATH setup
CMD ["python", "-m", "social.a2a_server"]
