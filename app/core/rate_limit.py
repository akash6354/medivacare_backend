from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory and process-local; use an appropriate shared store before multi-worker deployment.
limiter = Limiter(key_func=get_remote_address, default_limits=[])
