from pydantic import BaseModel
from typing import Optional
from datetime import date
from datetime import datetime, timezone


def get_default_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class GetAppointmentsRequest(BaseModel):
    eDate: Optional[str] = None
    maxCount: Optional[int] = 100
