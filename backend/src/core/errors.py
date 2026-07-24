from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class ExtractionError(Exception):
    """LLM returned a response that could not be parsed into propositions."""


class DeduplicationError(Exception):
    """Vector similarity check failed during node/edge dedup."""


class GraphWriteError(Exception):
    """Neo4j upsert failed."""


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ExtractionError)
    async def extraction_error_handler(request: Request, exc: ExtractionError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": f"Extraction failed: {exc}"},
        )

    @app.exception_handler(DeduplicationError)
    async def dedup_error_handler(request: Request, exc: DeduplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"Deduplication error: {exc}"},
        )

    @app.exception_handler(GraphWriteError)
    async def graph_write_error_handler(request: Request, exc: GraphWriteError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"Graph write error: {exc}"},
        )
