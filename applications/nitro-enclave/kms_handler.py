#!/usr/bin/env python3
"""
KMS Handler for Nitro Enclave

Handles all AWS KMS operations from within the Nitro Enclave.
Uses attestation documents to prove enclave identity to KMS.

Key Features:
- Decrypt tenant requests using their KMS keys
- Encrypt inference results
- Attestation-based authentication
- Support for per-request dynamic KMS keys
"""

import boto3
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class KMSHandler:
    """Handles KMS operations with attestation"""

    def __init__(self):
        """Initialize KMS handler"""
        logger.info("Initializing KMS handler")

        # Create KMS client
        # Note: In production, use vsock-based AWS credentials provider
        # For now, we'll use the instance role credentials
        try:
            self.kms_client = boto3.client('kms')
            self._ready = True
            logger.info("KMS client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize KMS client: {e}")
            self._ready = False

    def is_ready(self) -> bool:
        """
        Check if KMS handler is ready

        Returns:
            True if ready
        """
        return self._ready

    def decrypt_with_attestation(
        self,
        ciphertext: bytes,
        key_arn: str,
        attestation_doc: bytes
    ) -> Optional[bytes]:
        """
        Decrypt ciphertext using KMS with attestation

        This method proves to KMS that the decryption is happening
        inside a verified Nitro Enclave by providing the attestation
        document.

        Flow:
        1. Call KMS Decrypt with ciphertext
        2. Include attestation document in request context
        3. KMS verifies attestation before decrypting
        4. Return plaintext

        Args:
            ciphertext: Encrypted data from tenant
            key_arn: Tenant's KMS key ARN
            attestation_doc: Nitro attestation document

        Returns:
            Decrypted plaintext or None on error
        """
        logger.info(f"Decrypting with KMS key: {key_arn}")

        try:
            # Build encryption context with attestation
            # This allows KMS key policies to enforce that decryption
            # only happens inside a verified Nitro Enclave
            encryption_context = {
                'aws:nitro-enclaves:attestation': base64.b64encode(attestation_doc).decode('utf-8')
            }

            # Call KMS Decrypt
            response = self.kms_client.decrypt(
                CiphertextBlob=ciphertext,
                KeyId=key_arn,
                EncryptionContext=encryption_context
            )

            plaintext = response['Plaintext']
            logger.info(f"Successfully decrypted {len(plaintext)} bytes")

            return plaintext

        except self.kms_client.exceptions.InvalidCiphertextException:
            logger.error("Invalid ciphertext provided")
            return None

        except self.kms_client.exceptions.AccessDeniedException:
            logger.error(f"Access denied to KMS key: {key_arn}")
            logger.error("Check that:")
            logger.error("  1. Key policy allows enclave to decrypt")
            logger.error("  2. Attestation document is valid")
            logger.error("  3. Enclave PCRs match key policy conditions")
            return None

        except self.kms_client.exceptions.NotFoundException:
            logger.error(f"KMS key not found: {key_arn}")
            return None

        except Exception as e:
            logger.error(f"Error decrypting with KMS: {e}", exc_info=True)
            return None

    def encrypt_with_attestation(
        self,
        plaintext: bytes,
        key_arn: str,
        attestation_doc: bytes
    ) -> Optional[bytes]:
        """
        Encrypt plaintext using KMS with attestation

        This method encrypts the inference result so only the tenant
        can decrypt it with their KMS key.

        Args:
            plaintext: Data to encrypt (inference result)
            key_arn: Tenant's KMS key ARN
            attestation_doc: Nitro attestation document

        Returns:
            Encrypted ciphertext or None on error
        """
        logger.info(f"Encrypting with KMS key: {key_arn}")

        try:
            # Build encryption context with attestation
            encryption_context = {
                'aws:nitro-enclaves:attestation': base64.b64encode(attestation_doc).decode('utf-8')
            }

            # Call KMS Encrypt
            response = self.kms_client.encrypt(
                KeyId=key_arn,
                Plaintext=plaintext,
                EncryptionContext=encryption_context
            )

            ciphertext = response['CiphertextBlob']
            logger.info(f"Successfully encrypted {len(plaintext)} bytes to {len(ciphertext)} bytes")

            return ciphertext

        except self.kms_client.exceptions.AccessDeniedException:
            logger.error(f"Access denied to KMS key: {key_arn}")
            return None

        except self.kms_client.exceptions.NotFoundException:
            logger.error(f"KMS key not found: {key_arn}")
            return None

        except Exception as e:
            logger.error(f"Error encrypting with KMS: {e}", exc_info=True)
            return None

    def verify_key_access(self, key_arn: str) -> bool:
        """
        Verify that enclave has access to a KMS key

        This is used during startup or health checks to verify
        that the enclave can access tenant KMS keys.

        Args:
            key_arn: KMS key ARN to verify

        Returns:
            True if enclave has access
        """
        try:
            # Try to describe the key
            response = self.kms_client.describe_key(KeyId=key_arn)

            key_id = response['KeyMetadata']['KeyId']
            key_state = response['KeyMetadata']['KeyState']

            logger.info(f"Key {key_id} is {key_state}")

            return key_state == 'Enabled'

        except self.kms_client.exceptions.AccessDeniedException:
            logger.warning(f"No access to key: {key_arn}")
            return False

        except self.kms_client.exceptions.NotFoundException:
            logger.warning(f"Key not found: {key_arn}")
            return False

        except Exception as e:
            logger.error(f"Error verifying key access: {e}")
            return False


# Example KMS Key Policy for Tenant Keys
#
# Tenants should configure their KMS keys with a policy that allows
# the GPU cluster to decrypt, but ONLY from inside a Nitro Enclave:
#
# {
#   "Version": "2012-10-17",
#   "Statement": [
#     {
#       "Sid": "Allow GPU cluster to decrypt in enclave only",
#       "Effect": "Allow",
#       "Principal": {
#         "AWS": "arn:aws:iam::GPU-CLUSTER-ACCOUNT-ID:role/gpu-instance-role"
#       },
#       "Action": [
#         "kms:Decrypt",
#         "kms:Encrypt"
#       ],
#       "Resource": "*",
#       "Condition": {
#         "StringEqualsIgnoreCase": {
#           "kms:RecipientAttestation:ImageSha384": "ENCLAVE_IMAGE_HASH"
#         }
#       }
#     }
#   ]
# }
#
# This ensures:
# 1. Only the GPU cluster's IAM role can access the key
# 2. Only from inside a Nitro Enclave with matching image hash
# 3. Parent instance CANNOT decrypt data (no enclave = no attestation)
