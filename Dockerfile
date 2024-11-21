# Use the official Python 3.9 slim image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy only the requirements file first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose any necessary ports (if applicable)
# EXPOSE 8080

# The .env file will be provided at runtime using --env-file, so we don't copy it into the image

# Set the entrypoint to allow specifying which script to run
ENTRYPOINT ["python"]
