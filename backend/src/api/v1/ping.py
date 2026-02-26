from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def ping() -> dict[str, str]:
    """Verification endpoint — confirms v1 router is wired."""
    return {"ping": "pong", "api_version": "v1"}
