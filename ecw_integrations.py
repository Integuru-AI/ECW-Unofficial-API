from datetime import datetime
import json
import time
from typing import Optional
from urllib.parse import quote_plus, urlencode
import aiohttp
from fake_useragent import UserAgent
from fastapi import HTTPException
from fastapi.logger import logger
from integrations.ecw.ecw_config import (
    BASE_URL,
    ECW_URLS,
    AuthTokens,
    reduced_visit_types,
)
from integrations.ecw.ecw_utils import (
    create_new_appointment_formdata_v2,
    generate_batch_allergy_flags_xml,
    generate_batch_medhx_flag_xml,
    generate_encounter_details_flag_xml,
    generate_family_history_formdata_notes_xml,
    generate_formdata_xml_for_history,
    generate_medical_history_text_xml,
    generate_set_allergy_item_xml,
    generate_social_history_formdata_xml,
    parse_progress_note_html,
    parse_xml_response,
)
from urllib import parse
from submodule_integrations.ecw.ecw_models import (
    AddFamilyHistoryNoteRequest,
    AddSocialHistoryNoteRequest,
    AddSurgicalAndHospitilizationItemsRequest,
    AppointmentRequest,
    GetAppointmentsRequest,
    GetPatientsRequest,
    UpdateMedHxAllergyRequest,
    get_default_date,
)
from submodule_integrations.models.integration import Integration
from submodule_integrations.utils.errors import (
    IntegrationAPIError,
)
import json
import traceback


class ECWIntegration(Integration):
    def __init__(self, auth_tokens: AuthTokens, user_agent: str = UserAgent().chrome):
        super().__init__("ecw")
        self.user_agent = user_agent
        self.network_requester = None
        self.url = "https://nybukaapp.eclinicalweb.com/mobiledoc/jsp/catalog/xml"
        self.auth_tokens: AuthTokens = auth_tokens
        self.client_session = aiohttp.ClientSession()

    @classmethod
    async def create(cls, auth_tokens: AuthTokens, network_requester=None):
        instance = cls(auth_tokens)
        instance.network_requester = network_requester

        return instance

    async def _make_request(self, method: str, url: str, **kwargs):
        if self.network_requester:
            response = await self.network_requester.request(method, url, **kwargs)
            return response
        else:
            async with self.client_session.request(method, url, **kwargs) as response:
                return await self._handle_response(response)

    async def close_session(self):
        await self.client_session.close()
        logger.debug("Closed client session in EcwIntegrations")

    async def _handle_response(self, response: aiohttp.ClientResponse):
        response_text = await response.text()
        status = response.status

        parsed_data = None

        try:
            if response_text.strip().startswith(
                "<?xml"
            ) or response_text.strip().startswith("<root"):
                parsed_data = parse_xml_response(response_text)
            elif response_text.strip().startswith("<HTML>"):
                parsed_data = parse_progress_note_html(response_text)
            elif response_text.strip().startswith("{"):
                parsed_data = json.loads(response_text)
            else:
                return response_text
        except Exception as e:
            await self.close_session()
            logger.warning(f"Response parsing failed: {str(e)}")
            # logger.warning(f"Cause: {traceback.print_exc()}")
            parsed_data = {"error": {"message": "Parsing error", "raw": response_text}}

        if 200 <= status < 300:
            return parsed_data

        error_message = parsed_data.get("error", {}).get("message", "Unknown error")
        error_code = parsed_data.get("error", {}).get("code", str(status))

        logger.debug(f"{status} - {parsed_data}")

        if 400 <= status < 500:
            await self.close_session()
            raise HTTPException(status_code=status, detail=parsed_data)
        elif status >= 500:
            await self.close_session()
            raise IntegrationAPIError(
                self.integration_name,
                f"Downstream server error (translated to HTTP 501): {error_message}",
                501,
                error_code,
            )
        else:
            await self.close_session()
            raise IntegrationAPIError(
                self.integration_name,
                f"{error_message} (HTTP {status})",
                status,
                error_code,
            )

    async def _setup_headers(self, content_type: str = None):
        _headers = {
            "User-Agent": self.user_agent,
            "Cookie": self.auth_tokens.Cookie,
            "Sec-Ch-Ua": "'Chromium';v='134', 'Not:A-Brand';v='24', 'Google Chrome';v='134'",
            "x-csrf-token": self.auth_tokens.x_csrf_token,
        }
        if content_type:
            _headers["Content-type"] = content_type

        return _headers

    async def get_facilities(self, close_session: bool = True):
        logger.debug("Fetching list of all facilities")
        try:
            headers = await self._setup_headers()

            url = ECW_URLS["get facilities"].format(
                sessionDID=self.auth_tokens.sessionDID,
                TrUserId=self.auth_tokens.TrUserId,
                timestamp=int(time.time() * 1000),
                clientTimezone="UTC",
            )

            return await self._make_request(
                method="GET",
                url=url,
                headers=headers,
            )
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            if close_session:
                await self.close_session()

    async def get_providers(self, page: int, close_session: bool = True):
        logger.debug(f"Fetching page: {page} of providers")
        try:
            headers = await self._setup_headers()

            url = ECW_URLS["get providers"].format(
                page=page,
                sessionDID=self.auth_tokens.sessionDID,
                TrUserId=self.auth_tokens.TrUserId,
                timestamp=int(time.time() * 1000),
                clientTimezone="UTC",
            )

            return await self._make_request(
                method="POST",
                url=url,
                headers=headers,
            )
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            if close_session:
                await self.close_session()

    async def get_provider(self, providerName: str, close_session: bool = True):
        logger.debug(f"Looking for provider: {providerName}")
        try:
            headers = await self._setup_headers()

            url = ECW_URLS["get provider"].format(
                provider=providerName.lower(),
                sessionDID=self.auth_tokens.sessionDID,
                TrUserId=self.auth_tokens.TrUserId,
                timestamp=int(time.time() * 1000),
                clientTimezone="UTC",
            )

            return await self._make_request(
                method="POST",
                url=url,
                headers=headers,
            )
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            if close_session:
                await self.close_session()

    async def get_reasons(self, close_session: bool = True):
        logger.debug(f"Fetching reasons")
        try:
            headers = await self._setup_headers()

            url = ECW_URLS["get resons"].format(
                sessionDID=self.auth_tokens.sessionDID,
                TrUserId=self.auth_tokens.TrUserId,
                timestamp=int(time.time() * 1000),
                clientTimezone="UTC",
            )

            return await self._make_request(
                method="GET",
                url=url,
                headers=headers,
            )
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            if close_session:
                await self.close_session()

    async def get_appointments(self, get_appointments_request: GetAppointmentsRequest):
        logger.debug("Fetching list of appointments")
        try:
            eDate = get_appointments_request.eDate or get_default_date()
            maxCount = get_appointments_request.maxCount or 100

            logger.debug(
                f"Fetching {maxCount} doctor's appointments for user: {self.auth_tokens.TrUserId}"
            )

            headers = await self._setup_headers(
                content_type="application/x-www-form-urlencoded; charset=UTF-8"
            )

            url = ECW_URLS["get appointments"].format(
                sessionDID=self.auth_tokens.sessionDID,
                TrUserId=self.auth_tokens.TrUserId,
                timestamp=int(time.time() * 1000),
                clientTimezone="UTC",
            )

            payload = {
                "eDate": eDate,
                "doctorId": get_appointments_request.providerId,
                "sortBy": "time",
                "facilityId": get_appointments_request.facilityId,
                "apptTime": 0,
                "checkinstatus": 0,
                "FacilityGrpId": 0,
                "maxCount": maxCount,
                "nCounter": 0,
                "DeptId": 0,
                "fromWeb": "yes",
                "fromAfterCare": "officeVisit",
                "tabId": 3,
                "toDate": "",
                "selectedChkShowASCvisits": "false",
                "includeResourceAppt": "true",
            }

            encoded_payload = urlencode(payload)

            return await self._make_request(
                method="POST",
                url=url,
                headers=headers,
                data=encoded_payload,
            )
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            await self.close_session()

    async def get_patients(
        self, get_patients_request: GetPatientsRequest, close_session: bool = True
    ):
        try:
            logger.debug(
                f"Searching patients with last name '{get_patients_request.lastName}'"
                + (
                    f" and first name '{get_patients_request.firstName}'"
                    if get_patients_request.firstName
                    else ""
                )
            )
            headers = await self._setup_headers(
                content_type="application/x-www-form-urlencoded; charset=UTF-8"
            )

            url = ECW_URLS["get patients"].format(
                sessionDID=self.auth_tokens.sessionDID,
                TrUserId=self.auth_tokens.TrUserId,
                timestamp=int(time.time() * 1000),
                clientTimezone="UTC",
            )

            primary_search_value = get_patients_request.lastName
            if get_patients_request.firstName:
                primary_search_value += f", {get_patients_request.firstName}"

            payload = {
                "counter": 1,
                "firstName": get_patients_request.firstName or "",
                "lastName": get_patients_request.lastName,
                "primarySearchValue": primary_search_value,
                "SearchBy": "Name",
                "StatusSearch": "Active",
                "limitstart": 0,
                "limitrange": get_patients_request.maxCount,
                "MAXCOUNT": get_patients_request.maxCount,
                "device": "webemr",
                "callFromScreen": "PatientSearch",
                "action": "Patient",
                "donorProfileStatus": 2,
                "AddlSearchBy": "DateOfBirth",
                "AddlSearchVal": "",
                "userType": "",
                "orderBy": "",
            }

            encoded_payload = urlencode(payload)

            return await self._make_request(
                method="POST",
                url=url,
                headers=headers,
                data=encoded_payload,
            )
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            if close_session:
                await self.close_session()

    async def validate_provider(self, provider_name: str):
        logger.debug(f"Validating provider/resource <{provider_name}>")
        provider = await self.get_provider(
            providerName=provider_name, close_session=False
        )
        provider_response = None

        if provider and len(provider.get("result")) > 0:
            provider_response = provider.get("result")[0]["id"]

        return provider_response

    async def validate_reason(self, reason_client: str):
        logger.debug(f"Validating reason: {reason_client}")
        reasons = await self.get_reasons(close_session=False)
        reason_item = None
        for reason in reasons["reasons"]:
            if reason["name"].lower() == reason_client.lower():
                reason_item = reason["name"]
        return reason_item

    async def validate_visit_type(self, visit_type: str):
        logger.debug(f"Validating visit type <{visit_type}>")
        visit_type_res = None

        for visit in reduced_visit_types:
            if visit["Description"].lower() == visit_type.lower():
                visit_type_res = visit["Name"]

        return visit_type_res

    async def validate_facilities(self, facility_name: str):
        logger.debug(f"Validating user facility <{facility_name}>")
        facilities_list = await self.get_facilities(close_session=False)
        facilities_res = None

        for facility in facilities_list["facilities"]:
            if facility["Name"].lower() == facility_name.lower():
                facilities_res = {"id": facility["Id"], "pos": facility["POS"]}

        return facilities_res

    async def create_appointment(self, request: AppointmentRequest):
        logger.debug(
            f"{'Updating' if request.encounterId else 'Creating'} appointment for patient <{request.patient_name}>"
        )
        try:
            headers = await self._setup_headers()

            patient_response = await self.get_patients(
                GetPatientsRequest(
                    lastName=request.patient_name.split(",")[0],
                    firstName=request.patient_name.split(",")[-1],
                ),
                close_session=False,
            )

            if not patient_response.get("patients"):
                logger.debug(f"No patients found by name: {request.patient_name}")
                raise HTTPException(
                    404, {"message": f"Patient: {request.patient_name} not found"}
                )

            patient_id = patient_response.get("patients")[0]["id"]
            start = request.start_time.replace(" ", "%20")
            date = parse.quote(
                str(datetime.strptime(request.date, "%m/%d/%Y").strftime("%m/%d/%Y"))
            )
            id = self.auth_tokens.sessionDID
            patient_name = parse.quote(str(request.patient_name.upper()))

            url = ECW_URLS["get appointment"].format(
                start=start,
                id=id,
                patient_name=patient_name,
                date=date,
                patient_id=patient_id,
                sessionDID=self.auth_tokens.sessionDID,
                TrUserId=self.auth_tokens.TrUserId,
                timestamp=int(time.time() * 1000),
                clientTimezone="UTC",
            )

            logger.debug("Making request to get appointment form")
            logger.debug(f"Get Form URL: {url}")
            await self._make_request(
                method="GET",
                url=url,
                headers=headers,
            )

            facility_id = await self.validate_facilities(request.facility_name)
            if not facility_id:
                logger.debug(f"No facility found by name {request.facility_name}")
                raise HTTPException(
                    status_code=404, detail={"message": "Facility not found"}
                )

            provider_id = await self.validate_provider(request.provider)
            if not provider_id:
                logger.debug(f"No provider found by name {request.provider}")
                raise HTTPException(
                    status_code=404, detail={"message": "Provider not found"}
                )

            resource_name = request.resource or request.provider
            resource_id = await self.validate_provider(resource_name)
            if not resource_id:
                logger.debug(f"No resource found by name {request.provider}")
                raise HTTPException(
                    status_code=404, detail={"message": "Resource not found"}
                )

            reason_name = await self.validate_reason(request.reason)
            if not reason_name:
                logger.debug(f"No reason found by description/name: {request.reason}")
                raise HTTPException(
                    status_code=404, detail={"message": "Reason not found"}
                )

            visit_type = await self.validate_visit_type(request.visit_type)
            if not visit_type:
                logger.debug(f"No visit type found by name {request.visit_type}")
                raise HTTPException(
                    status_code=404, detail={"message": "Visit Type not found"}
                )

            logger.debug("Creating appointment XML formdata request body")

            create_payload = await create_new_appointment_formdata_v2(
                patient_id=patient_id,
                date_str=request.date,
                start_time_str=request.start_time,
                end_time_str=request.end_time,
                visit_type_name=visit_type,
                reason_str=reason_name,
                doctor_id_str=provider_id,
                status_code_str=request.visit_status,
                facility_id_str=str(facility_id["id"]),
                diagnosis_str=request.diagnosis,
                patient_email_str=request.email,
                tr_user_id_str=self.auth_tokens.TrUserId,
                resource_id_str=resource_id,
                pos_str=facility_id["pos"],
                # general_notes_str=request.general_notes
            )

            logger.debug("URL encoding appointment XML formdata")
            encoded_payload = parse.quote_plus(str(create_payload))
            form_data_payload = f"FormData={encoded_payload}"
            logger.debug(f"Formatted form data payload: {form_data_payload[:200]}...")

            if request.encounterId:
                url = ECW_URLS["update appointment"].format(
                    encounterId=request.encounterId,
                    sessionDID=self.auth_tokens.sessionDID,
                    TrUserId=self.auth_tokens.TrUserId,
                    timestamp=int(time.time() * 1000),
                    clientTimezone="UTC",
                )
            else:
                url = ECW_URLS["post appointment"].format(
                    sessionDID=self.auth_tokens.sessionDID,
                    TrUserId=self.auth_tokens.TrUserId,
                    timestamp=int(time.time() * 1000),
                    clientTimezone="UTC",
                )

            logger.debug(f"Final POST URL: {url}")

            fin_header = await self._setup_headers(
                content_type="application/x-www-form-urlencoded; charset=UTF-8"
            )
            fin_header["origin"] = "https://nybukaapp.eclinicalweb.com"
            fin_header["referer"] = (
                "https://nybukaapp.eclinicalweb.com/mobiledoc/jsp/webemr/index.jsp"
            )
            fin_header["x-requested-with"] = "XMLHttpRequest"
            fin_header["isajaxrequest"] = "true"

            return await self._make_request(
                method="POST",
                url=url,
                headers=fin_header,
                data=form_data_payload,
            )
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            await self.close_session()

    async def get_progress_notes(self, encounterId: str):
        logger.debug(f"Fetching progress notes for encounter: <{encounterId}>")
        try:
            headers = await self._setup_headers()
            url = ECW_URLS["get progress notes"].format(
                encounterId=encounterId,
                sessionDID=self.auth_tokens.sessionDID,
                TrUserId=self.auth_tokens.TrUserId,
                timestamp=int(time.time() * 1000),
                clientTimezone="UTC",
            )
            return await self._make_request(method="GET", url=url, headers=headers)
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            await self.close_session()

    async def update_history_add_only(
        self, request_data: AddSurgicalAndHospitilizationItemsRequest
    ):
        logger.debug("Updating surgical history and hospitilization info")
        try:
            headers = await self._setup_headers()
            batch_items_to_send = []
            timestamp_ms_base = int(time.time() * 1000)

            auth_params = {
                "sessionDID": self.auth_tokens.sessionDID,
                "TrUserId": self.auth_tokens.TrUserId,
            }
            common_device_params = {
                "Device": "webemr",
                "ecwappprocessid": "0",
                "clientTimezone": "UTC",
            }

            surgical_actually_changed = False
            if request_data.new_surgical_items:
                surgical_actually_changed = True

                get_surg_url_params = {
                    "encounterId": request_data.encounter_id,
                    **auth_params,
                    **common_device_params,
                    "timestamp": timestamp_ms_base,
                    "calledFromHospCtrl": "true",
                }
                get_surg_url = ECW_URLS["get_surgical_history"].format(
                    **get_surg_url_params
                )

                try:
                    logger.debug(f"Fetching surgical history: {get_surg_url}")
                    surg_response_xml = await self._make_request(
                        "GET", get_surg_url, headers=headers
                    )
                    existing_surgical_items = surg_response_xml.get(
                        "surgical_history", []
                    )
                except Exception as e:
                    logger.debug(
                        f"Error fetching/parsing existing surgical history: {e}"
                    )
                    existing_surgical_items = []

                combined_surgical_items = []
                current_max_idx = 0
                for item_dict in existing_surgical_items:
                    combined_surgical_items.append(item_dict)
                    if (
                        item_dict.get("displayIndex")
                        and int(item_dict["displayIndex"]) > current_max_idx
                    ):
                        current_max_idx = int(item_dict["displayIndex"])

                for new_item in request_data.new_surgical_items:
                    current_max_idx += 1
                    combined_surgical_items.append(
                        {
                            "reason": new_item.reason,
                            "date": new_item.date,
                            "cptcode": new_item.cptcode if new_item.cptcode else "",
                            "displayIndex": str(current_max_idx),
                        }
                    )

                form_data_xml_surg = generate_formdata_xml_for_history(
                    combined_surgical_items, "surgical"
                )
                batch_url_params_surg = {
                    "mode": "webemr",
                    "patientId": request_data.patient_id,
                    "EncounterId": request_data.encounter_id,
                    **auth_params,
                    **common_device_params,
                    "timestamp": timestamp_ms_base + 1,
                    "surgicalHxChanged": str(surgical_actually_changed).lower(),
                }

                query_string_surg = urlencode(batch_url_params_surg)
                batch_items_to_send.append(
                    {
                        "url": f"{ECW_URLS['set_surgical_history']}?{query_string_surg}",
                        "param": [
                            {"paramName": "FormData", "paramValue": form_data_xml_surg}
                        ],
                    }
                )

                encounter_details_xml_surg = generate_encounter_details_flag_xml(
                    request_data.encounter_id,
                    "Surgical History",
                    surgical_actually_changed,
                )
                batch_url_params_enc_surg = {
                    "mode": "webEMR",
                    "Id": request_data.encounter_id,
                    "sectionName": "Surgical History",
                    "historyChanged": str(surgical_actually_changed).lower(),
                    "ptId": request_data.patient_id,
                    **auth_params,
                    **common_device_params,
                    "timestamp": timestamp_ms_base + 2,
                }
                query_string_enc_surg = urlencode(batch_url_params_enc_surg)
                batch_items_to_send.append(
                    {
                        "url": f"{ECW_URLS['set_encounter_details']}?{query_string_enc_surg}",
                        "param": [
                            {
                                "paramName": "FormData",
                                "paramValue": encounter_details_xml_surg,
                            }
                        ],
                        "args": {},
                    }
                )

            hospitalization_actually_changed = False
            if request_data.new_hospitalization_items:
                hospitalization_actually_changed = True

                get_hosp_url_params = {
                    "encounterId": request_data.encounter_id,
                    **auth_params,
                    **common_device_params,
                    "timestamp": timestamp_ms_base + 3,
                    "calledFromHospCtrl": "true",
                }
                get_hosp_url = ECW_URLS["get_hospitalization_history"].format(
                    **get_hosp_url_params
                )

                try:
                    logger.debug(f"Fetching hospitalization history: {get_hosp_url}")
                    hosp_response_xml = await self._make_request(
                        "GET", get_hosp_url, headers=headers
                    )
                    existing_hosp_items = hosp_response_xml.get(
                        "hospitalization_history", []
                    )
                except Exception as e:
                    logger.debug(f"Error fetching/parsing existing hosp history: {e}")
                    existing_hosp_items = []

                combined_hosp_items = []
                current_max_idx_hosp = 0
                for item_dict in existing_hosp_items:
                    combined_hosp_items.append(item_dict)
                    if (
                        item_dict.get("displayIndex")
                        and int(item_dict["displayIndex"]) > current_max_idx_hosp
                    ):
                        current_max_idx_hosp = int(item_dict["displayIndex"])

                for new_item in request_data.new_hospitalization_items:
                    current_max_idx_hosp += 1
                    combined_hosp_items.append(
                        {
                            "reason": new_item.reason,
                            "date": new_item.date,
                            "displayIndex": str(current_max_idx_hosp),
                        }
                    )

                form_data_xml_hosp = generate_formdata_xml_for_history(
                    combined_hosp_items, "hospitalization"
                )

                batch_url_params_hosp = {
                    "mode": "webemr",
                    "patientId": request_data.patient_id,
                    "EncounterId": request_data.encounter_id,
                    **auth_params,
                    **common_device_params,
                    "timestamp": timestamp_ms_base + 4,
                    "hospHxChanged": str(hospitalization_actually_changed).lower(),
                }
                query_string_hosp = urlencode(batch_url_params_hosp)
                batch_items_to_send.append(
                    {
                        "url": f"{ECW_URLS['set_hospitalization_history']}?{query_string_hosp}",
                        "param": [
                            {"paramName": "FormData", "paramValue": form_data_xml_hosp}
                        ],
                    }
                )

                if hospitalization_actually_changed:
                    encounter_details_xml_hosp = generate_encounter_details_flag_xml(
                        request_data.encounter_id,
                        "Hospitalization",
                        hospitalization_actually_changed,
                    )
                    batch_url_params_enc_hosp = {
                        "mode": "webEMR",
                        "Id": request_data.encounter_id,
                        "sectionName": "Hospitalization",
                        "historyChanged": str(hospitalization_actually_changed).lower(),
                        "ptId": request_data.patient_id,
                        **auth_params,
                        **common_device_params,
                        "timestamp": timestamp_ms_base + 5,
                    }
                    query_string_enc_hosp = urlencode(batch_url_params_enc_hosp)
                    batch_items_to_send.append(
                        {
                            "url": f"{ECW_URLS['set_encounter_details']}?{query_string_enc_hosp}",
                            "param": [
                                {
                                    "paramName": "FormData",
                                    "paramValue": encounter_details_xml_hosp,
                                }
                            ],
                            "args": {},
                        }
                    )

            if not batch_items_to_send:
                return {"message": "No new history items to add."}

            json_x_payload_string = json.dumps(batch_items_to_send)
            final_form_data = {
                "_csrf": self.auth_tokens.x_csrf_token,
                "x": json_x_payload_string,
            }

            batch_update_url = ECW_URLS["batch_ajax"]

            final_headers = await self._setup_headers(
                content_type="application/x-www-form-urlencoded; charset=UTF-8"
            )
            final_headers["Referer"] = f"{BASE_URL}/mobiledoc/jsp/webemr/index.jsp"
            final_headers["X-Requested-With"] = "XMLHttpRequest"

            return await self._make_request(
                method="POST",
                url=batch_update_url,
                headers=final_headers,
                data=final_form_data,
            )
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            await self.close_session()

    async def add_family_history_note(self, request_data: AddFamilyHistoryNoteRequest):
        logger.debug("Adding family history note")
        try:
            form_data_notes_xml = generate_family_history_formdata_notes_xml(
                request_data.encounter_id, request_data.plain_text_notes
            )

            form_payload_dict = {
                "Id": request_data.encounter_id,
                "TrUserId": self.auth_tokens.TrUserId,
                "patientId": request_data.patient_id,
                "action": "SAVE",
                "isDashboard": "false",
                "familymodified": "true",
                "FormDataNotes": form_data_notes_xml,
            }

            final_form_data_string = urlencode(form_payload_dict)

            target_url = ECW_URLS["add family history notes"]

            final_headers = await self._setup_headers(
                content_type="application/x-www-form-urlencoded; charset=UTF-8"
            )
            final_headers["X-Requested-With"] = "XMLHttpRequest"

            logger.debug(f"Family History URL: {target_url}")
            logger.debug(
                f"Family History Form Data String (first 500 chars): {final_form_data_string[:500]}..."
            )

            response_data = await self._make_request(
                method="POST",
                url=target_url,
                headers=final_headers,
                data=final_form_data_string,
            )

            if isinstance(response_data, str) and not response_data.strip():
                return {
                    "status": "success",
                    "message": "Family history note likely saved (empty response received).",
                }
            return {
                "status": "unknown",
                "raw_response": response_data,
            }
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            await self.close_session()

    async def add_social_history_note(self, request_data: AddSocialHistoryNoteRequest):
        logger.debug("Adding social history note")
        try:
            timestamp_ms = int(time.time() * 1000)

            form_data_xml = generate_social_history_formdata_xml(
                request_data.encounter_id, request_data.plain_text_notes
            )

            auth_params = {
                "sessionDID": self.auth_tokens.sessionDID,
                "TrUserId": self.auth_tokens.TrUserId,
            }
            common_device_params = {
                "Device": "webemr",
                "ecwappprocessid": "0",
                "clientTimezone": "UTC",
            }

            batch_url_params = {
                "encounterId": request_data.encounter_id,
                "type": "Social",
                "patientId": request_data.patient_id,
                **auth_params,
                **common_device_params,
                "timestamp": timestamp_ms,
            }
            query_string = urlencode(batch_url_params)

            set_annual_notes_url = f"{ECW_URLS.get('set_annual_notes')}?{query_string}"

            batch_item = {
                "url": set_annual_notes_url,
                "param": [{"paramName": "FormData", "paramValue": form_data_xml}],
                "args": {},
            }

            x_payload_list = [batch_item]
            json_x_payload_string = json.dumps(x_payload_list)

            final_form_data_string = f"_csrf={quote_plus(self.auth_tokens.x_csrf_token)}&x={quote_plus(json_x_payload_string)}"

            batch_ajax_url = ECW_URLS["batch_ajax"]

            final_headers = await self._setup_headers(
                content_type="application/x-www-form-urlencoded; charset=UTF-8"
            )
            final_headers["X-Requested-With"] = "XMLHttpRequest"

            logger.debug(f"Social History Batch URL: {batch_ajax_url}")
            logger.debug(
                f"Social History Data String (first 300 chars): {final_form_data_string[:300]}..."
            )

            return await self._make_request(
                method="POST",
                url=batch_ajax_url,
                headers=final_headers,
                data=final_form_data_string,
            )
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            await self.close_session()

    async def search_allergies(self, search_text: str, n_limit: Optional[str] = "9"):
        logger.debug(f"Searching for allergy: {search_text}")
        try:
            timestamp_ms = int(time.time() * 1000)
            headers = await self._setup_headers()
            params = {
                "searchType": "0",
                "calledFrom": "MedReconciliation",
                "searchText": search_text,
                "TrUserId": self.auth_tokens.TrUserId,
                "RxTypeID": "12846",
                "nEncounterId": "0",
                "nLimit": n_limit,
                "rxDrugSearchType": "1",
                "hideMSClinical": "false",
                "facilityId": "0",
                "bObsolete": "0",
                "showDeletedDrug": "0",
                "enhancedMedicationSearchType": "searchAllergy",
                "startsWithContainsSearchEnabled": "-1",
                "fuzzySearchEnabled": "-1",
                "mnemonicSearchEnabled": "-1",
                "proximitySearchEnabled": "-1",
                "genericWithBrandSearchEnabled": "-1",
                "section": "AllergyDrugRxNotes1",
                "sessionDID": self.auth_tokens.sessionDID,
                "Device": "webemr",
                "ecwappprocessid": "0",
                "timestamp": timestamp_ms,
                "clientTimezone": "UTC",
            }
            query_string = urlencode(params)
            search_url = f"{ECW_URLS['allergy_quick_search']}?{query_string}"

            return await self._make_request("GET", search_url, headers=headers)
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            await self.close_session()

    async def update_med_hx_and_allergies(
        self, request_data: UpdateMedHxAllergyRequest
    ):
        try:
            logger.debug("Updating medical histor and/or allergy information")
            responses = {}
            timestamp_base = int(time.time() * 1000)

            auth_params = {
                "sessionDID": self.auth_tokens.sessionDID,
                "TrUserId": self.auth_tokens.TrUserId,
            }
            common_device_params = {
                "Device": "webemr",
                "ecwappprocessid": "0",
                "clientTimezone": "UTC",
            }

            if request_data.medical_history_text is not None:
                med_hx_xml = generate_medical_history_text_xml(
                    request_data.encounter_id, request_data.medical_history_text
                )
                med_hx_url_params = {
                    "historyChanged": "true",
                    "sectionName": "Medical History",
                    "Id": request_data.encounter_id,
                    "mode": "webEMR",
                    "ptId": request_data.patient_id,
                    "allergyChanged": "undefined",
                    **auth_params,
                    **common_device_params,
                    "timestamp": timestamp_base,
                }
                med_hx_url = f"{ECW_URLS['set_encounter_details_medical_history']}?{urlencode(med_hx_url_params)}"

                form_data_med_hx = urlencode({"FormData": med_hx_xml})

                headers_direct_post = await self._setup_headers(
                    content_type="application/x-www-form-urlencoded; charset=UTF-8"
                )
                headers_direct_post["X-Requested-With"] = "XMLHttpRequest"

                med_hx_resp = await self._make_request(
                    "POST",
                    med_hx_url,
                    headers=headers_direct_post,
                    data=form_data_med_hx,
                )
                responses["medical_history_set"] = med_hx_resp

            batch_items_for_flags = []
            med_hx_flag_xml = generate_batch_medhx_flag_xml(
                request_data.encounter_id,
                no_reported_med_hx=(
                    request_data.medical_history_text is None
                    or not request_data.medical_history_text.strip()
                ),
            )
            flag_url_params_medhx = {
                "historyChanged": "true",
                "sectionName": "Medical History",
                "Id": request_data.encounter_id,
                "mode": "webEMR",
                "ptId": request_data.patient_id,
                **auth_params,
                **common_device_params,
                "timestamp": timestamp_base + 1,
            }
            batch_items_for_flags.append(
                {
                    "url": f"{ECW_URLS['set_encounter_details']}?{urlencode(flag_url_params_medhx)}",
                    "param": [{"paramName": "FormData", "paramValue": med_hx_flag_xml}],
                }
            )

            nkda_is_set_by_user = False
            allergy_flags_xml = generate_batch_allergy_flags_xml(
                request_data.encounter_id,
                has_allergies=bool(request_data.new_allergies),
                nkda_flag_val="Y" if nkda_is_set_by_user else "N",
            )
            flag_url_params_allergy = {
                "allergyChanged": "true",
                "sectionName": "Allergies",
                "Id": request_data.encounter_id,
                "mode": "webEMR",
                "ptId": request_data.patient_id,
                **auth_params,
                **common_device_params,
                "timestamp": timestamp_base + 2,
            }
            batch_items_for_flags.append(
                {
                    "url": f"{ECW_URLS['set_encounter_details']}?{urlencode(flag_url_params_allergy)}",
                    "param": [
                        {"paramName": "FormData", "paramValue": allergy_flags_xml}
                    ],
                    "args": {},
                }
            )

            if batch_items_for_flags:
                json_x_flags = json.dumps(batch_items_for_flags)
                form_data_flags_batch = f"_csrf={quote_plus(self.auth_tokens.x_csrf_token)}&x={quote_plus(json_x_flags)}"
                batch_ajax_url = ECW_URLS["batch_ajax"]

                flags_batch_resp_text = await self._make_request(
                    "POST",
                    batch_ajax_url,
                    headers=headers_direct_post,
                    data=form_data_flags_batch,
                )
                responses["flags_batch_set"] = flags_batch_resp_text

            if request_data.new_allergies:
                responses["set_allergies"] = []
                # robust solution would be to GET existing allergies for this encounter first.
                current_allergy_display_index = 0

                for i, allergy_to_add in enumerate(request_data.new_allergies):
                    current_allergy_display_index += 1
                    allergy_item_xml = generate_set_allergy_item_xml(
                        request_data.patient_id,
                        request_data.encounter_id,
                        allergy_to_add,
                        current_allergy_display_index,
                    )
                    allergy_url_params = {
                        "patientId": request_data.patient_id,
                        "encounterId": request_data.encounter_id,
                        "allergyChanged": "true",
                        **auth_params,
                        **common_device_params,
                        "timestamp": timestamp_base + 3 + i,
                    }
                    allergy_url = f"{ECW_URLS['set_allergies_for_encounter']}?{urlencode(allergy_url_params)}"

                    form_data_allergy_item = urlencode(
                        {
                            "FormData": allergy_item_xml,
                        }
                    )

                    allergy_set_resp = await self._make_request(
                        "POST",
                        allergy_url,
                        headers=headers_direct_post,
                        data=form_data_allergy_item,
                    )
                    responses["set_allergies"].append(
                        {"item": allergy_to_add.drug_name, "response": allergy_set_resp}
                    )

            return responses
        except Exception as exc:
            logger.debug(exc)
            raise
        finally:
            await self.close_session()
