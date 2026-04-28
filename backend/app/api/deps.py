from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.postgres import get_db


DbDep = Annotated[Session, Depends(get_db)]
