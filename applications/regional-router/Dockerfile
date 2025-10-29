# Dockerfile for Regional Router (ECS Fargate)

FROM public.ecr.aws/amazonlinux/amazonlinux:2023

# Install Python 3.11
RUN dnf install -y python3.11 python3.11-pip && dnf clean all

# Create app directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN python3.11 -m pip install --no-cache-dir -r requirements.txt

# Copy router application
COPY router_app.py .

# Copy global-state modules (dependencies)
RUN mkdir -p /opt/mrgc/applications/global-state
COPY ../global-state/*.py /opt/mrgc/applications/global-state/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV AWS_REGION=us-east-1

# Expose HTTP port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3.11 -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# Run router
CMD ["python3.11", "router_app.py"]
