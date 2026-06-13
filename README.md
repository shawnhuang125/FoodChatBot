# FoodChatBot - APP UI 介面

本專案之行動終端基於 Kotlin 語言開發，採用 Google 推崇的 Jetpack Compose 響應式 UI 框架，旨在建構一個高性能、零延遲的 AI 美食導覽介面

---

## 優勢與架構
- **原生 Kotlin 開發：發揮 APP 極致執行效能與相容性**
- **通訊架構 (HTTP & Socket):**
  - **即時反饋：透過 Socket.IO 建立即時通訊管道，達成 AI 串流回覆「逐字生成」的即時視覺效果**
  - **情境感知：結合 HTTP 請求 並動態注入 SID 與 GPS 參數，實現針對當前地理位置的個性化資料檢索，確保回傳內容具備高相關性與精準距離**
- **永久儲存收藏資料：Android Room 資料庫**
  - **持久化安全：採用官方 Room (SQLite) 實作，資料直接寫入手機底層硬碟，即使 App 關閉或裝置重啟，資料夾與收藏內容仍保持 100% 完整**
  - **響應式同步：利用 Kotlin Flow 監聽硬碟異動，資料一變動、畫面立刻重畫，達成「資料與視圖同步」的最高穩定性架構**


---

##  開發環境需求
- **Android Studio 4**
- **Android Emulator ( Pixel 9、Pixel 10)**

---

## Android Studio 開啟專案

### 1. 下載專案
從GitHub倉庫下載完整Code，或是將專案壓縮檔解壓縮

### 2. 開啟專案
在 Android Studio 中選擇 Open 並指向專案根目錄

### 3. Gradle 同步
點擊頂部的 Sync Project with Gradle Files 圖示
系統會自動下載所有依賴套件
**注意：同步過程需保持網路連線**

### 4. 專案運行
開啟手機模擬器，在 Android Studio 工具列頂部，確認左邊下拉選單是啟動的「虛擬機名稱」，右邊選單是 :app ，點擊頂部的綠色 Run 按鈕

---

### 運行監控
在 Android Studio 4 IDE 左下角，有一個 Logcat (像貓咪的Icone)，點擊後確認上面的下拉選單是選擇當前的 Android 虛擬手機
在下拉選單的旁邊輸入區，輸入 Logs 即可看到所有 Log 

---

## APK 安裝  (使用實體手機 或 Android 虛擬手)
### 1. 下載專案 APK
從 Google 專題資料夾，APK File 將 APK 檔下載下來並解壓縮

 - **如果是實體手機**
   - 直接點開解壓縮後的 APK 檔即可安裝
     
   <br>
   
 - **如果是 Android 虛擬手機**
   - 將解壓縮後的APK檔，拖曳到虛擬手機內，即可安裝



## 開發者資訊

* **專案負責人：** 林聖峰
* **學號：** 4120E013
* **系所：** 崑山科技大學 資工系 3A
* **開發分支：** `feature/shenfunlin-app`
