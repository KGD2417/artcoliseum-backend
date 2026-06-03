"""Auth dependencies: resolve the current user from a Bearer access token."""
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .database import get_db
from .models.user import User
from .security import decode_token

# auto_error=False so endpoints can allow anonymous access via get_optional_user.
_bearer = HTTPBearer(auto_error=False)


def _user_from_creds(creds: HTTPAuthorizationCredentials | None, db: Session) -> User | None:
    if not creds:
        return None
    payload = decode_token(creds.credentials, expected_type="access")
    if not payload:
        return None
    try:
        uid = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None
    return db.get(User, uid)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    user = _user_from_creds(creds, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    return _user_from_creds(creds, db)


def require_role(*roles: str):
    """Dependency factory: ensure the current user's profile.role is in `roles`."""

    def _checker(user: User = Depends(get_current_user)) -> User:
        role = user.profile.role if user.profile else "user"
        if role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {', '.join(roles)}",
            )
        return user

    return _checker
