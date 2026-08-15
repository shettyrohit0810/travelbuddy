"""Request dependencies.

`get_current_user` is the only source of caller identity. No endpoint accepts a
`user_id` from the client -- doing so is an IDOR by construction, since a client-supplied
identifier is an assertion, not a proof.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import ACCESS, decode_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

_UNAUTHORISED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> User:
    payload = decode_token(token, ACCESS)
    if payload is None:
        raise _UNAUTHORISED
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if user is None:
        raise _UNAUTHORISED
    return user
