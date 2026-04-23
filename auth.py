"""
auth.py — Authentication helpers for BizMonitor.

Fixed for bcrypt 4.x compatibility — passwords are truncated to 72 bytes
before hashing to avoid the ValueError in newer bcrypt versions.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
import models

settings    = get_settings()
pwd_ctx     = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2      = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _truncate(password: str) -> str:
    """bcrypt silently truncated at 72 bytes in old versions; newer raises ValueError.
    We truncate explicitly so behaviour is consistent across all bcrypt versions."""
    return password.encode("utf-8")[:72].decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    return pwd_ctx.hash(_truncate(password))


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(_truncate(plain), hashed)


def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
    return db.query(models.User).filter(
        models.User.email == email.lower().strip()
    ).first()


def authenticate_user(db: Session, email: str, password: str) -> Optional[models.User]:
    user = get_user_by_email(db, email)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    expire    = datetime.utcnow() + (expires_delta or timedelta(minutes=480))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2),
    db: Session = Depends(get_db),
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def require_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def require_manager(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Manager access required")
    return current_user


def require_employee(current_user: models.User = Depends(get_current_user)) -> models.User:
    return current_user  # all authenticated users pass
