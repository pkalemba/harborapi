from typing import List, Optional

from httpx import HTTPStatusError, Response
from loguru import logger

from harborapi.utils import is_json

from .models import Error, Errors


class HarborAPIException(Exception):
    pass


# FIXME: this SUCKS
class StatusError(HarborAPIException):
    __cause__: Optional[HTTPStatusError]
    errors: List[Error]

    def __init__(self, errors: Optional[Errors] = None, *args, **kwargs):
        self.errors = []
        if isinstance(errors, Errors) and errors.errors:
            self.errors = errors.errors
        super().__init__(*args, **kwargs)

    @property
    def status_code(self) -> Optional[int]:
        # should always return int, but we can't guarantee it
        try:
            return self.__cause__.response.status_code  # type: ignore
        except:
            return None


class BadRequest(StatusError):
    pass


class Unauthorized(StatusError):
    pass


class Forbidden(StatusError):
    pass


class NotFound(StatusError):
    pass


class PreconditionFailed(StatusError):
    pass


class InternalServerError(StatusError):
    pass


# NOTE: should this function be async?
def check_response_status(response: Response, missing_ok: bool = False) -> None:
    """Raises an exception if the response status is not 2xx.

    Exceptions are wrapped in a `StatusError` if the response contains errors.

    Parameters
    ----------
    response : Response
        The response to check.
    missing_ok : bool, optional
        If `True`, do not raise an exception if the status is 404.
    """
    try:
        response.raise_for_status()
    except HTTPStatusError as e:
        status_code = response.status_code
        if missing_ok and status_code == 404:
            logger.debug("{} not found", response.request.url)
            return
        errors = try_parse_errors(response)
        logger.bind(httpx_err=e, errors=errors).error(
            "Harbor API returned status code {} for {}",
            response.status_code,
            response.url,
        )
        exceptions = {
            400: BadRequest,
            401: Unauthorized,
            403: Forbidden,
            404: NotFound,
            412: PreconditionFailed,
            500: InternalServerError,
        }
        exc = exceptions.get(status_code, StatusError)
        raise exc from e


def try_parse_errors(response: Response) -> Optional[Errors]:
    """Attempts to return the errors from a response.

        See: `models.Errors`

        Parameters
        ----------
        response : Response
    ):
        Returns
        -------
        Optional[Errors]
            The errors from the response.
    """
    if is_json(response):
        try:
            return Errors(**response.json())
        except Exception as e:
            logger.bind(error=e).error(
                "Failed to parse error response from {} as JSON", response.url
            )
    return None
