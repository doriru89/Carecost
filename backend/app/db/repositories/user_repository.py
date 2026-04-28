from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.tables import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def find_by_email(self, email: str) -> User | None:
        return self.db.query(User).filter(User.email == email.lower()).first()

    def find_by_id(self, user_id: str) -> User | None:
        return self.db.get(User, uuid.UUID(user_id))

    def patch_profiles(
        self,
        user_id: str,
        *,
        user_profile: dict[str, Any] | None = None,
        insurance_profile: dict[str, Any] | None = None,
    ) -> User | None:
        u = self.find_by_id(user_id)
        if not u:
            return None
        if user_profile is not None:
            u.user_profile = user_profile
        if insurance_profile is not None:
            u.insurance_profile = insurance_profile
        self.db.flush()
        return u
