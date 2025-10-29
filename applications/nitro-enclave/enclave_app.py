#!/usr/bin/env python3
"""
Nitro Enclave Application for Multi-Region GPU Cluster

Handles all encryption/decryption operations with cryptographic isolation.
Runs inside AWS Nitro Enclave with hardware-enforced memory protection.

Key Responsibilities:
1. Generate attestation document
2. Decrypt tenant requests using their KMS keys
3. Send plaintext to parent instance (via vsock)
4. Encrypt inference results
5. Return encrypted response to parent

Security Properties:
- Parent instance NEVER sees plaintext data
- Parent instance NEVER sees KMS keys
- All crypto operations happen in hardware-isolated enclave
- Memory is encrypted and isolated by AWS Nitro hardware
"""

import socket
import json
import base64
import logging
import sys
from typing import Dict, Tuple, Optional

from kms_handler import KMSHandler
from attestation import AttestationManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[ENCLAVE] %(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


class EnclaveApp:
    """Main Nitro Enclave application"""

    # vsock configuration
    VSOCK_PORT = 5000
    VSOCK_CID_PARENT = 3  # Parent instance CID

    def __init__(self):
        """Initialize enclave application"""
        logger.info("Initializing Nitro Enclave application")

        # Initialize KMS handler
        self.kms_handler = KMSHandler()

        # Initialize attestation manager
        self.attestation_mgr = AttestationManager()

        # Generate attestation document on startup
        self.attestation_doc = self.attestation_mgr.generate_attestation()
        logger.info(f"Attestation document generated (size: {len(self.attestation_doc)} bytes)")

        # vsock socket
        self.vsock_socket = None

    def setup_vsock_server(self):
        """
        Set up vsock server to receive requests from parent

        vsock allows communication between enclave and parent instance
        without going through network stack
        """
        logger.info(f"Setting up vsock server on port {self.VSOCK_PORT}")

        # Create vsock socket
        self.vsock_socket = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)

        # Bind to enclave CID (always CID 16 for enclave)
        # Port 5000 for communication
        self.vsock_socket.bind((socket.VMADDR_CID_ANY, self.VSOCK_PORT))

        # Listen for connections
        self.vsock_socket.listen(10)

        logger.info("vsock server ready, waiting for parent connection")

    def handle_request(
        self,
        encrypted_payload: bytes,
        kms_key_arn: str,
        tenant_id: str,
        request_id: str
    ) -> Tuple[bytes, bool]:
        """
        Handle encrypted inference request

        Flow:
        1. Use attestation to get decrypt permission from KMS
        2. Decrypt request payload
        3. Send plaintext to parent (via vsock response)
        4. Receive inference result from parent
        5. Encrypt result
        6. Return encrypted result

        Args:
            encrypted_payload: Encrypted request from tenant
            kms_key_arn: Tenant's KMS key ARN
            tenant_id: Tenant ID
            request_id: Unique request ID

        Returns:
            Tuple of (encrypted_response, success)
        """
        logger.info(f"Processing request {request_id} for tenant {tenant_id}")

        try:
            # Step 1: Decrypt request using KMS with attestation
            logger.info(f"Decrypting request with KMS key: {kms_key_arn}")

            plaintext_request = self.kms_handler.decrypt_with_attestation(
                ciphertext=encrypted_payload,
                key_arn=kms_key_arn,
                attestation_doc=self.attestation_doc
            )

            if not plaintext_request:
                logger.error("Failed to decrypt request")
                return self._create_error_response("Decryption failed"), False

            logger.info(f"Request decrypted successfully ({len(plaintext_request)} bytes)")

            # Step 2: Parse plaintext request
            try:
                request_data = json.loads(plaintext_request.decode('utf-8'))
            except Exception as e:
                logger.error(f"Failed to parse request JSON: {e}")
                return self._create_error_response("Invalid request format"), False

            # Step 3: Return plaintext to parent for inference
            # (Parent will send this via vsock back to us after inference)
            logger.info("Returning plaintext to parent for GPU inference")

            return plaintext_request, True

        except Exception as e:
            logger.error(f"Error handling request: {e}", exc_info=True)
            return self._create_error_response(str(e)), False

    def encrypt_response(
        self,
        plaintext_response: bytes,
        kms_key_arn: str
    ) -> Optional[bytes]:
        """
        Encrypt inference response for tenant

        Args:
            plaintext_response: Inference result from parent
            kms_key_arn: Tenant's KMS key ARN

        Returns:
            Encrypted response or None on error
        """
        logger.info(f"Encrypting response with KMS key: {kms_key_arn}")

        try:
            encrypted = self.kms_handler.encrypt_with_attestation(
                plaintext=plaintext_response,
                key_arn=kms_key_arn,
                attestation_doc=self.attestation_doc
            )

            if encrypted:
                logger.info(f"Response encrypted successfully ({len(encrypted)} bytes)")
            else:
                logger.error("Failed to encrypt response")

            return encrypted

        except Exception as e:
            logger.error(f"Error encrypting response: {e}", exc_info=True)
            return None

    def process_vsock_request(self, conn: socket.socket):
        """
        Process a single vsock request from parent

        Protocol:
        1. Parent sends: {
             "action": "decrypt",
             "encrypted_payload": base64,
             "kms_key_arn": str,
             "tenant_id": str,
             "request_id": str
           }
        2. Enclave decrypts and returns: {
             "plaintext": base64,
             "success": bool
           }
        3. Parent performs inference
        4. Parent sends: {
             "action": "encrypt",
             "plaintext_result": base64,
             "kms_key_arn": str,
             "request_id": str
           }
        5. Enclave encrypts and returns: {
             "encrypted_response": base64,
             "success": bool
           }

        Args:
            conn: vsock connection socket
        """
        try:
            # Receive data from parent
            data = self._recv_json(conn)

            if not data:
                logger.warning("Received empty data from parent")
                return

            action = data.get('action')
            request_id = data.get('request_id', 'unknown')

            logger.info(f"Received action: {action} (request: {request_id})")

            if action == 'decrypt':
                # Decrypt request
                encrypted_payload = base64.b64decode(data['encrypted_payload'])
                kms_key_arn = data['kms_key_arn']
                tenant_id = data['tenant_id']

                plaintext, success = self.handle_request(
                    encrypted_payload=encrypted_payload,
                    kms_key_arn=kms_key_arn,
                    tenant_id=tenant_id,
                    request_id=request_id
                )

                # Send plaintext back to parent
                response = {
                    'plaintext': base64.b64encode(plaintext).decode('utf-8'),
                    'success': success,
                    'request_id': request_id
                }

                self._send_json(conn, response)

            elif action == 'encrypt':
                # Encrypt inference result
                plaintext_result = base64.b64decode(data['plaintext_result'])
                kms_key_arn = data['kms_key_arn']

                encrypted = self.encrypt_response(
                    plaintext_response=plaintext_result,
                    kms_key_arn=kms_key_arn
                )

                # Send encrypted response back to parent
                response = {
                    'encrypted_response': base64.b64encode(encrypted).decode('utf-8') if encrypted else None,
                    'success': encrypted is not None,
                    'request_id': request_id
                }

                self._send_json(conn, response)

            elif action == 'health':
                # Health check
                response = {
                    'status': 'healthy',
                    'attestation_ready': self.attestation_doc is not None,
                    'kms_ready': self.kms_handler.is_ready()
                }

                self._send_json(conn, response)

            else:
                logger.warning(f"Unknown action: {action}")
                self._send_json(conn, {'error': 'Unknown action', 'success': False})

        except Exception as e:
            logger.error(f"Error processing vsock request: {e}", exc_info=True)
            try:
                self._send_json(conn, {'error': str(e), 'success': False})
            except:
                pass

    def run(self):
        """
        Main application loop

        Listens for vsock connections from parent and processes requests
        """
        logger.info("Starting Nitro Enclave main loop")

        # Set up vsock server
        self.setup_vsock_server()

        # Accept connections from parent
        while True:
            try:
                logger.info("Waiting for parent connection...")

                conn, addr = self.vsock_socket.accept()
                logger.info(f"Parent connected from CID: {addr}")

                # Process request
                self.process_vsock_request(conn)

                # Close connection
                conn.close()

            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                break

            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                # Continue running even on errors

        # Cleanup
        if self.vsock_socket:
            self.vsock_socket.close()

        logger.info("Nitro Enclave shutting down")

    def _recv_json(self, conn: socket.socket) -> Optional[Dict]:
        """
        Receive JSON message from vsock

        Args:
            conn: vsock connection

        Returns:
            Parsed JSON dict or None
        """
        # First receive length (4 bytes)
        length_bytes = conn.recv(4)
        if not length_bytes:
            return None

        length = int.from_bytes(length_bytes, byteorder='big')

        # Receive full message
        data = b''
        while len(data) < length:
            chunk = conn.recv(min(length - len(data), 4096))
            if not chunk:
                break
            data += chunk

        # Parse JSON
        return json.loads(data.decode('utf-8'))

    def _send_json(self, conn: socket.socket, data: Dict):
        """
        Send JSON message via vsock

        Args:
            conn: vsock connection
            data: Dict to send as JSON
        """
        # Serialize to JSON
        json_data = json.dumps(data).encode('utf-8')

        # Send length first (4 bytes)
        length = len(json_data)
        conn.sendall(length.to_bytes(4, byteorder='big'))

        # Send data
        conn.sendall(json_data)

    def _create_error_response(self, error_message: str) -> bytes:
        """
        Create error response

        Args:
            error_message: Error description

        Returns:
            Error response as bytes
        """
        error_response = {
            'error': error_message,
            'success': False
        }

        return json.dumps(error_response).encode('utf-8')


def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("AWS Nitro Enclave - Multi-Region GPU Cluster")
    logger.info("Version: 1.0.0")
    logger.info("=" * 60)

    # Create and run enclave application
    app = EnclaveApp()
    app.run()


if __name__ == '__main__':
    main()
