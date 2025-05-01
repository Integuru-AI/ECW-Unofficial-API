from datetime import datetime, timezone
import json
import time
from typing import Literal
from urllib.parse import urlencode
import aiohttp
from fake_useragent import UserAgent
from fastapi import HTTPException
from fastapi.logger import logger
from fastapi.responses import JSONResponse
from integrations.ecw.ecw_config import ECW_URLS, AuthTokens
from integrations.ecw.ecw_utils import parse_appointments_xml
from submodule_integrations.ecw.ecw_models import (
    GetAppointmentsRequest,
    get_default_date,
)
from submodule_integrations.models.integration import Integration
from submodule_integrations.utils.errors import (
    IntegrationAPIError,
)


class ECWIntegration(Integration):
    def __init__(self, auth_tokens: AuthTokens, user_agent: str = UserAgent().chrome):
        super().__init__("ecw")
        self.user_agent = user_agent
        self.network_requester = None
        self.url = "https://nybukaapp.eclinicalweb.com/mobiledoc/jsp/catalog/xml"
        self.auth_tokens: AuthTokens = auth_tokens

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
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, **kwargs) as response:
                    return await self._handle_response(response)

    async def _handle_response(self, response: aiohttp.ClientResponse):
        response_text = await response.text()
        status = response.status

        parsed_data = None

        try:
            if response_text.strip().startswith("<?xml"):
                parsed_data = parse_appointments_xml(response_text)
            else:
                parsed_data = json.loads(response_text)
        except Exception as e:
            logger.warning(f"Response parsing failed: {str(e)}")
            parsed_data = {"error": {"message": "Parsing error", "raw": response_text}}

        if 200 <= status < 300:
            return parsed_data

        error_message = parsed_data.get("error", {}).get("message", "Unknown error")
        error_code = parsed_data.get("error", {}).get("code", str(status))

        logger.debug(f"{status} - {parsed_data}")

        if 400 <= status < 500:
            raise HTTPException(status_code=status, detail=parsed_data)
        elif status >= 500:
            raise IntegrationAPIError(
                self.integration_name,
                f"Downstream server error (translated to HTTP 501): {error_message}",
                501,
                error_code,
            )
        else:
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
            "Cip": self.auth_tokens.Cip,
        }
        if content_type:
            _headers["Content-type"] = content_type

        return _headers

    async def get_appointments(self, get_appointments_request: GetAppointmentsRequest):
        eDate = get_appointments_request.eDate or get_default_date()
        maxCount = get_appointments_request.maxCount or 100

        logger.debug(
            f"Fetching {maxCount} doctor's appointments for user: {self.auth_tokens.TrUserId}"
        )

        headers = await self._setup_headers(
            content_type="application/x-www-form-urlencoded; charset=UTF-8"
        )

        # Format dynamic URL
        url = ECW_URLS["get appointments"].format(
            sessionDID=self.auth_tokens.sessionDID,
            TrUserId=self.auth_tokens.TrUserId,
            timestamp=int(time.time() * 1000),
            clientTimezone="UTC",
        )

        payload = {
            "eDate": eDate,
            "doctorId": 0,
            "sortBy": "time",
            "facilityId": 0,
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
