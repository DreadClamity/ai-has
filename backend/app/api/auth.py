from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.rbac import get_current_user, require_roles
from app.core.security import create_access_token, verify_password
from app.database import get_db
from app.schemas.models import TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    row = db.execute(
        text(
            """
            SELECT id::text AS id, password_hash, role::text AS role, is_active
            FROM users
            WHERE email = :email
            """
        ),
        {"email": form_data.username.strip().lower()},
    ).mappings().first()

    if (
        row is None
        or not row["is_active"]
        or not verify_password(form_data.password, row["password_hash"])
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user_id=row["id"], role=row["role"])
    return TokenResponse(access_token=token, role=row["role"])


@router.get("/me", response_model=UserOut)
def read_me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.get("/users", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_roles("admin")),
):
    rows = db.execute(
        text(
            """
            SELECT id::text AS id, email, full_name, role::text AS role,
                   department, is_active
            FROM users
            ORDER BY created_at
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]