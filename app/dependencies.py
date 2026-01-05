from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings  # This is now a dynamic proxy

security = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> None:
    """
    Verify the bearer token matches configured AUTH_TOKEN.

    Uses the dynamic settings proxy to get the current auth_token,
    which may have been reloaded from config.yaml.
    """
    if credentials.credentials != settings.auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )
