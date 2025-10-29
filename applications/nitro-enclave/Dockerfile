# Dockerfile for Nitro Enclave Application
#
# This builds a Docker image that will be converted to an Enclave Image File (EIF)
# using the nitro-cli build-enclave command.

FROM public.ecr.aws/amazonlinux/amazonlinux:2023

# Install Python 3.11 and dependencies
RUN dnf install -y \
    python3.11 \
    python3.11-pip \
    && dnf clean all

# Create app directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN python3.11 -m pip install --no-cache-dir -r requirements.txt

# Copy enclave application code
COPY enclave_app.py .
COPY kms_handler.py .
COPY attestation.py .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# In production, you would install the NSM library here:
# RUN rpm -ivh aws-nitro-enclaves-nsm-api-*.rpm

# Expose vsock port (documentation only, vsock doesn't use network)
EXPOSE 5000

# Set entrypoint
ENTRYPOINT ["python3.11", "enclave_app.py"]
