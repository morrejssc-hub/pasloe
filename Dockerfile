# Use a slim Python image
FROM python:3.11-slim as builder

# Install uv for fast dependency management
RUN pip install uv

# Set the working directory
WORKDIR /app

# Copy dependency files
copy pyproject.toml uv.lock ./

# Install dependencies (only) to cache them
RUN uv sync --no-install-project

# Final stage
FROM python:3.11-slim

WORKDIR /app

# Copy the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy the source code
COPY . .

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Expose the port
EXPOSE 8000

# Run migrations and start server
CMD ["./entrypoint.sh"]
