from pydantic import BaseModel, EmailStr, Field, constr
from typing import List, Literal, Optional
from datetime import datetime, timezone


def get_default_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class GetAppointmentsRequest(BaseModel):
    eDate: Optional[str] = None
    maxCount: Optional[int] = 100
    providerId: Optional[str] = "0"
    facilityId: Optional[str] = "0"


class GetPatientsRequest(BaseModel):
    lastName: str
    firstName: Optional[str] = None
    maxCount: Optional[int] = 15


class AppointmentRequest(BaseModel):
    patient_name: str = Field(..., pattern=r"^[A-Za-z]+,\s[A-Za-z]+$")
    facility_name: str
    date: str = Field(
        ...,
        pattern=r"^(0[1-9]|1[0-2])/([0-2][0-9]|3[01])/\d{4}$",
        description="Format: MM/DD/YYYY",
    )
    start_time: str = Field(..., pattern=r"^(0[1-9]|1[0-2]):[0-5][0-9] (am|pm)$")
    end_time: str = Field(..., pattern=r"^(0[1-9]|1[0-2]):[0-5][0-9] (am|pm)$")
    provider: str
    resource: Optional[str] = None
    email: Optional[EmailStr] = None
    reason: str
    diagnosis: Optional[str] = None
    visit_type: str
    visit_status: Optional[str] = "PEN"
    encounterId: Optional[str] = None


class NewHistoryItem(BaseModel):
    reason: str
    date: str
    cptcode: Optional[str] = None


class AddSurgicalAndHospitilizationItemsRequest(BaseModel):
    encounter_id: str
    patient_id: str
    new_surgical_items: Optional[List[NewHistoryItem]] = Field(default_factory=list)
    new_hospitalization_items: Optional[List[NewHistoryItem]] = Field(
        default_factory=list
    )


class AddFamilyHistoryNoteRequest(BaseModel):
    encounter_id: str
    patient_id: str
    plain_text_notes: str


class AddSocialHistoryNoteRequest(BaseModel):
    encounter_id: str
    patient_id: str
    plain_text_notes: str


class AllergySearchRequest(BaseModel):
    search_text: str


class AllergyItemToAdd(BaseModel):
    drug_name: str
    rx_id: str
    reaction_description: str
    allergy_type: Literal[
        "Lack of Therapeutic Effect", "Allergy", "Side Effects", "Contraindication"
    ] = Field(default="Allergy")
    status: Literal["Active", "Inactive"] = Field(default="Active")
    criticality: Literal["Low", "Unknown", "High"] = Field(default="Low")
    onset_date: str = Field(
        ...,
        pattern=r"^(0[1-9]|1[0-2])/([0-2][0-9]|3[01])/\d{4}$",
        description="Format: MM/DD/YYYY",
    )  # format "MM/DD/YYYY"


class UpdateMedHxAllergyRequest(BaseModel):
    encounter_id: str
    patient_id: str
    medical_history_text: Optional[str] = None
    new_allergies: List[AllergyItemToAdd] = Field(default_factory=list)


class ECWLoginCredentials(BaseModel):
    username: str
    password: str
    validate_creds: Optional[bool] = True
