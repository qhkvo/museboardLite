# Create a local worker credential without displaying it or replacing settings
from pathlib import Path
import os
import re
import secrets

root = Path(__file__).resolve().parents[1]
path = root / '.env'
existing = path.read_text() if path.exists() else ''
if re.search(r'^\s*(?:export\s+)?WORKER_TOKEN\s*=', existing, re.MULTILINE):
    print('WORKER_TOKEN is already configured in .env; kept existing settings.')
else:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(('\n' if existing and not existing.endswith('\n') else '')
                  + 'WORKER_TOKEN=' + secrets.token_hex(32) + '\n')
    print('Created local worker credential in .env (ignored by Git).')
