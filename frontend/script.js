const ws = new WebSocket(`ws://${location.host}/ws`);

// DOM Elements
const statusDot = document.getElementById("connection-status");
const statusText = document.getElementById("status-text");
const conversation = document.getElementById("conversation");
const textInput = document.getElementById("text-input");
const sendButton = document.getElementById("send-button");
const micButton = document.getElementById("mic-button");
const stopButton = document.getElementById("stop-button");
const wakeWordToggle = document.getElementById("wake-word-toggle");
const languageSelector = document.getElementById("language-selector");
const sidebar = document.getElementById("sidebar");
const sidebarToggle = document.getElementById("sidebar-toggle");
const chatList = document.getElementById("chat-list");
const newChatBtn = document.getElementById("new-chat-btn");

// State
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let wakeWordEnabled = true;
let wakeWordRecognition = null;
let currentSessionId = null;
let isGenerating = false;

// WebSocket Events
ws.onopen = () => {
    updateStatus("connected");
    console.log("WebSocket connected");
    loadSessions(); // Load chat history list
};

ws.onclose = () => {
    updateStatus("disconnected");
    console.log("WebSocket disconnected");
};

ws.onmessage = async (event) => {
    // Handle binary audio data
    if (event.data instanceof Blob) {
        playAudio(event.data);
        if (window.jarvisVisualizer) {
            window.jarvisVisualizer.setSpeaking(true);
            // Reset after audio duration (approximate or listen to 'ended' event in playAudio)
        }
        return;
    }

    // Handle JSON text data
    try {
        const data = JSON.parse(event.data);
        
        if (data.type === "session_init") {
            currentSessionId = data.session_id;
            // Clear conversation if it's a fresh session and we aren't loading history
            if (!data.restored) {
                conversation.innerHTML = '';
                addMessage("System initialized. Ready for input.", "system");
            }
            loadSessions();
        } else if (data.type === "history") {
            renderHistory(data.messages);
        } else if (data.type === "session_updated") {
            loadSessions();
        } else if (data.type === "transcription") {
            addMessage(data.text, "user");
            setGenerating(true);
        } else if (data.type === "text") {
            const content = data.chunk || data.content || data.data || "";
            if (data.chunk) {
                appendToMessage(content, "jarvis");
            } else if (content) {
                addMessage(content, "jarvis");
            }
        } else if (data.type === "thought") {
            const content = data.chunk || data.content || "";
            if (data.chunk) {
                appendToMessage(content, "thought");
            } else if (content) {
                addMessage(content, "thought");
            }
        } else if (data.type === "tool_call") {
            const args = data.args ? JSON.stringify(data.args, null, 2) : "{}";
            const toolInfo = `🛠️ Calling ${data.tool}...\nArgs: ${args}`;
            addMessage(toolInfo, "tool-call");
        } else if (data.type === "tool_result") {
            const content = data.content || "";
            const resultInfo = `✅ Result from ${data.tool}:\n${content}`;
            addMessage(resultInfo, "tool-result");
        } else if (data.type === "complete") {
            setGenerating(false);
        } else if (data.type === "error") {
            console.error("Server error:", data.message);
            addMessage(`Error: ${data.message}`, "system");
            setGenerating(false);
        }
    } catch (e) {
        console.error("Error parsing message:", e);
    }
};

// UI Functions
let currentMessageDiv = null;
let currentMessageType = null;

function updateStatus(status) {
    statusDot.className = `status-dot ${status}`;
    statusText.textContent = status.charAt(0).toUpperCase() + status.slice(1);
}

function setGenerating(generating) {
    isGenerating = generating;
    if (generating) {
        stopButton.classList.remove("hidden");
        micButton.classList.add("hidden");
    } else {
        stopButton.classList.add("hidden");
        micButton.classList.remove("hidden");
        currentMessageDiv = null; // Reset stream buffer
    }
}

function appendToMessage(text, type) {
    if (!text) return;

    if (!currentMessageDiv || currentMessageType !== type) {
        addMessage("", type);
        currentMessageDiv = conversation.lastElementChild;
        currentMessageType = type;
    }
    
    const contentDiv = currentMessageDiv.querySelector(".content");
    
    if (type === "jarvis") {
        if (!contentDiv.dataset.raw) contentDiv.dataset.raw = "";
        contentDiv.dataset.raw += text;
        if (window.marked) {
            contentDiv.innerHTML = marked.parse(contentDiv.dataset.raw);
        } else {
            contentDiv.textContent = contentDiv.dataset.raw;
        }
    } else {
        contentDiv.textContent += text;
    }
    
    conversation.scrollTop = conversation.scrollHeight;
}

function addMessage(text, sender) {
    currentMessageDiv = null;
    currentMessageType = null;

    const messageDiv = document.createElement("div");
    messageDiv.className = `message ${sender}`;
    
    const contentDiv = document.createElement("div");
    contentDiv.className = "content";
    
    const safeText = text || "";

    if ((sender === "jarvis" || sender === "assistant") && window.marked) {
        contentDiv.dataset.raw = safeText;
        contentDiv.innerHTML = marked.parse(safeText);
    } else {
        contentDiv.textContent = safeText;
    }
    
    messageDiv.appendChild(contentDiv);
    conversation.appendChild(messageDiv);
    conversation.scrollTop = conversation.scrollHeight;
}

function renderHistory(messages) {
    conversation.innerHTML = '';
    messages.forEach(msg => {
        // Map backend roles to frontend classes
        let sender = msg.role;
        if (sender === "assistant") sender = "jarvis";
        addMessage(msg.content, sender);
    });
}

// Session Management
async function loadSessions() {
    try {
        const response = await fetch('/api/sessions');
        const sessions = await response.json();
        renderSessionList(sessions);
    } catch (e) {
        console.error("Failed to load sessions:", e);
    }
}

function renderSessionList(sessions) {
    chatList.innerHTML = '';
    sessions.forEach(session => {
        const div = document.createElement('div');
        div.className = `chat-item ${session.id === currentSessionId ? 'active' : ''}`;
        
        const titleSpan = document.createElement('span');
        titleSpan.textContent = session.title || "New Conversation";
        titleSpan.style.flex = "1";
        titleSpan.style.overflow = "hidden";
        titleSpan.style.textOverflow = "ellipsis";
        
        const deleteBtn = document.createElement('button');
        deleteBtn.className = "delete-btn";
        deleteBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>`;
        deleteBtn.title = "Delete Chat";
        deleteBtn.onclick = (e) => deleteSession(session.id, e);

        div.appendChild(titleSpan);
        div.appendChild(deleteBtn);
        
        div.onclick = (e) => {
            // Only load if not clicking delete
            if (!e.target.closest('.delete-btn')) {
                loadSession(session.id);
            }
        };
        
        chatList.appendChild(div);
    });
}

async function deleteSession(sessionId, event) {
    if (event) event.stopPropagation();
    
    if (!confirm("Are you sure you want to delete this chat?")) return;

    try {
        await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
        
        // If we deleted the current session, create a new one
        if (sessionId === currentSessionId) {
            createNewSession();
        } else {
            loadSessions();
        }
    } catch (e) {
        console.error("Failed to delete session:", e);
    }
}

function loadSession(sessionId) {
    if (sessionId === currentSessionId) return;
    
    ws.send(JSON.stringify({
        type: "load_session",
        session_id: sessionId
    }));
    currentSessionId = sessionId;
    loadSessions(); // Refresh active state
    
    // Close sidebar on mobile
    if (window.innerWidth < 768) {
        sidebar.classList.remove("open");
    }
}

function createNewSession() {
    ws.send(JSON.stringify({
        type: "new_session"
    }));
}

// Audio Functions
function playAudio(blob) {
    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    
    if (window.jarvisVisualizer) {
        window.jarvisVisualizer.setSpeaking(true);
    }

    audio.onended = () => {
        URL.revokeObjectURL(audioUrl);
        if (window.jarvisVisualizer) {
            window.jarvisVisualizer.setSpeaking(false);
        }
        if (wakeWordEnabled) {
            startWakeWordDetection();
        }
    };
    
    stopWakeWordDetection();
    audio.play().catch(e => console.error("Audio playback failed:", e));
}

// Recording Functions
async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];

        mediaRecorder.ondataavailable = (event) => {
            audioChunks.push(event.data);
        };

        mediaRecorder.onstop = () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
            ws.send(audioBlob);
            stream.getTracks().forEach(track => track.stop());
        };

        mediaRecorder.start();
        isRecording = true;
        micButton.classList.add("recording");
        stopWakeWordDetection();
        
    } catch (err) {
        console.error("Error accessing microphone:", err);
        addMessage("Error accessing microphone. Please check permissions.", "system");
    }
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        micButton.classList.remove("recording");
    }
}

// Wake Word Detection
function initWakeWordDetection() {
    if (!('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)) {
        console.warn("Speech recognition not supported");
        wakeWordToggle.style.display = "none";
        return;
    }

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    wakeWordRecognition = new SR();
    wakeWordRecognition.continuous = true;
    wakeWordRecognition.interimResults = false;
    wakeWordRecognition.lang = 'en-US';

    wakeWordRecognition.onresult = (event) => {
        const lastResult = event.results[event.results.length - 1];
        if (lastResult.isFinal) {
            const transcript = lastResult[0].transcript.toLowerCase().trim();
            console.log("Heard:", transcript);
            
            if (transcript.includes("hey jarvis") || transcript.includes("jarvis")) {
                console.log("Wake word detected!");
                startRecording();
            }
        }
    };

    wakeWordRecognition.onerror = (event) => {
        if (event.error === 'not-allowed') {
            wakeWordEnabled = false;
            updateWakeWordUI();
        }
    };
    
    wakeWordRecognition.onend = () => {
        if (wakeWordEnabled && !isRecording) {
            try { wakeWordRecognition.start(); } catch (e) {}
        }
    };

    if (wakeWordEnabled) {
        startWakeWordDetection();
    }
}

function startWakeWordDetection() {
    if (wakeWordRecognition && wakeWordEnabled) {
        try { wakeWordRecognition.start(); } catch (e) {}
    }
}

function stopWakeWordDetection() {
    if (wakeWordRecognition) {
        try { wakeWordRecognition.stop(); } catch (e) {}
    }
}

function updateWakeWordUI() {
    if (wakeWordEnabled) {
        wakeWordToggle.classList.add("active");
    } else {
        wakeWordToggle.classList.remove("active");
    }
}

// Event Listeners
sendButton.addEventListener("click", () => {
    const text = textInput.value.trim();
    if (text) {
        ws.send(JSON.stringify({
            type: "text",
            text: text,
            language: languageSelector.value
        }));
        
        addMessage(text, "user");
        textInput.value = "";
        setGenerating(true);
    }
});

textInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendButton.click();
    }
});

micButton.addEventListener("click", () => {
    if (isRecording) {
        stopRecording();
    } else {
        startRecording();
    }
});

stopButton.addEventListener("click", () => {
    ws.send(JSON.stringify({ type: "stop" }));
    setGenerating(false);
});

wakeWordToggle.addEventListener("click", () => {
    wakeWordEnabled = !wakeWordEnabled;
    updateWakeWordUI();
    if (wakeWordEnabled) startWakeWordDetection();
    else stopWakeWordDetection();
});

sidebarToggle.addEventListener("click", () => {
    sidebar.classList.toggle("open");
});

newChatBtn.addEventListener("click", createNewSession);

// Initialize
initWakeWordDetection();

// Settings Modal Logic
const settingsBtn = document.getElementById("settings-btn");
const settingsModal = document.getElementById("settings-modal");
const closeSettingsBtn = document.getElementById("close-settings");
const saveSettingsBtn = document.getElementById("save-settings");
const toolsList = document.getElementById("tools-list");

if (settingsBtn) {
    settingsBtn.addEventListener("click", async () => {
        settingsModal.style.display = "block";
        await loadSettings();
    });
}

if (closeSettingsBtn) {
    closeSettingsBtn.addEventListener("click", () => {
        settingsModal.style.display = "none";
    });
}

window.addEventListener("click", (event) => {
    if (event.target === settingsModal) {
        settingsModal.style.display = "none";
    }
});

if (saveSettingsBtn) {
    saveSettingsBtn.addEventListener("click", async () => {
        await saveSettings();
        settingsModal.style.display = "none";
    });
}

async function loadSettings() {
    try {
        const response = await fetch("/api/settings");
        const config = await response.json();
        
        if (config.tools) {
            renderTools(config.tools);
        }
    } catch (error) {
        console.error("Error loading settings:", error);
    }
}

async function saveSettings() {
    const toolsConfig = {};
    const toolInputs = toolsList.querySelectorAll("input[type='checkbox']");
    toolInputs.forEach(input => {
        const toolName = input.id.replace("tool-", "");
        toolsConfig[toolName] = input.checked;
    });

    const newSettings = {
        tools: toolsConfig
    };
    
    try {
        const response = await fetch("/api/settings", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(newSettings)
        });
        
        const result = await response.json();
        console.log("Settings saved:", result);
    } catch (error) {
        console.error("Error saving settings:", error);
    }
}

function renderTools(toolsConfig) {
    toolsList.innerHTML = "";
    // Sort keys to keep list stable
    const sortedKeys = Object.keys(toolsConfig).sort();
    
    for (const toolName of sortedKeys) {
        const enabled = toolsConfig[toolName];
        const div = document.createElement("div");
        div.className = "setting-item";
        div.innerHTML = `
            <label class="switch">
                <input type="checkbox" id="tool-${toolName}" ${enabled ? "checked" : ""}>
                <span class="slider round"></span>
            </label>
            <span>${formatToolName(toolName)}</span>
        `;
        toolsList.appendChild(div);
    }
}

function formatToolName(name) {
    return name.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}
