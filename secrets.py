from __future__ import annotations
import os
import re
from dataclasses import dataclass

_VALID_REF = re.compile(r'^[A-Z0-9_]{3,80}$')

class SecretStore:
    def get(self, ref: str) -> dict[str, str]:
        raise NotImplementedError

@dataclass
class EnvSecretStore(SecretStore):
    prefix: str = 'QOS_SECRET_'

    def get(self, ref: str) -> dict[str, str]:
        clean = ref.strip().upper()
        if not _VALID_REF.match(clean):
            raise ValueError('Invalid secret reference')
        base = f'{self.prefix}{clean}_'
        api_key = os.getenv(base + 'API_KEY', '')
        api_secret = os.getenv(base + 'API_SECRET', '')
        if not api_key or not api_secret:
            raise KeyError(f'Secret reference {clean} is not configured')
        return {'api_key': api_key, 'api_secret': api_secret}

secret_store: SecretStore = EnvSecretStore()
