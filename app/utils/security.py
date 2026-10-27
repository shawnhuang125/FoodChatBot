# ./app/utils/security.py
from fastapi import Request, HTTPException, status
from app.config import Config

def verify_ip_whitelist(request: Request):
    # 1. 優先從 Nginx 轉發的 Header 取得真實外部 IP，若無則降級使用連線 IP
    client_ip = request.headers.get("x-real-ip")
    
    if not client_ip:
        if request.client is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not determine client IP address."
            )
        client_ip = request.client.host

    # 2. 驗證真實客戶端 IP 是否在允許名單內
    if client_ip not in Config.ALLOWED_IPS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access Denied: Unauthorized IP ({client_ip})"
        )