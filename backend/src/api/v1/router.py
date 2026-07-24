from fastapi import APIRouter

from api.v1 import (
    account,
    conversations,
    graph,
    health,
    interpretations,
    messages,
    stories,
    turns,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(messages.router)
router.include_router(graph.router)
router.include_router(conversations.router)
router.include_router(interpretations.router)
router.include_router(stories.router)
router.include_router(turns.router)
router.include_router(account.router)
