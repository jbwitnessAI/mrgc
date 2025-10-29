#!/usr/bin/env python3
"""
vsock Handler for Parent Instance

Handles communication with Nitro Enclave via vsock (virtual socket).

vsock is a special socket type that allows communication between:
- Parent instance (CID 3)
- Enclave (CID 16)

Unlike network sockets, vsock:
- Doesn't use network stack
- Cannot be intercepted
- Is isolated to parent-enclave communication
- Has very low latency (1-2ms)
"""

import socket
import json
import base64
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class VsockHandler:
    """Handles vsock communication with enclave"""

    # vsock configuration
    VSOCK_PORT = 5000
    ENCLAVE_CID = 16  # Enclave always has CID 16

    def __init__(self):
        """Initialize vsock handler"""
        logger.info("Initializing vsock handler")

        self.socket: Optional[socket.socket] = None
        self.connected = False

    def connect(self) -> bool:
        """
        Connect to enclave via vsock

        Returns:
            True if connected successfully
        """
        logger.info(f"Connecting to enclave CID {self.ENCLAVE_CID} port {self.VSOCK_PORT}")

        try:
            # Create vsock socket
            self.socket = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)

            # Set socket timeout
            self.socket.settimeout(10.0)

            # Connect to enclave
            self.socket.connect((self.ENCLAVE_CID, self.VSOCK_PORT))

            self.connected = True
            logger.info("✓ Connected to enclave via vsock")

            return True

        except socket.timeout:
            logger.error("Timeout connecting to enclave")
            return False

        except socket.error as e:
            logger.error(f"Socket error connecting to enclave: {e}")
            return False

        except Exception as e:
            logger.error(f"Error connecting to enclave: {e}", exc_info=True)
            return False

    def is_connected(self) -> bool:
        """
        Check if connected to enclave

        Returns:
            True if connected
        """
        return self.connected and self.socket is not None

    def disconnect(self):
        """Disconnect from enclave"""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass

        self.socket = None
        self.connected = False
        logger.info("Disconnected from enclave")

    def decrypt(
        self,
        encrypted_payload: bytes,
        kms_key_arn: str,
        tenant_id: str,
        request_id: str
    ) -> Optional[bytes]:
        """
        Send encrypted payload to enclave for decryption

        Args:
            encrypted_payload: Encrypted data from tenant
            kms_key_arn: Tenant's KMS key ARN
            tenant_id: Tenant ID
            request_id: Request ID

        Returns:
            Decrypted plaintext or None on error
        """
        logger.info(f"[{request_id}] Requesting decryption from enclave")

        # Build decrypt request
        request = {
            'action': 'decrypt',
            'encrypted_payload': base64.b64encode(encrypted_payload).decode('utf-8'),
            'kms_key_arn': kms_key_arn,
            'tenant_id': tenant_id,
            'request_id': request_id
        }

        # Send to enclave
        response = self._send_request(request)

        if not response:
            logger.error(f"[{request_id}] No response from enclave")
            return None

        if not response.get('success'):
            logger.error(f"[{request_id}] Decryption failed in enclave")
            return None

        # Extract plaintext
        plaintext_b64 = response.get('plaintext')
        if not plaintext_b64:
            logger.error(f"[{request_id}] No plaintext in response")
            return None

        plaintext = base64.b64decode(plaintext_b64)

        logger.info(f"[{request_id}] Decryption successful ({len(plaintext)} bytes)")

        return plaintext

    def encrypt(
        self,
        plaintext_result: bytes,
        kms_key_arn: str,
        request_id: str
    ) -> Optional[bytes]:
        """
        Send plaintext result to enclave for encryption

        Args:
            plaintext_result: Inference result to encrypt
            kms_key_arn: Tenant's KMS key ARN
            request_id: Request ID

        Returns:
            Encrypted ciphertext or None on error
        """
        logger.info(f"[{request_id}] Requesting encryption from enclave")

        # Build encrypt request
        request = {
            'action': 'encrypt',
            'plaintext_result': base64.b64encode(plaintext_result).decode('utf-8'),
            'kms_key_arn': kms_key_arn,
            'request_id': request_id
        }

        # Send to enclave
        response = self._send_request(request)

        if not response:
            logger.error(f"[{request_id}] No response from enclave")
            return None

        if not response.get('success'):
            logger.error(f"[{request_id}] Encryption failed in enclave")
            return None

        # Extract encrypted response
        encrypted_b64 = response.get('encrypted_response')
        if not encrypted_b64:
            logger.error(f"[{request_id}] No encrypted response")
            return None

        encrypted = base64.b64decode(encrypted_b64)

        logger.info(f"[{request_id}] Encryption successful ({len(encrypted)} bytes)")

        return encrypted

    def health_check(self) -> bool:
        """
        Check enclave health

        Returns:
            True if enclave is healthy
        """
        logger.info("Checking enclave health")

        if not self.is_connected():
            logger.warning("Not connected to enclave")
            return False

        # Send health check request
        request = {
            'action': 'health',
            'request_id': 'health-check'
        }

        response = self._send_request(request)

        if not response:
            logger.warning("No response from enclave health check")
            return False

        status = response.get('status')
        attestation_ready = response.get('attestation_ready', False)
        kms_ready = response.get('kms_ready', False)

        healthy = (status == 'healthy') and attestation_ready and kms_ready

        if healthy:
            logger.info("✓ Enclave is healthy")
        else:
            logger.warning(f"Enclave not healthy: status={status}, attestation={attestation_ready}, kms={kms_ready}")

        return healthy

    def _send_request(self, request: Dict) -> Optional[Dict]:
        """
        Send request to enclave and receive response

        Protocol:
        1. Send length (4 bytes, big-endian)
        2. Send JSON data
        3. Receive length (4 bytes, big-endian)
        4. Receive JSON response

        Args:
            request: Request dict

        Returns:
            Response dict or None on error
        """
        if not self.is_connected():
            logger.error("Not connected to enclave")
            return None

        try:
            # Serialize request to JSON
            request_json = json.dumps(request).encode('utf-8')

            # Send length (4 bytes, big-endian)
            length = len(request_json)
            self.socket.sendall(length.to_bytes(4, byteorder='big'))

            # Send data
            self.socket.sendall(request_json)

            # Receive response length (4 bytes)
            length_bytes = self.socket.recv(4)
            if not length_bytes:
                logger.error("No response from enclave")
                return None

            response_length = int.from_bytes(length_bytes, byteorder='big')

            # Receive full response
            response_data = b''
            while len(response_data) < response_length:
                chunk = self.socket.recv(min(response_length - len(response_data), 4096))
                if not chunk:
                    break
                response_data += chunk

            if len(response_data) != response_length:
                logger.error(f"Incomplete response: expected {response_length}, got {len(response_data)}")
                return None

            # Parse JSON response
            response = json.loads(response_data.decode('utf-8'))

            return response

        except socket.timeout:
            logger.error("Timeout waiting for enclave response")
            return None

        except socket.error as e:
            logger.error(f"Socket error communicating with enclave: {e}")
            self.connected = False
            return None

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from enclave: {e}")
            return None

        except Exception as e:
            logger.error(f"Error communicating with enclave: {e}", exc_info=True)
            return None

    def reconnect(self) -> bool:
        """
        Reconnect to enclave

        Returns:
            True if reconnected successfully
        """
        logger.info("Reconnecting to enclave")

        self.disconnect()

        return self.connect()
