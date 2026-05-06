# app/utils/distance_utils.py
import logging

def get_haversine_distance_sql(user_lat,user_lng, lat_col="p.lat", lng_col="p.lng"):
    # 生成distance的函式
    # param user_lat: 使用者的緯度(Latitude)
    # param user_lng: 使用者的經度(Longitude)
    # param lat_col:店家的緯度
    # param lng_col:店家的經度
    # return: SQL字串 (單位:公里)
    R_METERS = 6371000 # 地球的半徑(單位:公尺)
    try:
        # 嘗試轉成浮點數
        lat = float(user_lat)
        lng = float(user_lng)
        
        # 加這行：紀錄一下現在是用哪個座標在算，方便除錯
        logging.debug(f"[Distance Utils] 生成距離公式 SQL - User 座標: ({lat}, {lng})")

    except (ValueError, TypeError) as e:
        # 如果傳進來的不是數字（例如傳到 None 或空字串），印出 Error Log 並回傳安全值
        logging.error(f"[Distance Utils] 座標格式錯誤，無法計算距離! Input: lat={user_lat}, lng={user_lng}, Error: {e}")
        # 回傳 0 或 NULL，避免 SQL 語法炸裂
        return "0"
    # 生成SQL
    # 使用MySQL的數學函式
    sql = f"""
    (
        ({R_METERS} * acos(
            cos(radians({lat})) * cos(radians({lat_col})) * cos(radians({lng_col}) - radians({lng})) + 
            sin(radians({lat})) * sin(radians({lat_col}))
        ))
    )
    """
    return sql.strip()