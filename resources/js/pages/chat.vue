<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue';
import { io, Socket } from 'socket.io-client';
import { Head } from '@inertiajs/vue3';

interface Message {
    id: number;
    user: string;
    content: string;
    time: string;
    isMe: boolean;
}

const isSidebarOpen = ref(false);

const toggleSidebar = () => {
    isSidebarOpen.value = !isSidebarOpen.value;
};

const messages = ref<Message[]>([
    { id: 1, user: 'AI Assistant', content: '歡迎來到台南美食助手！請輸入您想查詢的內容。', time: '系統', isMe: false }
]);

const newMessage = ref('');
const inputRef = ref<HTMLTextAreaElement | null>(null);
const messageContainer = ref<HTMLElement | null>(null);
const isConnected = ref(false);
const isGenerating = ref(false); // 新增：對齊模擬器的生成狀態

const isRefreshing = ref(false); // 定義重新整理的動畫狀態

const isWaiting = ref(false); // 新增：等待 AI 第一波回應的狀態

// 定義重新連線的邏輯 (對齊模擬器手動重連需求)
// 修改 reconnect 函式
const reconnect = (e?: Event) => {
    // 🟢 防止 Safari 預設行為
    if (e && e.cancelable) e.preventDefault(); 
    
    // 如果已經在重新整理中則跳過，避免重複觸發
    if (isRefreshing.value) return; 

    isRefreshing.value = true;
    isGenerating.value = false;
    isWaiting.value = false;
    isSidebarOpen.value = false; // 確保側邊欄關閉

    // 🟢 執行重置邏輯...
    messages.value = [
        { id: 1, user: 'AI Assistant', content: '歡迎來到台南美食助手！', time: '系統', isMe: false }
    ];

    socket.disconnect();
    
    setTimeout(() => {
        socket.connect();
        newMessage.value = '';
        isRefreshing.value = false;
        // 🟢 Safari 對 .focus() 有嚴格限制，必須由直接點擊觸發
        inputRef.value?.focus(); 
    }, 800);
};

// 初始化 Socket 連線 (對齊模擬器 5000 port)
const socket: Socket = io('http://192.168.1.113:5000', {
    transports: ['polling', 'websocket'], // 建議保留 polling 以利手機握手
    autoConnect: false, // 🟢 關鍵：改為手動連線
    reconnection: true,
    reconnectionAttempts: Infinity,
    timeout: 20000
});

const scrollToBottom = async () => {
    await nextTick();
    if (messageContainer.value) {
        messageContainer.value.scrollTo({
            top: messageContainer.value.scrollHeight,
            behavior: 'smooth'
        });
    }
};

onMounted(() => {
    // 1. 強制執行 Socket 連線
    if (!socket.connected) {
        console.log('%c[Socket] 正在嘗試建立初始連線...', 'color: #D4AF37;');
        socket.connect();
    }

    inputRef.value?.focus();

    // 2. 監聽連線事件
    socket.on('connect', () => {
        isConnected.value = true;
        console.log('%c[Socket] 連線成功！', 'color: #4ade80; font-weight: bold;');
    });

    // 🟢 [核心修正] 對齊後端模擬器事件名稱: 'chat_stream'
    socket.on('chat_stream', (data: any) => {
        console.log('%c[接收串流]', 'color: #38bdf8;', data);
        isWaiting.value = false; // 只要接到資料，就關閉等待動畫

        if (data && data.done === true) {
            isGenerating.value = false;
            console.log('✅ 生成結束');
            return;
        }

        const targetText = data.text || data.content || data.message || data.response || (typeof data === 'string' ? data : '');

        if (targetText) {
            const lastMsg = messages.value[messages.value.length - 1];
            // 增加判斷：如果最後一則訊息是 AI 且當前正在生成中，則累加文字
            if (lastMsg && !lastMsg.isMe && !lastMsg.id.toString().includes('user')) {
                lastMsg.content += targetText;
            } else {
                messages.value.push({
                    id: Date.now(),
                    user: 'AI Assistant',
                    content: targetText,
                    time: new Date().toLocaleTimeString(),
                    isMe: false
                });
            }
            scrollToBottom();
        }
    });

    socket.on('disconnect', () => {
        isConnected.value = false;
        isGenerating.value = false;
    });
});

onUnmounted(() => {
    socket.off('chat_stream');
    socket.disconnect();
});

const handleInput = (e: Event) => {
    const target = e.target as HTMLTextAreaElement;
    target.style.height = 'auto';
    target.style.height = `${Math.min(target.scrollHeight, 200)}px`;
};

const getLocation = (): Promise<{ lat: string; lng: string }> => {
    return new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
            (pos) => resolve({ lat: pos.coords.latitude.toFixed(7), lng: pos.coords.longitude.toFixed(7) }),
            () => resolve({ lat: "23.0010000", lng: "120.2390000" }),
            { enableHighAccuracy: true }
        );
    });
};

const sendMessage = async () => {
    const text = newMessage.value.trim();
    if (!text || !isConnected.value || isGenerating.value) return;

    isGenerating.value = true;
    isWaiting.value = true;
    const coords = await getLocation();

    // 🟢 [格式修正] 對齊模擬器 payload 結構
    const payload = {
        role: "user",
        text: text,
        gps: {
            lat: coords.lat,
            lng: coords.lng
        },
        // 直接傳入字串 "zh-TW"，不要讓它有 undefined 的可能性
        time: new Date().toLocaleString("zh-TW", { hour12: false }) 
    };

    console.log('%c[發送數據]', 'color: #60a5fa;', payload);
    socket.emit('text_input', payload);

    messages.value.push({
        id: Date.now(),
        user: 'You',
        content: text,
        time: new Date().toLocaleTimeString(),
        isMe: true
    });

    newMessage.value = '';
    if (inputRef.value) inputRef.value.style.height = 'auto';
    scrollToBottom();
};

// 🛑 新增：中止生成 (對齊模擬器 stop 指令)
const stopGeneration = () => {
    if (!isGenerating.value) return;
    socket.emit('text_input', { action: "stop" });
    isGenerating.value = false;
    messages.value.push({
        id: Date.now(),
        user: 'System',
        content: '--- 已手動中止 ---',
        time: new Date().toLocaleTimeString(),
        isMe: false
    });
};

// 解析訊息內容，將 <start>...<end> 轉為物件陣列
const parseContent = (content: string) => {
    const parts = [];
    const regex = /<start>(.*?)<end>/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(content)) !== null) {
        // 放入標籤前的文字
        if (match.index > lastIndex) {
            parts.push({ type: 'text', value: content.substring(lastIndex, match.index) });
        }
        // 放入卡片內容：假設格式為 "店名：描述"
        const fullContent = match[1];
        const colonIndex = fullContent.indexOf('：');
        
        if (colonIndex !== -1) {
            parts.push({ 
                type: 'card', 
                title: fullContent.substring(0, colonIndex).trim(), 
                desc: fullContent.substring(colonIndex + 1).trim() 
            });
        } else {
            parts.push({ type: 'card', title: fullContent.trim(), desc: "" });
        }
        lastIndex = regex.lastIndex;
    }

    if (lastIndex < content.length) {
        parts.push({ type: 'text', value: content.substring(lastIndex) });
    }
    return parts;
};

// 點擊卡片觸發的動作
const handleCardClick = (title: string) => {
    newMessage.value = `我想了解更多關於 ${title} 的細節`;
    inputRef.value?.focus();
};

</script>

<template>
    <Head title="Tainan Food AI" />

    <div class="flex flex-col h-screen bg-[#0e0e0e] text-[#e3e3e3] font-sans">

        <!-- 🟢 左側 Sidebar 結構 -->
        <!-- 背景遮罩 (Overlay) -->
        <div v-if="isSidebarOpen" 
             @click="toggleSidebar"
             class="fixed inset-0 bg-black/60 backdrop-blur-sm z-[60] transition-opacity duration-300">
        </div>

        <!-- Sidebar 本體 -->
        <aside :class="[
            'fixed top-0 left-0 h-full w-72 bg-[#121212] border-r border-[#D4AF37]/10 z-[70] transition-transform duration-500 ease-in-out shadow-2xl',
            isSidebarOpen ? 'translate-x-0' : '-translate-x-full'
        ]">
            <div class="p-6">
                <div class="flex items-center justify-between mb-8">
                    <h2 class="text-[#D4AF37] font-bold tracking-widest text-lg">選單目錄</h2>
                    <button @click="toggleSidebar" class="text-gray-500 hover:text-[#D4AF37] transition-colors">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>
                <!-- 這裡可以預留你後續要加的東西 -->
                <nav class="space-y-4">
                    <div class="text-sm text-gray-500 italic">側邊欄內容開發中...</div>
                </nav>
            </div>
        </aside>
        
        <!-- 頂部標題 -->
        <!-- 🟢 加入 z-[100] 確保 Header 在手機版不會被 main 的滾動區域擋住 -->
        <header class="fixed top-0 left-0 right-0 h-16 flex items-center justify-between px-6 z-[100] bg-[#0e0e0e]/80 backdrop-blur-md border-b border-[#D4AF37]/10">
            <!-- 左側內容保持不變 -->
            <div class="flex items-center space-x-4">
                <button @click="toggleSidebar" class="p-2 -ml-2 text-[#D4AF37]/60 hover:text-[#D4AF37] active:bg-[#D4AF37]/10 rounded-full transition-all">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" /></svg>
                </button>
                <div class="flex items-center space-x-2">
                    <span class="text-xl font-medium tracking-tight text-[#D4AF37]">FoodChat AI</span>
                    <div :class="['w-1.5 h-1.5 rounded-full ml-2', isConnected ? 'bg-[#D4AF37] shadow-[0_0_8px_rgba(212,175,55,0.6)]' : 'bg-red-500']"></div>
                </div>
            </div>

            <!-- 🟢 右側 Reconnect 按鈕：優化手機點擊 -->
            <div class="flex items-center space-x-2">
                <button 
                    @click="reconnect"
                    @touchend.prevent="reconnect"
                    type="button"
                    class="relative p-3 flex items-center justify-center rounded-full border border-[#D4AF37]/40 text-[#D4AF37]
                        z-[110] cursor-pointer touch-manipulation group
                        transition-all duration-200
                        active:scale-90 active:bg-[#D4AF37]/20" 
                >
                    <svg 
                        :class="[
                            'w-6 h-6 transition-transform duration-500 group-hover:rotate-[15deg]',
                            isRefreshing ? 'animate-pulse' : ''
                        ]" 
                        fill="none" 
                        stroke="currentColor" 
                        viewBox="0 0 24 24"
                    >
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M8 10h.01M12 10h.01M16 10h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                    <span class="absolute inset-0 rounded-full bg-[#D4AF37] opacity-0 group-active:opacity-10 pointer-events-none"></span>
                </button>
            </div>
        </header>

        <!-- 主內容區 -->
        <main :class="[
            'flex-1 w-full flex flex-col items-center transition-all duration-700 ease-in-out overflow-y-auto no-scrollbar',
            messages.length <= 1 ? 'justify-center' : 'pt-20'
        ]">
            
            <!-- 1. 訊息展示區：僅在有對話時渲染 -->
            <div v-if="messages.length > 1" ref="messageContainer" class="w-full max-w-4xl px-4 md:px-6 py-8 space-y-10 pb-80">
                <div v-for="msg in messages" :key="msg.id" class="flex flex-col space-y-2 group">
                    <!-- 角色名稱 -->
                    <div class="flex items-center space-x-2 px-1">
                        <div v-if="!msg.isMe" class="w-6 h-6 rounded-full bg-[#D4AF37]/20 flex items-center justify-center">
                            <span class="text-[10px] text-[#D4AF37]">AI</span>
                        </div>
                        <span class="text-sm font-semibold text-gray-400">
                            {{ msg.isMe ? 'You' : 'Tainan Food AI' }}
                        </span>
                    </div>

                    <!-- 訊息內容區 -->
                    <div class="px-1 text-[16px] leading-relaxed max-w-full space-y-4">
                        <p v-if="msg.isMe" class="whitespace-pre-wrap text-[#e3e3e3]">{{ msg.content }}</p>
                        <template v-else>
                            <div v-for="(part, index) in parseContent(msg.content)" :key="index">
                                <!-- 一般文字 -->
                                <p v-if="part.type === 'text'" class="text-[#e3e3e3] opacity-95 whitespace-pre-wrap">
                                    {{ part.value }}
                                </p>

                                <!-- 燙金美食卡片 -->
                                <div v-else-if="part.type === 'card'" @click="handleCardClick(part.title!)"
                                    class="relative my-4 p-[1px] rounded-2xl bg-gradient-to-r from-[#D4AF37] to-transparent hover:from-[#f3cf7a] transition-all duration-300 cursor-pointer group/card">
                                    
                                    <div class="bg-[#1e1f20] rounded-[15px] p-4 space-y-2 backdrop-blur-md hover:bg-[#2a2b2d] transition-colors">
                                        <div class="flex justify-between items-start">
                                            <h3 class="text-lg font-bold text-[#D4AF37] tracking-wide">{{ part.title }}</h3>
                                            <span class="text-[10px] text-gray-500 bg-gray-800 px-2 py-0.5 rounded uppercase font-bold">Restaurant</span>
                                        </div>
                                        <p class="text-sm text-gray-400 leading-relaxed">{{ part.desc }}</p>
                                        
                                        <div class="pt-1 flex items-center text-[11px] text-[#D4AF37] opacity-0 group-hover/card:opacity-100 transition-opacity">
                                            <span>點擊詢問更多細節</span>
                                            <svg class="w-3 h-3 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </template>
                    </div>
                </div>

                <!-- AI 等待動畫 -->
                <div v-if="isWaiting" class="flex flex-col space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <div class="flex items-center space-x-2 px-1">
                        <div class="w-6 h-6 rounded-full bg-[#D4AF37]/20 flex items-center justify-center">
                            <span class="text-[10px] text-[#D4AF37]">AI</span>
                        </div>
                        <span class="text-sm font-semibold text-gray-400">Tainan Food AI</span>
                    </div>
                    <div class="px-1 flex items-center space-x-3">
                        <div class="flex space-x-1.5 bg-[#1e1f20] px-4 py-3 rounded-2xl border border-[#D4AF37]/20 shadow-sm">
                            <div class="w-2 h-2 bg-[#D4AF37] rounded-full animate-bounce [animation-delay:-0.3s]"></div>
                            <div class="w-2 h-2 bg-[#D4AF37] rounded-full animate-bounce [animation-delay:-0.15s]"></div>
                            <div class="w-2 h-2 bg-[#D4AF37] rounded-full animate-bounce"></div>
                        </div>
                        <span class="text-xs text-gray-500 italic tracking-wide">正在檢索資料並準備回覆...</span>
                    </div>
                </div>
            </div>

            <!-- 2. 輸入框區域：初始置中，對話後置底 -->
            <div :class="[
                'w-full transition-all duration-700 ease-in-out z-50',
                messages.length <= 1 
                    ? 'max-w-xl px-4' 
                    : 'fixed bottom-0 left-0 right-0 bg-[#0e0e0e] border-t border-white/5 pt-6 pb-safe flex justify-center shadow-[0_-20px_30px_10px_rgba(14,14,14,0.9)]'
            ]">
                <div :class="['group w-full', messages.length <= 1 ? '' : 'max-w-4xl px-4 pb-[env(safe-area-inset-bottom)]']">
                    
                    <!-- 初始狀態燙金 LOGO -->
                    <div v-if="messages.length <= 1" class="mb-10 text-center animate-in fade-in zoom-in duration-1000">
                        <div class="w-20 h-20 rounded-full bg-gradient-to-tr from-[#8A6623] via-[#D4AF37] to-[#F3CF7A] shadow-[0_0_30px_rgba(212,175,55,0.4)] mb-6 mx-auto border border-white/10"></div>
                        <h1 class="text-3xl font-bold text-[#D4AF37] tracking-widest uppercase"> FoodChat AI</h1>
                        <p class="text-gray-500 mt-3 tracking-widest text-xs uppercase">台南美食指南 · 今天要吃甚麼呢?</p>
                    </div>

                    <!-- 輸入框主體 -->
                    <div class="relative p-[1.5px] rounded-[30px] overflow-hidden bg-[#1e1f20]">
                        <!-- 燙金呼吸燈光束 -->
                        <div class="absolute inset-[-200%] animate-[spin_4s_linear_infinite] bg-[conic-gradient(from_0deg,transparent_120deg,#D4AF37_180deg,transparent_240deg)] opacity-0 group-focus-within:opacity-100 transition-opacity duration-500"></div>
                        
                        <div class="relative flex items-end w-full bg-[#1e1f20] rounded-[28px] px-4 py-2 backdrop-blur-xl z-10">
                            <textarea 
                                ref="inputRef" 
                                v-model="newMessage" 
                                @input="handleInput" 
                                @keydown.enter.prevent="sendMessage"
                                class="flex-1 bg-transparent border-none outline-none text-base focus:ring-0 py-3 resize-none placeholder-[#8e9196] min-h-[56px] max-h-[200px] leading-relaxed"
                                placeholder="輸入關於台南美食的問題..."
                            ></textarea>
                            
                            <div class="pb-2.5 ml-2">
                                <button 
                                    @click="sendMessage"
                                    @touchend.prevent="sendMessage"
                                    type="button"
                                    :disabled="!newMessage.trim() || !isConnected"
                                    class="p-2.5 rounded-full transition-all duration-300 flex items-center justify-center z-[110] touch-manipulation"
                                >
                                    <svg class="w-5 h-5 fill-current" viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"></path></svg>
                                </button>
                            </div>
                        </div>
                    </div>

                    <!-- 底部法律/系統宣告 -->
                    <p v-if="messages.length > 1" class="text-center text-[10px] text-gray-600 mt-3 tracking-wide">
                        Tainan Food AI 可能會提供不準確的資訊，請考慮查證其回覆。
                    </p>
                </div>
            </div>
        </main>
    </div>
</template>

<style scoped>
/* 1. 基礎網頁環境設定 */
:global(html) {
    overflow-y: scroll;
    background-color: #0e0e0e;
    /* 🟢 修正 Safari 行動端彈性滾動導致的層級偏移 */
    -webkit-overflow-scrolling: touch;
}

/* 🟢 順時針旋轉動畫 */
@keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}

/* 2. 滾動條樣式 */
:global(::-webkit-scrollbar) {
    width: 8px;
}
:global(::-webkit-scrollbar-track) {
    background: transparent;
}
:global(::-webkit-scrollbar-thumb) {
    background: rgba(212, 175, 55, 0.15); 
    border-radius: 10px;
}
:global(::-webkit-scrollbar-thumb:hover) {
    background: rgba(212, 175, 55, 0.4);
}

/* 3. 內容區塊佈局 */
main {
    flex: 1;
    padding-top: 80px; 
    /* 🟢 修改：增加對安全區域的考慮，防止內容被輸入框擋死 */
    padding-bottom: calc(160px + env(safe-area-inset-bottom)); 
    position: relative;
    z-index: 10;
}

/* 4. 輸入框與按鈕優化 */
textarea {
    line-height: 1.6;
    caret-color: #D4AF37; 
    scrollbar-width: none;
    /* 🟢 修正 iOS 輸入框預設外觀 */
    -webkit-appearance: none;
}

/* 5. 🟢 核心修正：解決 Safari 按鈕失效 */
header {
    /* 🟢 強制開啟硬體加速，防止 Safari 渲染層級塌陷 */
    -webkit-transform: translateZ(0);
    transform: translateZ(0);
    pointer-events: auto !important;
    z-index: 100 !important;
}

button {
    /* 🟢 移除 Safari 點擊高亮灰色方塊 */
    -webkit-tap-highlight-color: transparent;
    /* 🟢 移除手機端 300ms 點擊延遲 */
    touch-action: manipulation;
    /* 🟢 確保點擊事件能穿透到正確的 DOM 節點 */
    pointer-events: auto !important;
    cursor: pointer;
}

/* 🟢 修正遮罩層級 */
.fixed.inset-0 {
    z-index: 60; 
    /* 防止遮罩攔截到 Header 區域的點擊 */
    -webkit-backdrop-filter: blur(4px);
}

/* 6. 其他細節 */
.group:focus-within .opacity-100 {
    opacity: 1 !important;
}

.text-\[\#D4AF37\] {
    text-shadow: 0px 0px 1px rgba(212, 175, 55, 0.3);
}

/* 🟢 針對 iPhone 底部安全區域適配 (防誤觸) */
@media (max-width: 768px) {
    .fixed.bottom-0 {
        /* 🟢 修正：增加實心背景色，防止內容穿透看到底 */
        background-color: #0e0e0e !important;
        /* 🟢 修正：移除模糊，避免 Safari 產生透明縫隙 */
        -webkit-backdrop-filter: none !important;
        backdrop-filter: none !important;
        /* 🟢 修正：加入向上陰影，讓訊息滾入時更自然 */
        shadow: 0 -20px 30px 10px rgba(14, 14, 14, 1);
        padding-bottom: calc(1.5rem + env(safe-area-inset-bottom));
    }
}
.pb-safe {
    padding-bottom: env(safe-area-inset-bottom);
}
</style>