# ./app/utils/security.py
from fastapi import Request, HTTPException, status
from app.config import Config
# 後端 API 允許的 IP 白名單


def verify_ip_whitelist(request: Request):
    # 1. 先驗證 request.client 是否存在 (消除 Pylance 警告)
    if request.client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not determine client IP address."
        )

    # 2. 此時 Pylance 確定 request.client 不是 None，可以安心存取 .host
    client_ip = request.client.host
    
    if client_ip not in Config.ALLOWED_IPS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Unauthorized IP"
        )