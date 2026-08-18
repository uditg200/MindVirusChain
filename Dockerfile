FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/

# Install the package
RUN uv pip install --system -e .

# Copy experiment data (results will be served by the viewer)
COPY experiments/ ./experiments/

# Copy data directory (souls, etc.)
COPY data/ ./data/

# Copy startup script
COPY start_viewer.py ./

# Expose the port Render will use
EXPOSE 10000

# Start the viewer using the startup script that configures ROOT_DIR
CMD ["python", "start_viewer.py"]
