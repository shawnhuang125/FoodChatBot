# app/routes/health_routes.py
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

health_router = APIRouter()

@health_router.get("/health", status_code=status.HTTP_200_OK, tags=["Health"])
async def health_check():
    """
    提供給 Docker、Traefik 及負載均衡器的健康檢查端點。
    回傳 200 OK 代表服務已成功預熱就緒。
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "healthy", "service": "search-api"}
    )