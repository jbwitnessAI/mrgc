#!/usr/bin/env python3
"""
Attestation Manager for Nitro Enclave

Generates and manages attestation documents that prove the enclave's
identity to external services like AWS KMS.

An attestation document contains:
- Platform Configuration Registers (PCRs) - measurements of enclave code
- Enclave image hash (SHA384)
- Public key
- Timestamp
- Cryptographic signature from AWS Nitro hardware

This document proves to KMS that:
1. Code is running inside a real AWS Nitro Enclave
2. The enclave image hash matches expected value
3. The enclave has not been tampered with
"""

import logging
import hashlib
import json
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class AttestationManager:
    """Manages Nitro Enclave attestation documents"""

    def __init__(self):
        """Initialize attestation manager"""
        logger.info("Initializing attestation manager")

        # Attestation document cache
        self._attestation_doc: Optional[bytes] = None
        self._attestation_timestamp: Optional[datetime] = None

        # PCR values (Platform Configuration Registers)
        # These are cryptographic measurements of the enclave
        self._pcr_values: Dict[int, str] = {}

    def generate_attestation(
        self,
        nonce: Optional[bytes] = None,
        user_data: Optional[bytes] = None,
        public_key: Optional[bytes] = None
    ) -> bytes:
        """
        Generate attestation document

        In production, this calls /dev/nsm (Nitro Secure Module) device
        to get a cryptographically signed attestation document from
        AWS Nitro hardware.

        Args:
            nonce: Optional nonce for freshness (max 512 bytes)
            user_data: Optional user data to include (max 512 bytes)
            public_key: Optional public key to include (max 1024 bytes)

        Returns:
            Attestation document (CBOR-encoded and signed)
        """
        logger.info("Generating attestation document")

        try:
            # In production, we would call the Nitro Secure Module (NSM)
            # device to generate the attestation document:
            #
            # import nsm_client
            # nsm = nsm_client.NSMClient()
            # attestation_doc = nsm.get_attestation_document(
            #     nonce=nonce,
            #     user_data=user_data,
            #     public_key=public_key
            # )
            #
            # The NSM returns a CBOR-encoded document signed by AWS Nitro
            # hardware that cannot be forged.

            # For development/testing, generate a mock attestation document
            attestation_doc = self._generate_mock_attestation(
                nonce=nonce,
                user_data=user_data,
                public_key=public_key
            )

            # Cache the attestation document
            self._attestation_doc = attestation_doc
            self._attestation_timestamp = datetime.utcnow()

            logger.info(f"Generated attestation document ({len(attestation_doc)} bytes)")

            return attestation_doc

        except Exception as e:
            logger.error(f"Error generating attestation: {e}", exc_info=True)
            raise

    def _generate_mock_attestation(
        self,
        nonce: Optional[bytes] = None,
        user_data: Optional[bytes] = None,
        public_key: Optional[bytes] = None
    ) -> bytes:
        """
        Generate mock attestation document for testing

        WARNING: This is for development only!
        In production, attestation MUST come from /dev/nsm device.

        Args:
            nonce: Optional nonce
            user_data: Optional user data
            public_key: Optional public key

        Returns:
            Mock attestation document
        """
        logger.warning("Generating MOCK attestation document (development only)")

        # Mock PCR values (in production, these come from NSM)
        pcrs = {
            0: hashlib.sha384(b"enclave-kernel").hexdigest(),      # Kernel
            1: hashlib.sha384(b"enclave-initramfs").hexdigest(),   # Init
            2: hashlib.sha384(b"enclave-application").hexdigest(), # Application
            3: hashlib.sha384(b"parent-instance-iam").hexdigest()  # IAM role
        }

        # Build attestation document structure
        attestation = {
            "module_id": "i-1234567890abcdef0-enc0123456789abcd",
            "timestamp": int(datetime.utcnow().timestamp() * 1000),
            "digest": "SHA384",
            "pcrs": pcrs,
            "certificate": "-----BEGIN CERTIFICATE-----\nMOCK CERTIFICATE\n-----END CERTIFICATE-----",
            "cabundle": ["-----BEGIN CERTIFICATE-----\nMOCK CA BUNDLE\n-----END CERTIFICATE-----"],
        }

        # Add optional fields
        if nonce:
            attestation["nonce"] = nonce.hex()
        if user_data:
            attestation["user_data"] = user_data.hex()
        if public_key:
            attestation["public_key"] = public_key.hex()

        # In production, this would be CBOR-encoded and cryptographically signed
        # For mock, we'll just JSON encode
        attestation_json = json.dumps(attestation, sort_keys=True)
        attestation_bytes = attestation_json.encode('utf-8')

        return attestation_bytes

    def verify_attestation(self, attestation_doc: bytes) -> bool:
        """
        Verify attestation document signature

        In production, this verifies:
        1. Document is properly CBOR-encoded
        2. Signature is valid (signed by AWS Nitro root CA)
        3. Certificate chain is valid
        4. PCR values match expected measurements

        Args:
            attestation_doc: Attestation document to verify

        Returns:
            True if valid
        """
        logger.info("Verifying attestation document")

        try:
            # In production, we would:
            # 1. Decode CBOR
            # 2. Verify signature chain
            # 3. Check certificate against AWS Nitro root CA
            # 4. Verify PCR values
            #
            # import cbor2
            # import cryptography
            #
            # attestation = cbor2.loads(attestation_doc)
            # signature = attestation['signature']
            # certificate = attestation['certificate']
            #
            # # Verify signature with certificate
            # # Verify certificate with AWS Nitro CA
            # # Check PCR values

            # For mock, just check it's valid JSON
            attestation = json.loads(attestation_doc.decode('utf-8'))

            # Verify required fields
            required_fields = ['module_id', 'timestamp', 'digest', 'pcrs']
            for field in required_fields:
                if field not in attestation:
                    logger.error(f"Missing required field: {field}")
                    return False

            logger.info("Attestation document is valid")
            return True

        except Exception as e:
            logger.error(f"Error verifying attestation: {e}", exc_info=True)
            return False

    def get_pcr_values(self) -> Dict[int, str]:
        """
        Get PCR (Platform Configuration Register) values

        PCRs are cryptographic measurements of:
        - PCR0: Enclave kernel
        - PCR1: Enclave initramfs
        - PCR2: Enclave application
        - PCR3: Parent instance IAM role
        - PCR4-15: Reserved for future use

        Returns:
            Dict mapping PCR index to hex value
        """
        if not self._attestation_doc:
            logger.warning("No attestation document generated yet")
            return {}

        try:
            # Parse attestation document to extract PCRs
            attestation = json.loads(self._attestation_doc.decode('utf-8'))
            pcrs = attestation.get('pcrs', {})

            # Convert string keys to ints
            return {int(k): v for k, v in pcrs.items()}

        except Exception as e:
            logger.error(f"Error extracting PCR values: {e}")
            return {}

    def get_enclave_measurements(self) -> Dict[str, str]:
        """
        Get enclave measurements (PCR hashes)

        This is used by KMS key policies to enforce that only
        a specific enclave image can decrypt data.

        Returns:
            Dict with measurement hashes
        """
        pcrs = self.get_pcr_values()

        return {
            'kernel_hash': pcrs.get(0, 'unknown'),
            'initramfs_hash': pcrs.get(1, 'unknown'),
            'application_hash': pcrs.get(2, 'unknown'),
            'iam_role_hash': pcrs.get(3, 'unknown')
        }

    def refresh_attestation(self) -> bytes:
        """
        Refresh attestation document

        Attestation documents should be refreshed periodically
        to prevent replay attacks.

        Recommended refresh interval: Every 60 minutes

        Returns:
            New attestation document
        """
        logger.info("Refreshing attestation document")

        # Generate new attestation with fresh timestamp
        return self.generate_attestation()


# Production Setup Notes:
#
# 1. Install NSM library in enclave:
#    - AWS provides nsm-lib and nsm-api
#    - These provide access to /dev/nsm device
#
# 2. Replace _generate_mock_attestation with real NSM calls:
#    ```python
#    import nsm
#    nsm_fd = nsm.nsm_lib_init()
#    attestation = nsm.nsm_get_attestation_doc(
#        nsm_fd,
#        nonce,
#        user_data,
#        public_key
#    )
#    nsm.nsm_lib_exit(nsm_fd)
#    ```
#
# 3. Tenant KMS key policies check attestation:
#    - Key policy condition: kms:RecipientAttestation:ImageSha384
#    - Must match PCR2 (application hash)
#    - Ensures only verified enclave can decrypt
#
# 4. Security benefits:
#    - Hardware-signed attestation cannot be forged
#    - PCR values prove code integrity
#    - KMS verifies attestation before decrypt
#    - Parent instance cannot generate valid attestation
