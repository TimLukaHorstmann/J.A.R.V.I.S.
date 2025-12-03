let ws;
let reconnectInterval = 1000;
const maxReconnectInterval = 30000;

// State
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let wakeWordEnabled = true;
let thinkingEnabled = true;
let ttsEnabled = true;
let wakeWordRecognition = null;
let currentSessionId = null;
let isGenerating = false;
let activeAgentMessage = null;

// Silence Detection State
let audioContext = null;
let analyser = null;
let microphone = null;
let javascriptNode = null;

function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws`;
    
    console.log(`Connecting to WebSocket: ${wsUrl}`);
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        updateStatus("connected");
        console.log("WebSocket connected");
        reconnectInterval = 1000; // Reset interval
        loadSessions(); // Load chat history list
    };

    ws.onclose = (e) => {
        updateStatus("disconnected");
        console.log(`WebSocket disconnected (Code: ${e.code}, Reason: ${e.reason})`);
        
        // Show error in chat if it was a clean close or error
        if (e.code !== 1000) {
             // Optional: Add a small system message or toast
             // addMessage(`Connection lost (Code: ${e.code}). Reconnecting...`, "system");
        }

        // Try to reconnect with exponential backoff
        const timeout = Math.min(reconnectInterval, maxReconnectInterval);
        console.log(`Reconnecting in ${timeout}ms...`);
        setTimeout(connectWebSocket, timeout);
        reconnectInterval *= 2;
    };

    ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        updateStatus("error");
        // addMessage("WebSocket connection error. Check console/network.", "system");
        ws.close();
    };

    ws.onmessage = handleMessage;
}

const handleMessage = async (event) => {
    // Handle binary audio data
    if (event.data instanceof Blob) {
        playAudio(event.data);
        if (window.jarvisVisualizer) {
            window.jarvisVisualizer.setSpeaking(true);
        }
        return;
    }

    // Handle JSON text data
    try {
        const data = JSON.parse(event.data);
        
        if (data.type === "session_init") {
            currentSessionId = data.session_id;
            if (!data.restored) {
                const conversation = document.getElementById("conversation");
                if (conversation) {
                    conversation.innerHTML = '';
                    addMessage("System initialized. Ready for input.", "system");
                }
            }
            loadSessions();
        } else if (data.type === "history") {
            renderHistory(data.messages);
        } else if (data.type === "session_updated") {
            loadSessions();
        } else if (data.type === "transcription") {
            addMessage(data.text, "user");
            setGenerating(true);
            activeAgentMessage = null; // Reset for new turn
        } else if (data.type === "text") {
            const content = data.chunk || data.content || data.data || "";
            updateAgentMessage("text", content);
        } else if (data.type === "thought") {
            const content = data.chunk || data.content || "";
            updateAgentMessage("thought", content);
        } else if (data.type === "tool_call") {
            updateAgentMessage("tool_call", data);
        } else if (data.type === "tool_result") {
            updateAgentMessage("tool_result", data);
        } else if (data.type === "complete") {
            setGenerating(false);
            if (activeAgentMessage) {
                updateAgentStatus("Done", "check");
                
                // Collapse trace after delay
                const msgToCollapse = activeAgentMessage;
                setTimeout(() => {
                    if (msgToCollapse && msgToCollapse.traceDiv) {
                        msgToCollapse.traceDiv.classList.remove("visible");
                        msgToCollapse.statusDiv.classList.remove("expanded");
                    }
                }, 3000);
                
                activeAgentMessage = null;
            }
        } else if (data.type === "error") {
            console.error("Server error:", data.message);
            addMessage(`Error: ${data.message}`, "system");
            setGenerating(false);
        }
    } catch (e) {
        console.error("Error parsing message:", e);
    }
};

// Start connection
connectWebSocket();

// UI Functions
let currentMessageDiv = null;
let currentMessageType = null;

function updateStatus(status) {
    const statusDot = document.getElementById("connection-status");
    const statusText = document.getElementById("status-text");
    if (statusDot) statusDot.className = `status-dot ${status}`;
    if (statusText) statusText.textContent = status.charAt(0).toUpperCase() + status.slice(1);
}

function setGenerating(generating) {
    isGenerating = generating;
    const stopButton = document.getElementById("stop-button");
    const micButton = document.getElementById("mic-button");
    
    if (generating) {
        if (stopButton) stopButton.classList.remove("hidden");
        if (micButton) micButton.classList.add("hidden");
    } else {
        if (stopButton) stopButton.classList.add("hidden");
        if (micButton) micButton.classList.remove("hidden");
        currentMessageDiv = null; // Reset stream buffer
    }
}

function updateAgentMessage(type, data) {
    const conversation = document.getElementById("conversation");
    if (!conversation) return;

    // Create container if not exists
    if (!activeAgentMessage) {
        createAgentMessageContainer();
    }

    if (type === "text") {
        activeAgentMessage.contentRaw += data;
        if (window.marked) {
            activeAgentMessage.contentDiv.innerHTML = marked.parse(activeAgentMessage.contentRaw);
            renderMath(activeAgentMessage.contentDiv);
        } else {
            activeAgentMessage.contentDiv.textContent = activeAgentMessage.contentRaw;
        }
        updateAgentStatus("Speaking...", "mic");
        activeAgentMessage.contentDiv.style.display = "block";
    } else if (type === "thought") {
        let step = activeAgentMessage.steps.find(s => s.type === "thinking" && !s.completed);
        if (!step) {
            step = createTraceStep("Thinking...", "brain");
            step.type = "thinking";
            activeAgentMessage.steps.push(step);
            activeAgentMessage.traceDiv.appendChild(step.div);
        }
        step.contentDiv.textContent += data;
        updateAgentStatus("Thinking...", "brain");
    } else if (type === "tool_call") {
        // Mark previous thinking as done
        const thinkingStep = activeAgentMessage.steps.find(s => s.type === "thinking" && !s.completed);
        if (thinkingStep) {
            thinkingStep.completed = true;
        }

        const args = data.args ? JSON.stringify(data.args, null, 2) : "{}";
        const step = createTraceStep(`Calling ${data.tool}...`, "tool");
        step.type = "tool";
        step.toolName = data.tool;
        step.contentDiv.textContent = `Args: ${args}`;
        step.div.classList.add("tool-call");
        
        activeAgentMessage.steps.push(step);
        activeAgentMessage.traceDiv.appendChild(step.div);
        updateAgentStatus(`Using ${data.tool}...`, "tool");
    } else if (type === "tool_result") {
        // Find the last tool step
        const step = activeAgentMessage.steps.slice().reverse().find(s => s.type === "tool" && !s.completed);
        if (step) {
            step.completed = true;
            const content = data.content || "";
            step.contentDiv.textContent += `\n\nResult:\n${content}`;
            
            // Check for error
            if (content.toLowerCase().includes("error")) {
                step.div.classList.add("error");
                step.headerText.textContent = `Error: ${step.toolName}`;
                updateAgentStatus(`Error in ${step.toolName}`, "alert-triangle");
            } else {
                step.div.classList.add("success");
                step.headerText.textContent = `Finished: ${step.toolName}`;
                updateAgentStatus(`Finished ${step.toolName}`, "check");
            }
        }
    }
    
    conversation.scrollTop = conversation.scrollHeight;
}

function createAgentMessageContainer() {
    const conversation = document.getElementById("conversation");
    const container = document.createElement("div");
    container.className = "agent-message-container";
    
    // Status Bar
    const statusDiv = document.createElement("div");
    statusDiv.className = "agent-status expanded"; // Expanded by default
    statusDiv.innerHTML = `
        <div class="icon"></div>
        <div class="text">Processing...</div>
        <div class="toggle-icon">▼</div>
    `;
    statusDiv.onclick = () => {
        traceDiv.classList.toggle("visible");
        statusDiv.classList.toggle("expanded");
    };
    
    // Trace Area
    const traceDiv = document.createElement("div");
    traceDiv.className = "agent-trace visible"; // Visible by default
    
    // Content Area
    const contentDiv = document.createElement("div");
    contentDiv.className = "agent-content";
    contentDiv.style.display = "none"; // Hide initially
    
    container.appendChild(statusDiv);
    container.appendChild(traceDiv);
    container.appendChild(contentDiv);
    conversation.appendChild(container);
    
    activeAgentMessage = {
        container,
        statusDiv,
        traceDiv,
        contentDiv,
        contentRaw: "",
        steps: []
    };
}

function createTraceStep(title, iconType) {
    const div = document.createElement("div");
    div.className = "trace-step";
    
    const header = document.createElement("div");
    header.className = "trace-step-header";
    header.innerHTML = `<span>${getIconSvg(iconType)}</span> <span>${title}</span>`;
    
    const content = document.createElement("div");
    content.className = "trace-step-content";
    
    div.appendChild(header);
    div.appendChild(content);
    
    return {
        div,
        headerText: header.querySelector("span:last-child"),
        contentDiv: content,
        completed: false
    };
}

function updateAgentStatus(text, iconType) {
    if (!activeAgentMessage) return;
    const iconDiv = activeAgentMessage.statusDiv.querySelector(".icon");
    const textDiv = activeAgentMessage.statusDiv.querySelector(".text");
    
    iconDiv.innerHTML = getIconSvg(iconType);
    textDiv.textContent = text;
}

function getIconSvg(type) {
    // Normalize type to lowercase for matching
    const t = type.toLowerCase();
    
    // Generic Icons
    if (t === "brain" || t === "thinking") return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z"/></svg>`;
    if (t === "check" || t === "success") return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
    if (t === "alert-triangle" || t === "error") return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`;
    if (t === "mic") return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>`;
    
    // Tool Specific Icons
    if (t.includes("spotify") || t.includes("music")) return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg>`;
    if (t.includes("weather") || t.includes("temperature")) return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`;
    if (t.includes("alexa") || t.includes("home") || t.includes("light")) return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>`;
    if (t.includes("search") || t.includes("web")) return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>`;
    if (t.includes("memory") || t.includes("remember") || t.includes("retrieve")) return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s 9-1.34 9-3V5"></path></svg>`;
    if (t.includes("volume") || t.includes("system")) return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>`;
    
    // Default Tool Icon
    return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>`;
}

function addMessage(text, sender) {
    currentMessageDiv = null;
    currentMessageType = null;
    const conversation = document.getElementById("conversation");
    if (!conversation) return;

    const messageDiv = document.createElement("div");
    messageDiv.className = `message ${sender}`;
    
    const contentDiv = document.createElement("div");
    contentDiv.className = "content";
    
    const safeText = text || "";

    if ((sender === "jarvis" || sender === "assistant") && window.marked) {
        contentDiv.dataset.raw = safeText;
        contentDiv.innerHTML = marked.parse(safeText);
        renderMath(contentDiv);
    } else {
        contentDiv.textContent = safeText;
    }
    
    messageDiv.appendChild(contentDiv);
    conversation.appendChild(messageDiv);
    conversation.scrollTop = conversation.scrollHeight;
}

function renderHistory(messages) {
    const conversation = document.getElementById("conversation");
    if (!conversation) return;
    conversation.innerHTML = '';
    messages.forEach(msg => {
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
    const chatList = document.getElementById("chat-list");
    if (!chatList) return;
    
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
    loadSessions();
    
    const sidebar = document.getElementById("sidebar");
    if (window.innerWidth < 768 && sidebar) {
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

        // Silence Detection Setup
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioContext.createAnalyser();
        microphone = audioContext.createMediaStreamSource(stream);
        javascriptNode = audioContext.createScriptProcessor(2048, 1, 1);

        analyser.smoothingTimeConstant = 0.8;
        analyser.fftSize = 1024;

        microphone.connect(analyser);
        analyser.connect(javascriptNode);
        javascriptNode.connect(audioContext.destination);

        let silenceStart = Date.now();
        const silenceThreshold = 0.02; // Sensitivity
        const silenceDuration = 2000; // 2 seconds of silence to stop

        javascriptNode.onaudioprocess = function() {
            const array = new Uint8Array(analyser.frequencyBinCount);
            analyser.getByteFrequencyData(array);
            let values = 0;
            const length = array.length;
            for (let i = 0; i < length; i++) {
                values += array[i];
            }
            const average = values / length;
            const volume = average / 255; 

            if (volume < silenceThreshold) {
                if (Date.now() - silenceStart > silenceDuration) {
                    console.log("Silence detected, stopping recording");
                    stopRecording();
                }
            } else {
                silenceStart = Date.now();
            }
        };

        mediaRecorder.ondataavailable = (event) => {
            audioChunks.push(event.data);
        };

        mediaRecorder.onstop = () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
            
            // Send configuration first
            ws.send(JSON.stringify({
                type: "config",
                thinking: thinkingEnabled
            }));
            
            ws.send(audioBlob);
            stream.getTracks().forEach(track => track.stop());
            
            // Cleanup Audio Context
            if (audioContext) {
                audioContext.close();
                audioContext = null;
            }
            if (javascriptNode) {
                javascriptNode.disconnect();
                javascriptNode = null;
            }
            if (analyser) {
                analyser.disconnect();
                analyser = null;
            }
            if (microphone) {
                microphone.disconnect();
                microphone = null;
            }
        };

        mediaRecorder.start();
        isRecording = true;
        const micButton = document.getElementById("mic-button");
        if (micButton) micButton.classList.add("recording");
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
        const micButton = document.getElementById("mic-button");
        if (micButton) micButton.classList.remove("recording");
    }
}

// Wake Word Detection
function initWakeWordDetection() {
    const wakeWordToggle = document.getElementById("wake-word-toggle");
    if (!('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)) {
        console.warn("Speech recognition not supported");
        if (wakeWordToggle) wakeWordToggle.style.display = "none";
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
    const wakeWordToggle = document.getElementById("wake-word-toggle");
    if (!wakeWordToggle) return;
    if (wakeWordEnabled) {
        wakeWordToggle.classList.add("active");
    } else {
        wakeWordToggle.classList.remove("active");
    }
}

// Settings & Memory Functions
async function loadSettings() {
    try {
        const response = await fetch("/api/settings");
        const config = await response.json();
        
        const toolsList = document.getElementById("tools-list");
        if (config.tools && toolsList) {
            renderTools(config.tools);
        }
        
        // Update TTS state
        const enabled = config.application && config.application.tts_enabled;
        ttsEnabled = enabled !== undefined ? enabled : true;
        const ttsBtn = document.getElementById("tts-toggle");
        if (ttsBtn) {
            ttsBtn.classList.toggle("active", ttsEnabled);
        }
    } catch (error) {
        console.error("Error loading settings:", error);
    }
}

async function saveSettings() {
    const toolsList = document.getElementById("tools-list");
    
    const toolsConfig = {};
    if (toolsList) {
        const toolInputs = toolsList.querySelectorAll("input[type='checkbox']");
        toolInputs.forEach(input => {
            const toolName = input.id.replace("tool-", "");
            toolsConfig[toolName] = input.checked;
        });
    }

    const newSettings = {
        tools: toolsConfig,
        application: {
            tts_enabled: ttsEnabled
        }
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

async function loadMemories() {
    try {
        const response = await fetch("/api/memory");
        const memories = await response.json();
        renderMemories(memories);
    } catch (error) {
        console.error("Error loading memories:", error);
    }
}

async function addMemory(key, value) {
    try {
        await fetch("/api/memory", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ key, value })
        });
    } catch (error) {
        console.error("Error adding memory:", error);
    }
}

async function deleteMemory(key) {
    try {
        await fetch(`/api/memory/${encodeURIComponent(key)}`, {
            method: "DELETE"
        });
        await loadMemories();
    } catch (error) {
        console.error("Error deleting memory:", error);
    }
}

function renderMemories(memories) {
    const memoryList = document.getElementById("memory-list");
    if (!memoryList) return;
    
    memoryList.innerHTML = "";
    if (memories.length === 0) {
        memoryList.innerHTML = "<p>No memories stored.</p>";
        return;
    }
    
    memories.forEach(mem => {
        const div = document.createElement("div");
        div.className = "memory-item";
        div.innerHTML = `
            <div class="memory-content">
                <strong>${mem.key}</strong>: ${mem.value}
            </div>
            <button class="icon-btn delete-memory" data-key="${mem.key}">&times;</button>
        `;
        memoryList.appendChild(div);
    });
    
    // Add delete listeners
    document.querySelectorAll(".delete-memory").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const key = e.target.getAttribute("data-key");
            deleteMemory(key);
        });
    });
}

function renderTools(toolsConfig) {
    const toolsList = document.getElementById("tools-list");
    if (!toolsList) return;
    
    toolsList.innerHTML = "";
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

// Metadata for known tools to show helpful descriptions in the settings UI
const toolMetadata = {
    spotify: {
        title: 'Spotify',
        desc: 'Connects to Spotify to control playback, search tracks and play music.'
    },
    weather: {
        title: 'Weather',
        desc: 'Fetches current weather and forecasts for locations.'
    },
    home_assistant: {
        title: 'Home Assistant',
        desc: 'Integrates with Home Assistant to control smart devices and read sensors.'
    },
    llm: {
        title: 'LLM',
        desc: 'Local language model backend used to generate responses and reasoning.'
    },
    mcp: {
        title: 'MCP',
        desc: 'Message / control plane for routing tool calls and agent events.'
    },
    openwb: {
        title: 'OpenWB',
        desc: 'Controls OpenWB chargers and reads charging state for EV charging management.'
    },
    system: {
        title: 'System',
        desc: 'Run system-level commands and query system status (volume, uptime, etc.).'
    },
    audio: {
        title: 'Audio',
        desc: 'Handles audio input/output, recording, playback and TTS hooks.'
    },
    memory: {
        title: 'Memory',
        desc: 'Long-term memory storage for remembering user preferences and facts.'
    }
};

function renderTools(toolsConfig) {
    const toolsList = document.getElementById("tools-list");
    if (!toolsList) return;

    toolsList.innerHTML = "";
    const sortedKeys = Object.keys(toolsConfig).sort();

    for (const toolName of sortedKeys) {
        const enabled = toolsConfig[toolName];
        const meta = toolMetadata[toolName] || { title: formatToolName(toolName), desc: 'No description available.' };

        const div = document.createElement("div");
        div.className = "setting-item";
        div.innerHTML = `
            <label class="switch">
                <input type="checkbox" id="tool-${toolName}" ${enabled ? "checked" : ""}>
                <span class="slider round"></span>
            </label>
            <div class="tool-text">
                <div class="tool-title">${meta.title}</div>
                <div class="tool-desc">${meta.desc}</div>
            </div>
        `;

        toolsList.appendChild(div);
    }
}

function formatToolName(name) {
    return name.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}

function sendMessage() {
    const input = document.getElementById("text-input");
    const text = input.value.trim();
    
    if (text && !isGenerating) {
        addMessage(text, "user");
        ws.send(JSON.stringify({
            type: "text",
            text: text,
            thinking: thinkingEnabled
        }));
        input.value = "";
        setGenerating(true);
        activeAgentMessage = null; // Reset for new turn
    }
}

// Initialize - Main Entry Point
document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const textInput = document.getElementById("text-input");
    const sendButton = document.getElementById("send-button");
    const micButton = document.getElementById("mic-button");
    const stopButton = document.getElementById("stop-button");
    const wakeWordToggle = document.getElementById("wake-word-toggle");
    const languageSelector = document.getElementById("language-selector");
    const sidebarToggle = document.getElementById("sidebar-toggle");
    const newChatBtn = document.getElementById("new-chat-btn");
    const deleteAllBtn = document.getElementById("delete-all-btn");
    
    // Settings Elements
    const settingsBtn = document.getElementById("settings-btn");
    const settingsModal = document.getElementById("settings-modal");
    const closeSettingsBtn = document.getElementById("close-settings");
    const saveSettingsBtn = document.getElementById("save-settings");
    
    // Memory Elements
    const memoryBtn = document.getElementById("memory-btn");
    const memoryModal = document.getElementById("memory-modal");
    const closeMemoryBtn = document.getElementById("close-memory");
    const addMemoryBtn = document.getElementById("add-memory-btn");
    const memoryKeyInput = document.getElementById("memory-key");
    const memoryValueInput = document.getElementById("memory-value");

    // Event Listeners
    if (sendButton) {
        sendButton.addEventListener("click", sendMessage);
    }

    if (textInput) {
        textInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    // Thinking Toggle
    const thinkingBtn = document.getElementById("thinking-toggle");
    if (thinkingBtn) {
        thinkingBtn.onclick = () => {
            thinkingEnabled = !thinkingEnabled;
            thinkingBtn.classList.toggle("active", thinkingEnabled);
        };
    }

    // TTS Toggle
    const ttsBtn = document.getElementById("tts-toggle");
    if (ttsBtn) {
        ttsBtn.onclick = async () => {
            ttsEnabled = !ttsEnabled;
            ttsBtn.classList.toggle("active", ttsEnabled);
            // Save only TTS setting to avoid saving pending tool changes
            try {
                await fetch("/api/settings", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        application: { tts_enabled: ttsEnabled }
                    })
                });
            } catch (e) {
                console.error("Error updating TTS:", e);
            }
        };
    }

    if (micButton) {
        micButton.addEventListener("click", () => {
            if (isRecording) {
                stopRecording();
            } else {
                startRecording();
            }
        });
    }

    if (stopButton) {
        stopButton.addEventListener("click", () => {
            ws.send(JSON.stringify({ type: "stop" }));
            setGenerating(false);
        });
    }

    if (wakeWordToggle) {
        wakeWordToggle.addEventListener("click", () => {
            wakeWordEnabled = !wakeWordEnabled;
            updateWakeWordUI();
            if (wakeWordEnabled) startWakeWordDetection();
            else stopWakeWordDetection();
        });
    }

    const sidebarOverlay = document.getElementById("sidebar-overlay");

    if (sidebarToggle) {
        sidebarToggle.addEventListener("click", () => {
            const sidebar = document.getElementById("sidebar");
            if (sidebar) {
                sidebar.classList.toggle("open");
                if (sidebarOverlay) {
                    sidebarOverlay.classList.toggle("active", sidebar.classList.contains("open"));
                }
            }
        });
    }

    if (sidebarOverlay) {
        sidebarOverlay.addEventListener("click", () => {
            const sidebar = document.getElementById("sidebar");
            if (sidebar) {
                sidebar.classList.remove("open");
                sidebarOverlay.classList.remove("active");
            }
        });
    }

    if (newChatBtn) {
        newChatBtn.addEventListener("click", createNewSession);
    }

    if (deleteAllBtn) {
        deleteAllBtn.addEventListener("click", async () => {
            if (confirm("Are you sure you want to delete ALL chats? This cannot be undone.")) {
                try {
                    await fetch("/api/sessions", { method: "DELETE" });
                    currentSessionId = null;
                    const conversation = document.getElementById("conversation");
                    if (conversation) {
                        conversation.innerHTML = "";
                        addMessage("All chats deleted. Starting fresh session.", "system");
                    }
                    await loadSessions();
                    createNewSession(); // Start fresh
                } catch (e) {
                    console.error("Error deleting all sessions:", e);
                }
            }
        });
    }

    // Settings Modal Logic
    if (settingsBtn) {
        settingsBtn.addEventListener("click", async () => {
            if (settingsModal) settingsModal.style.display = "block";
            await loadSettings();
        });
    }

    if (closeSettingsBtn) {
        closeSettingsBtn.addEventListener("click", () => {
            if (settingsModal) settingsModal.style.display = "none";
        });
    }

    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener("click", async () => {
            await saveSettings();
            if (settingsModal) settingsModal.style.display = "none";
        });
    }

    // Memory Modal Logic
    if (memoryBtn) {
        memoryBtn.addEventListener("click", async () => {
            if (memoryModal) memoryModal.style.display = "block";
            await loadMemories();
        });
    }

    if (closeMemoryBtn) {
        closeMemoryBtn.addEventListener("click", () => {
            if (memoryModal) memoryModal.style.display = "none";
        });
    }

    if (addMemoryBtn) {
        addMemoryBtn.addEventListener("click", async () => {
            const key = memoryKeyInput.value.trim();
            const value = memoryValueInput.value.trim();
            if (key && value) {
                await addMemory(key, value);
                memoryKeyInput.value = "";
                memoryValueInput.value = "";
                await loadMemories();
            }
        });
    }

    window.addEventListener("click", (event) => {
        if (settingsModal && event.target === settingsModal) {
            settingsModal.style.display = "none";
        }
        if (memoryModal && event.target === memoryModal) {
            memoryModal.style.display = "none";
        }
    });

    // Initial Load
    initWakeWordDetection();
    loadSettings();
});

function renderMath(element) {
    if (window.renderMathInElement) {
        renderMathInElement(element, {
            delimiters: [
                {left: '$$', right: '$$', display: true},
                {left: '$', right: '$', display: false},
                {left: '\\(', right: '\\)', display: false},
                {left: '\\[', right: '\\]', display: true}
            ],
            throwOnError: false
        });
    }
}
