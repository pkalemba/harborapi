import asyncio
from typing import Any, Dict, List, Optional, Type, TypeVar, Union

import backoff
import httpx
from httpx import RequestError, Response
from loguru import logger
from pydantic import BaseModel, ValidationError

from harborapi.models.models import Artifact, Label

from .exceptions import HarborAPIException, check_response_status
from .models import (
    Accessory,
    CVEAllowlist,
    HarborVulnerabilityReport,
    IsDefault,
    OverallHealthStatus,
    Permission,
    ScannerAdapterMetadata,
    ScannerRegistration,
    ScannerRegistrationReq,
    ScannerRegistrationSettings,
    Schedule,
    Stats,
    Tag,
    UserResp,
    UserSearchRespItem,
)
from .types import JSONType
from .utils import get_artifact_path, get_credentials, handle_optional_json_response

__all__ = ["HarborAsyncClient"]

T = TypeVar("T", bound=BaseModel)


def construct_model(cls: Type[T], data: Any) -> T:
    try:
        return cls.parse_obj(data)
    except ValidationError as e:
        logger.error(
            "Failed to validate {} given {}, error: {}", cls.__class__.__name__, data, e
        )
        raise e


class _HarborClientBase:
    """Base class used by both the AsyncClient and the Client classes."""

    # NOTE: Async and sync clients were originally intended to be implemented
    #       as separate classes that both inherit from this class.
    #       However, given the way the sync client ended up being implemented,
    #       the functionality of this class should be baked into the async client.

    def __init__(
        self,
        url: str,
        username: str = None,
        secret: str = None,
        credentials: str = None,
        config: Optional[Any] = None,
        version: str = "v2.0",
    ) -> None:
        self.username = username
        if username and secret:
            self.credentials = get_credentials(username, secret)
        elif credentials:
            self.credentials = credentials
        else:
            raise ValueError("Must provide either username and secret or credentials")

        # TODO: add URL regex and improve parsing OR don't police this at all
        url = url.strip("/")  # remove trailing slash
        if version and not "/api/v" in url:
            if "/api" in url:
                url = url.strip("/") + "/" + version
            else:
                url = url + "/api/" + version
        self.url = url.strip("/")  # make sure we haven't added a trailing slash again

        self.config = config


class HarborAsyncClient(_HarborClientBase):
    def __init__(
        self,
        url: str,
        username: str = None,
        secret: str = None,
        credentials: str = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(url, username, secret, credentials, **kwargs)
        self.client = httpx.AsyncClient()

    # NOTE: add destructor that closes client?

    # CATEGORY: user

    # GET /users/search?username=<username>
    async def get_users_by_username(
        self, username: str, **kwargs: Any
    ) -> List[UserSearchRespItem]:
        users_resp = await self.get(
            "/users/search",
            params={"username": username, **kwargs},
        )
        return [construct_model(UserSearchRespItem, u) for u in users_resp]

    # GET /users
    async def get_users(self, sort: Optional[str] = None, **kwargs) -> List[UserResp]:
        params = {**kwargs}
        if sort:
            params["sort"] = sort
        users_resp = await self.get("/users", params=params)
        return [construct_model(UserResp, u) for u in users_resp]

    # GET /users/current
    async def get_current_user(self) -> UserResp:
        user_resp = await self.get("/users/current")
        return construct_model(UserResp, user_resp)

    # GET /users/current/permissions
    async def get_current_user_permissions(
        self, scope: Optional[str], relative: bool = False
    ) -> List[Permission]:
        """Get current user permissions.

        Parameters
        ----------
        scope : Optional[str]
            The scope for the permission
        relative : bool, optional
            Display resource paths relative to the scope, by default False
            Has no effect if `scope` is not specified

        Returns
        -------
        List[Permission]
            A list of Permission objects for the current user.
        """
        params = {}  # type: Dict[str, Any]
        if scope:
            params["scope"] = scope
            params["relative"] = relative
        resp = await self.get("/api/users/current/permissions", params=params)
        return [construct_model(Permission, p) for p in resp]

    # CATEGORY: gc

    # CATEGORY: scanAll

    # GET /scans/all/metrics
    async def get_scan_all_metrics(self) -> Stats:
        resp = await self.get("/scans/all/metrics")
        return construct_model(Stats, resp)

    # PUT /system/scanAll/schedule
    async def update_scan_all_schedule(self, schedule: Schedule) -> None:
        """Update the scan all schedule."""
        await self.put("/system/scanAll/schedule", json=schedule)

    # POST /system/scanAll/schedule
    async def create_scan_all_schedule(self, schedule: Schedule) -> str:
        """Create a new scan all job schedule. Returns location of the created schedule."""
        resp = await self.post("/system/scanAll/schedule", json=schedule)
        return resp.headers.get("Location")

    # GET /system/scanAll/schedule
    async def get_scan_all_schedule(self) -> Schedule:
        resp = await self.get("/system/scanAll/schedule")
        return construct_model(Schedule, resp)

    # POST /system/scanAll/stop
    async def stop_scan_all_job(self) -> None:
        await self.post("/system/scanAll/stop")

    # CATEGORY: configure
    # CATEGORY: usergroup
    # CATEGORY: preheat
    # CATEGORY: replication
    # CATEGORY: label
    # CATEGORY: robot
    # CATEGORY: webhookjob
    # CATEGORY: icon
    # CATEGORY: project
    # CATEGORY: webhook

    # CATEGORY: scan

    # POST /projects/{project_name}/repositories/{repository_name}/artifacts/{reference}/scan
    async def scan_artifact(
        self, project_name: str, repository_name: str, reference: str
    ) -> None:
        """Scan an artifact.

        Parameters
        ----------
        project_name : str
            The name of the project
        repository_name : str
            The name of the repository
        reference : str
            The reference of the artifact, can be digest or tag
        """
        path = get_artifact_path(project_name, repository_name, reference)
        resp = await self.post(f"{path}/scan")
        if resp.status_code != 202:
            logger.warning(
                "Scan request for {} returned status code {}, expected 202",
                path,
                resp.status_code,
            )

    # GET /projects/{project_name}/repositories/{repository_name}/artifacts/{reference}/scan/{report_id}/log
    async def get_artifact_scan_report_log(
        self, project_name: str, repository_name: str, reference: str, report_id: str
    ) -> str:
        """Get the log of a scan report."""
        # TODO: investigate what exactly this endpoint returns
        path = get_artifact_path(project_name, repository_name, reference)
        return await self.get_text(f"{path}/scan/{report_id}/log")

    # # POST /projects/{project_name}/repositories/{repository_name}/artifacts/{reference}/scan/stop
    async def stop_artifact_scan(
        self, project_name: str, repository_name: str, reference: str
    ) -> None:
        """Stop a scan for a particular artifact."""
        path = get_artifact_path(project_name, repository_name, reference)
        resp = await self.post(f"{path}/scan/stop")
        if resp.status_code != 202:
            logger.warning(
                "Stop scan request for {} returned status code {}, expected 202",
                path,
                resp.status_code,
            )

    # CATEGORY: member
    # CATEGORY: ldap
    # CATEGORY: registry
    # CATEGORY: search
    # CATEGORY: artifact

    # POST /projects/{project_name}/repositories/{repository_name}/artifacts/{reference}/tags
    async def create_artifact_tag(
        self, project_name: str, repository_name: str, reference: str, tag: Tag
    ) -> str:
        """Create a tag for an artifact.

        Parameters
        ----------
        project_name : str
            The name of the project
        repository_name : str
            The name of the repository
        reference : str
            The reference of the artifact, can be digest or tag
        tag : Tag
            The tag to create
        """
        path = get_artifact_path(project_name, repository_name, reference)
        resp = await self.post(f"{path}/tags", json=tag)
        if resp.status_code != 201:
            logger.warning(
                "Create tag request for {} returned status code {}, expected 201",
                path,
                resp.status_code,
            )
        return resp.headers.get("Location")

    # GET /projects/{project_name}/repositories/{repository_name}/artifacts/{reference}/tags
    async def get_artifact_tags(
        self,
        project_name: str,
        repository_name: str,
        reference: str,
        query: Optional[str] = None,
        sort: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
        with_signature: bool = False,
        with_immutable_status: bool = False,
    ) -> List[Tag]:
        """Get the tags for an artifact.

        Parameters
        ----------
        project_name : str
            The name of the project
        repository_name : str
            The name of the repository
        reference : str
            The reference of the artifact, can be digest or tag
        query : Optional[str]
            A query string to filter the tags
        sort : Optional[str]
            The sort order of the tags. TODO: document this parameter
        page : int
            The page of results to return, default 1
        page_size : int
            The number of results to return per page, default 10
        with_signature : bool
            Whether to include the signature of the tag in the response
        with_immutable_status : bool
            Whether to include the immutable status of the tag in the response

        Returns
        -------
        List[Tag]
            A list of Tag objects for the artifact.
        """
        path = get_artifact_path(project_name, repository_name, reference)
        params = {
            "page": page,
            "page_size": page_size,
            "with_signature": with_signature,
            "with_immutable_status": with_immutable_status,
        }  # type: Dict[str, Any]
        if query:
            params["q"] = query
        if sort:
            params["sort"] = sort
        resp = await self.get(f"{path}/tags")
        return [construct_model(Tag, t) for t in resp]

    # GET /projects/{project_name}/repositories/{repository_name}/artifacts/{reference}/tags
    async def get_artifact_accessories(
        self,
        project_name: str,
        repository_name: str,
        reference: str,
        query: Optional[str] = None,
        sort: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> List[Accessory]:
        """Get the tags for an artifact.

        Parameters
        ----------
        project_name : str
            The name of the project
        repository_name : str
            The name of the repository
        reference : str
            The reference of the artifact, can be digest or tag
        query : Optional[str]
            A query string to filter the tags
        sort : Optional[str]
            The sort order of the tags.
        page : int
            The page of results to return, default 1
        page_size : int
            The number of results to return per page, default 10

        Returns
        -------
        List[Accessory]
            A list of Accessory objects for the artifact.
        """
        path = get_artifact_path(project_name, repository_name, reference)
        params = {
            "page": page,
            "page_size": page_size,
        }  # type: Dict[str, Any]
        if query:
            params["q"] = query
        if sort:
            params["sort"] = sort
        resp = await self.get(f"{path}/accessories")
        return [construct_model(Accessory, a) for a in resp]

    # DELETE /projects/{project_name}/repositories/{repository_name}/artifacts/{reference}/tags
    async def delete_artifact_tag(
        self,
        project_name: str,
        repository_name: str,
        reference: str,
        tag_name: str,
        missing_ok: bool = False,
    ) -> None:
        """Get the tags for an artifact.

        Parameters
        ----------
        project_name : str
            The name of the project
        repository_name : str
            The name of the repository
        reference : str
            The reference of the artifact, can be digest or tag
        tag_name : str
            The name of the tag to delete
        """
        path = get_artifact_path(project_name, repository_name, reference)
        # TODO: implement missing_ok for all delete methods
        await self.delete(f"{path}/tags/{tag_name}", missing_ok=missing_ok)

    # POST /projects/{project_name}/repositories/{repository_name}/artifacts
    async def copy_artifact(
        self, project_name: str, repository_name: str, source: str
    ) -> Optional[str]:
        """Copy an artifact.

        Parameters
        ----------
        project_name : str
            Name of new artifact's project
        repository_name : str
            Name of new artifact's repository
        source : str
            The source artifact to copy from in the form of
            `"project/repository:tag"` or `"project/repository@digest"`

        Returns
        -------
        Optional[str]
            The location of the new artifact
        """
        path = f"/projects/{project_name}/repositories/{repository_name}/artifacts"
        resp = await self.post(f"{path}", params={"from": source})
        if resp.status_code != 201:
            logger.warning(
                "Copy artifact request for {} returned status code {}, expected 201",
                path,
                resp.status_code,
            )
        return resp.headers.get("Location")

    # GET /projects/{project_name}/repositories/{repository_name}/artifacts
    async def get_artifacts(
        self,
        project_name: str,
        repository_name: str,
        query: Optional[str] = None,
        sort: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
        with_tag: bool = True,
        with_label: bool = False,
        with_scan_overview: bool = False,
        with_signature: bool = False,
        with_immutable_status: bool = False,
        with_accessory: bool = False,
        mime_type: str = "application/vnd.security.vulnerability.report; version=1.1",
    ) -> List[Artifact]:
        """Get the artifacts for a repository.

        Parameters
        ----------
        project_name : str
            The name of the project
        repository_name : str
            The name of the repository
        query : Optional[str]
            A query string to filter the artifacts

            Except the basic properties, the other supported queries includes:
            * `"tags=*"` to list only tagged artifacts
            * `"tags=nil"` to list only untagged artifacts
            * `"tags=~v"` to list artifacts whose tag fuzzy matches "v"
            * `"tags=v"` to list artifact whose tag exactly matches "v"
            * `"labels=(id1, id2)"` to list artifacts that both labels with id1 and id2 are added to

        sort : Optional[str]
            The sort order of the artifacts.
        page : int
            The page of results to return, default 1
        page_size : int
            The number of results to return per page, default 10
        with_tag : bool
            Whether to include the tags of the artifact in the response
        with_label : bool
            Whether to include the labels of the artifact in the response
        with_scan_overview : bool
            Whether to include the scan overview of the artifact in the response
        with_signature : bool
            Whether the signature is included inside the tags of the returning artifacts.
            Only works when setting `with_tag==True`.
        with_immutable_status : bool
            Whether the immutable status is included inside the tags of the returning artifacts.
        with_accessory : bool
            Whether the accessories are included of the returning artifacts.
        mime_type : str
            A comma-separated lists of MIME types for the scan report or scan summary.
            The first mime type will be used when the report found for it.
            Currently the mime type supports:
            * `'application/vnd.scanner.adapter.vuln.report.harbor+json; version=1.0'`
            * `'application/vnd.security.vulnerability.report; version=1.1'`
        """
        path = f"/projects/{project_name}/repositories/{repository_name}/artifacts"
        params = {
            "page": page,
            "page_size": page_size,
            "with_tag": with_tag,
            "with_label": with_label,
            "with_scan_overview": with_scan_overview,
            "with_signature": with_signature,
            "with_immutable_status": with_immutable_status,
            "with_accessory": with_accessory,
        }  # type: Dict[str, Union[str, int, bool]]
        if query:
            params["q"] = query
        if sort:
            params["sort"] = sort
        resp = await self.get(
            f"{path}", params=params, headers={"X-Accept-Vulnerabilities": mime_type}
        )
        return [construct_model(Artifact, a) for a in resp]

    # POST /projects/{project_name}/repositories/{repository_name}/artifacts/{reference}/labels
    async def add_artifact_label(
        self,
        project_name: str,
        repository_name: str,
        reference: str,
        label: Label,
    ) -> None:
        """Add a label to an artifact.

        Parameters
        ----------
        project_name : str
            The name of the project
        repository_name : str
            The name of the repository
        reference : str
            The reference of the artifact, can be digest or tag
        label : Label
            The label to add
        """
        path = get_artifact_path(project_name, repository_name, reference)
        await self.post(
            f"{path}/labels",
            json=label,
        )
        # response should have status code 201, but API spec says it's 200
        # so we don't check it

    async def get_artifact(
        self,
        project_name: str,
        repository_name: str,
        reference: str,
        page: int = 1,
        page_size: int = 10,
        with_tag: bool = True,
        with_label: bool = False,
        with_scan_overview: bool = False,
        with_signature: bool = False,
        with_immutable_status: bool = False,
        with_accessory: bool = False,
        mime_type: str = "application/vnd.security.vulnerability.report; version=1.1",
    ) -> Artifact:
        """Get an artifact.

        Parameters
        ----------
        project_name : str
            The name of the project
        repository_name : str
            The name of the repository
        reference : str
            The reference of the artifact, can be digest or tag
        page : int
            The page of results to return, default 1
        page_size : int
            The number of results to return per page, default 10
        with_tag : bool
            Whether to include the tags of the artifact in the response
        with_label : bool
            Whether to include the labels of the artifact in the response
        with_scan_overview : bool
            Whether to include the scan overview of the artifact in the response
        with_signature : bool
            Whether the signature is included inside the tags of the returning artifact.
            Only works when setting `with_tag==True`.
        with_immutable_status : bool
            Whether the immutable status is included inside the tags of the returning artifact.
        with_accessory : bool
            Whether the accessories are included of the returning artifact.
        mime_type : str
            A comma-separated lists of MIME types for the scan report or scan summary.
            The first mime type will be used when the report found for it.
            Currently the mime type supports:
            * `'application/vnd.scanner.adapter.vuln.report.harbor+json; version=1.0'`
            * `'application/vnd.security.vulnerability.report; version=1.1'`
        """
        path = get_artifact_path(project_name, repository_name, reference)
        resp = await self.get(
            f"{path}",
            params={
                "page": page,
                "page_size": page_size,
                "with_tag": with_tag,
                "with_label": with_label,
                "with_scan_overview": with_scan_overview,
                "with_signature": with_signature,
                "with_immutable_status": with_immutable_status,
                "with_accessory": with_accessory,
            },
            headers={"X-Accept-Vulnerabilities": mime_type},
        )
        return construct_model(Artifact, resp)

    async def delete_artifact(
        self,
        project_name: str,
        repository_name: str,
        reference: str,
        missing_ok: bool = False,
    ) -> None:
        """Delete an artifact.

        Parameters
        ----------
        project_name : str
            The name of the project
        repository_name : str
            The name of the repository
        reference : str
            The reference of the artifact, can be digest or tag
        missing_ok : bool
            Whether to ignore 404 error when deleting the artifact
        """
        path = get_artifact_path(project_name, repository_name, reference)
        await self.delete(path, missing_ok=missing_ok)

    # GET /projects/{project_name}/repositories/{repository_name}/artifacts/{reference}/additions/vulnerabilities
    async def get_artifact_vulnerabilities(
        self,
        project_name: str,
        repository_name: str,
        reference: str,  # Make this default to "latest"?
        # TODO: support multiple mime types?
        mime_type: str = "application/vnd.security.vulnerability.report; version=1.1",
    ) -> Optional[HarborVulnerabilityReport]:
        """Get the vulnerabilities for an artifact."""
        path = get_artifact_path(project_name, repository_name, reference)
        url = f"{path}/additions/vulnerabilities"
        resp = await self.get(url, headers={"X-Accept-Vulnerabilities": mime_type})

        if not isinstance(resp, dict):
            logger.bind(response=resp).warning("{} returned non-dict response", url)
            return None

        # Get the report, which is stored under the key of the mime type
        report = resp.get(mime_type)
        if not report:
            logger.warning("{} returned no report", url)  # Is this an error?
            return None

        return construct_model(HarborVulnerabilityReport, report)

    # CATEGORY: immutable
    # CATEGORY: retention

    # CATEGORY: scanner

    # POST /scanners
    async def create_scanner(self, scanner: ScannerRegistrationReq) -> str:
        """Creates a new scanner. Returns location of the created scanner."""
        resp = await self.post("/scanners", json=scanner)
        return resp.headers.get("Location")

    # GET /scanners
    async def get_scanners(self, *args, **kwargs) -> List[ScannerRegistration]:
        scanners = await self.get("/scanners", params=kwargs)
        return [construct_model(ScannerRegistration, s) for s in scanners]

    # PUT /scanners/{registration_id}
    async def update_scanner(
        self, registration_id: Union[int, str], scanner: ScannerRegistrationReq
    ) -> None:
        await self.put(f"/scanners/{registration_id}", json=scanner)

    # GET /scanners/{registration_id}
    async def get_scanner(
        self, registration_id: Union[int, str]
    ) -> ScannerRegistration:
        scanner = await self.get(f"/scanners/{registration_id}")
        return construct_model(ScannerRegistration, scanner)

    # DELETE /scanners/{registration_id}
    async def delete_scanner(
        self,
        registration_id: Union[int, str],
        missing_ok: bool = False,
    ) -> Optional[ScannerRegistration]:
        scanner = await self.delete(
            f"/scanners/{registration_id}", missing_ok=missing_ok
        )
        # TODO: differentiate between 404 and no return value (how?)
        if not scanner:
            if missing_ok:
                return None
            raise HarborAPIException(
                "Deletion request returned no data. Is the scanner registered?"
            )
        return construct_model(ScannerRegistration, scanner)

    # PATCH /scanners/{registration_id}
    async def set_default_scanner(
        self, registration_id: Union[int, str], is_default: bool = True
    ) -> None:
        await self.patch(
            f"/scanners/{registration_id}", json=IsDefault(is_default=is_default)
        )

    # POST /scanners/ping
    async def ping_scanner_adapter(self, settings: ScannerRegistrationSettings) -> None:
        await self.post("/scanners/ping", json=settings)

    # GET /scanners/{registration_id}/metadata
    async def get_scanner_metadata(
        self, registration_id: int
    ) -> ScannerAdapterMetadata:
        scanner = await self.get(f"/scanners/{registration_id}/metadata")
        return construct_model(ScannerAdapterMetadata, scanner)

    # CATEGORY: systeminfo
    # CATEGORY: statistic
    # CATEGORY: quota
    # CATEGORY: repository

    # CATEGORY: ping
    # GET /ping
    async def ping_harbor_api(self) -> str:
        """Pings the Harbor API to check if it is alive."""
        # TODO: add plaintext GET method so we don't have to do this here
        return await self.get_text("/ping")

    # CATEGORY: oidc

    # CATEGORY: SystemCVEAllowlist
    # PUT /system/CVEAllowlist
    async def update_cve_allowlist(self, allowlist: CVEAllowlist) -> None:
        """Overwrites the existing CVE allowlist with a new one."""
        await self.put("/system/CVEAllowlist", json=allowlist)

    # GET /system/CVEAllowlist
    async def get_cve_allowlist(self) -> CVEAllowlist:
        resp = await self.get("/system/CVEAllowlist")
        return construct_model(CVEAllowlist, resp)

    # CATEGORY: health
    # GET /health
    async def health_check(self) -> OverallHealthStatus:
        resp = await self.get("/health")
        return construct_model(OverallHealthStatus, resp)

    # CATEGORY: robotv1
    # CATEGORY: projectMetadata
    # CATEGORY: auditlog

    def _get_headers(self, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = headers or {}
        base_headers = {
            "Authorization": "Basic " + self.credentials,
            "Accept": "application/json",
        }
        base_headers.update(headers)  # Override defaults with provided headers
        return base_headers

    @backoff.on_exception(backoff.expo, RequestError, max_time=30)
    async def get(
        self,
        path: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        follow_links: bool = True,
        **kwargs,
    ) -> JSONType:
        return await self._get(
            path,
            params=params,
            headers=headers,
            follow_links=follow_links,
            **kwargs,
        )

    @backoff.on_exception(backoff.expo, RequestError, max_time=30)
    async def get_text(
        self,
        path: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        **kwargs,
    ) -> str:
        """Bad workaround in order to have a cleaner API for text/plain responses."""
        resp = await self._get(path, params=params, headers=headers, **kwargs)
        return resp  # type: ignore

    # TODO: refactor this method so it looks like the other methods, while still supporting pagination.
    async def _get(
        self,
        path: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        follow_links: bool = True,
        **kwargs,
    ) -> JSONType:
        """Sends a GET request to the Harbor API.
        Returns JSON unless the response is text/plain.

        Parameters
        ----------
        path : str
            URL path to resource
        params : Optional[dict], optional
            Request parameters, by default None
        headers : Optional[dict], optional
            Request headers, by default None
        follow_links : bool, optional
            Enable pagination by following links in response header, by default True

        Returns
        -------
        JSONType
            JSON data returned by the API
        """
        # async with httpx.AsyncClient() as client:
        resp = await self.client.get(
            self.url + path,
            params=params,
            headers=self._get_headers(headers),
        )
        check_response_status(resp)
        j = handle_optional_json_response(resp)
        if j is None:
            return resp.text  # type: ignore # FIXME: resolve this ASAP (use overload?)

        # If we have "Link" in headers, we need to handle paginated results
        if (link := resp.headers.get("link")) and follow_links:
            logger.debug("Handling paginated results. URL: {}", link)
            j = await self._handle_pagination(j, link)  # recursion (refactor?)

        return j

    async def _handle_pagination(self, data: JSONType, link: str) -> JSONType:
        """Handles paginated results by recursing until all results are returned."""
        # NOTE: can this be done more elegantly?
        # TODO: re-use async client somehow
        j = await self.get(link)  # ignoring params and only using the link
        if not isinstance(j, list) or not isinstance(data, list):
            logger.warning(
                "Unable to handle paginated results, received non-list value. URL: {}",
                link,
            )
            # TODO: add more diagnostics info here
            return data
        data.extend(j)
        return data

    # NOTE: POST is not idempotent, should we still retry?
    # TODO: fix abstraction of post/_post. Put everything into _post?
    @backoff.on_exception(backoff.expo, RequestError, max_tries=1)
    async def post(
        self,
        path: str,
        json: Optional[Union[BaseModel, JSONType]] = None,
        params: Optional[dict] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Response:
        """Sends a POST request to a path, optionally with a JSON body."""
        return await self._post(
            path,
            json=json,
            params=params,
            headers=headers,
        )

    async def _post(
        self,
        path: str,
        json: Optional[Union[BaseModel, JSONType]] = None,
        params: Optional[dict] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Response:
        if isinstance(json, BaseModel):
            json = json.dict()
        resp = await self.client.post(
            self.url + path,
            json=json,
            params=params,
            headers=self._get_headers(headers),
        )
        check_response_status(resp)
        return resp

    @backoff.on_exception(backoff.expo, RequestError, max_time=30)
    async def put(
        self,
        path: str,
        json: Union[BaseModel, JSONType],
        params: Optional[dict] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> Optional[JSONType]:
        resp = await self._put(
            path,
            json=json,
            params=params,
            headers=headers,
            **kwargs,
        )
        return handle_optional_json_response(resp)

    async def _put(
        self,
        path: str,
        json: Union[BaseModel, JSONType],
        params: Optional[dict] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> Response:
        if isinstance(json, BaseModel):
            json = json.dict()
        resp = await self.client.put(
            self.url + path,
            json=json,
            params=params,
            headers=self._get_headers(headers),
            **kwargs,
        )
        check_response_status(resp)
        return resp

    @backoff.on_exception(backoff.expo, RequestError, max_time=30)
    async def patch(
        self,
        path: str,
        json: Union[BaseModel, JSONType],
        params: Optional[dict] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> Optional[JSONType]:
        resp = await self._patch(
            path,
            json=json,
            headers=headers,
            params=params,
            **kwargs,
        )
        return handle_optional_json_response(resp)

    async def _patch(
        self,
        path: str,
        json: Union[BaseModel, JSONType],
        params: Optional[dict] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> Response:
        if isinstance(json, BaseModel):
            json = json.dict()

        resp = await self.client.patch(
            self.url + path,
            json=json,
            params=params,
            headers=self._get_headers(headers),
            **kwargs,
        )
        check_response_status(resp)
        return resp

    @backoff.on_exception(backoff.expo, RequestError, max_time=30)
    async def delete(
        self,
        path: str,
        params: Optional[dict] = None,
        headers: Optional[Dict[str, str]] = None,
        missing_ok: bool = False,
        **kwargs,
    ) -> Optional[JSONType]:
        resp = await self._delete(
            path,
            headers=headers,
            params=params,
            missing_ok=missing_ok,
            **kwargs,
        )
        return handle_optional_json_response(resp)

    async def _delete(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[dict] = None,
        missing_ok: bool = False,
        **kwargs,
    ) -> Response:
        resp = await self.client.delete(
            self.url + path,
            params=params,
            headers=self._get_headers(headers),
            **kwargs,
        )
        check_response_status(resp, missing_ok=missing_ok)
        return resp

    # TODO: add on_giveup callback for all backoff methods
