# Use the official lightweight Python image
FROM python:3.11-slim

# Keep Python from buffering logs
ENV PYTHONUNBUFFERED=1

# Create app directory
WORKDIR /app

# Copy files into the container
COPY . ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Start the bot (Notice it says main.py to match your file!)
CMD ["python", "main.py"]
