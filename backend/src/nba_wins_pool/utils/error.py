import logging

from fastapi import status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def detailed_error_handler(request, exc):
    """Log an unhandled exception with its traceback and return it as a 500 response.

    Args:
        request: The request that raised.
        exc: The unhandled exception.

    Returns:
        JSONResponse with status 500 and the exception string as "detail".
    """
    logger.error("Unhandled error for %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc)},
    )
