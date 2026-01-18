let ws;
let reconnectInterval = 1000;
const maxReconnectInterval = 30000;

// State
let asrConfig = { engine: 'whisper', mode: 'server' };
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let wakeWordEnabled = true;
let thinkingEnabled = true;
let ttsEnabled = true;
let wakeWordRecognition = null;
let recognition = null;
let currentSessionId = null;
let isGenerating = false;
let activeAgentMessage = null;
let currentAudio = null;
let serverWakeWordRecorder = null;
let serverWakeWordStream = null;

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
        
        // Send initial language
        const languageSelector = document.getElementById("language-selector");
        if (languageSelector) {
            ws.send(JSON.stringify({
                type: "language",
                lang: languageSelector.value
            }));
        }
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
            if (data.config && data.config.asr) {
                asrConfig = data.config.asr;
                console.log("ASR Config:", asrConfig);
            }
            if (!data.restored) {
                const conversation = document.getElementById("conversation");
                if (conversation) {
                    conversation.innerHTML = '';
                    addMessage("System initialized. Ready for input.", "system");
                }
            }
            loadSessions();
        } else if (data.type === "wake_word_detected") {
            console.log("Server detected wake word!");
            stopServerWakeWordDetection();
            startRecording();
        } else if (data.type === "history") {
            renderHistory(data.messages);
        } else if (data.type === "session_updated") {
            loadSessions();
        } else if (data.type === "transcription") {
            if (data.is_final) {
                addMessage(data.text, "user");
                setGenerating(true);
                activeAgentMessage = null;
                const input = document.getElementById("text-input");
                if (input) input.value = "";
            } else {
                // Partial
                const input = document.getElementById("text-input");
                if (input) input.value = data.text;
            }
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
    // Stop any currently playing audio
    stopAudioPlayback();

    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    audio.srcUrl = audioUrl; // Store for cleanup
    currentAudio = audio;
    
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
        currentAudio = null;
    };
    
    stopWakeWordDetection();
    audio.play().catch(e => console.error("Audio playback failed:", e));
}

function stopAudioPlayback() {
    if (currentAudio) {
        currentAudio.onended = null; // Prevent double trigger
        currentAudio.pause();
        
        if (currentAudio.srcUrl) {
            URL.revokeObjectURL(currentAudio.srcUrl);
        }
        
        if (window.jarvisVisualizer) {
            window.jarvisVisualizer.setSpeaking(false);
        }
        
        // Restore wake word if it was enabled globally
        if (wakeWordEnabled) {
            startWakeWordDetection();
        }
        
        currentAudio = null;
    }
}

// Recording Functions
async function startRecording() {
    stopAudioPlayback(); // Interrupt TTS
    if (isRecording) return; // Prevent multiple triggers

    // Check config
    if (asrConfig.mode === 'client') {
        // Check for SpeechRecognition support
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SR) {
            startClientSideRecording(SR);
            return;
        }
    }

    if (asrConfig.engine === 'vosk') {
        startStreamingRecording();
    } else {
        startServerSideRecording();
    }
}

// Streaming State
let audioContextStream = null;
let processor = null;
let inputStream = null;

async function startStreamingRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContextStream = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        inputStream = audioContextStream.createMediaStreamSource(stream);
        
        // Buffer size 4096
        processor = audioContextStream.createScriptProcessor(4096, 1, 1);
        
        inputStream.connect(processor);
        processor.connect(audioContextStream.destination);
        
        processor.onaudioprocess = (e) => {
            if (!isRecording) return;
            
            const inputData = e.inputBuffer.getChannelData(0);
            // Convert float32 to int16
            const buffer = new ArrayBuffer(inputData.length * 2);
            const view = new DataView(buffer);
            for (let i = 0; i < inputData.length; i++) {
                let s = Math.max(-1, Math.min(1, inputData[i]));
                view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
            }
            
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(buffer);
            }
        };
        
        isRecording = true;
        const micButton = document.getElementById("mic-button");
        if (micButton) micButton.classList.add("recording");
        stopWakeWordDetection();
        
    } catch (e) {
        console.error("Error starting streaming:", e);
        addMessage("Error accessing microphone.", "system");
    }
}

function startClientSideRecording(SR) {
    // Stop wake word detection immediately to free up the mic
    stopWakeWordDetection();
    
    // Set flag to prevent wake word from restarting in its onend handler
    isRecording = true; 
    const micButton = document.getElementById("mic-button");
    if (micButton) micButton.classList.add("recording");

    try {
        recognition = new SR();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'en-US';

        recognition.onstart = () => {
            console.log("Command recognition started");
        };

        recognition.onresult = (event) => {
            const lastResult = event.results[event.results.length - 1];
            if (lastResult.isFinal) {
                const transcript = lastResult[0].transcript.trim();
                if (transcript) {
                    console.log("Client STT Final:", transcript);
                    
                    // Add to UI immediately
                    addMessage(transcript, "user");
                    setGenerating(true);
                    activeAgentMessage = null;

                    // Send to backend
                    ws.send(JSON.stringify({
                        type: "config",
                        thinking: thinkingEnabled
                    }));
                    
                    ws.send(JSON.stringify({
                        type: "text",
                        text: transcript
                    }));
                }
            }
        };

        recognition.onerror = (event) => {
            console.error("Speech recognition error", event.error);
            if (event.error === 'no-speech') {
                // Just stop if no speech
                stopRecording();
            } else if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
                // Permission denied or insecure origin. Try fallback, but it might also fail.
                console.warn("Client STT not allowed. Falling back to server-side...");
                stopRecording(); // Stop the failed recognition instance
                startServerSideRecording();
            } else {
                // Fallback to server-side if other error?
                stopRecording();
                if (event.error !== 'aborted') {
                     addMessage(`Speech recognition error: ${event.error}. Falling back to server-side...`, "system");
                     startServerSideRecording();
                }
            }
        };

        recognition.onend = () => {
            isRecording = false;
            const micButton = document.getElementById("mic-button");
            if (micButton) micButton.classList.remove("recording");
            
            if (wakeWordEnabled) {
                startWakeWordDetection();
            }
        };

        // Small delay to ensure wake word recognition has fully stopped/released mic
        setTimeout(() => {
            try {
                recognition.start();
            } catch (e) {
                console.error("Failed to start recognition after delay:", e);
                isRecording = false;
                if (micButton) micButton.classList.remove("recording");
            }
        }, 100);

    } catch (e) {
        console.error("Failed to start client STT:", e);
        isRecording = false;
        if (micButton) micButton.classList.remove("recording");
        startServerSideRecording();
    }
}

async function startServerSideRecording() {
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
        let msg = "Error accessing microphone. Please check permissions.";
        if (location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
            msg += " Note: Microphone access usually requires HTTPS or localhost.";
        }
        addMessage(msg, "system");
    }
}

function stopRecording() {
    if (recognition && isRecording) {
        recognition.stop();
        // isRecording will be set to false in onend
    }

    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        const micButton = document.getElementById("mic-button");
        if (micButton) micButton.classList.remove("recording");
    }

    if (processor && isRecording) {
        processor.disconnect();
        inputStream.disconnect();
        if (audioContextStream) audioContextStream.close();
        processor = null;
        inputStream = null;
        audioContextStream = null;
        
        isRecording = false;
        const micButton = document.getElementById("mic-button");
        if (micButton) micButton.classList.remove("recording");
    }
}

// Wake Word Detection
function initWakeWordDetection() {
    const wakeWordToggle = document.getElementById("wake-word-toggle");
    
    // Check if we should use server-side fallback immediately (e.g. if on Linux/Chromium without keys)
    // For now, we try client-side first, and fallback on error.
    
    if (!('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)) {
        console.warn("Speech recognition not supported. Using Server-Side Detection.");
        startServerWakeWordDetection();
        return;
    }

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    try {
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
            console.warn("SpeechRecognition error:", event.error);
            if (event.error === 'not-allowed') {
                wakeWordEnabled = false;
                updateWakeWordUI();
            } else if (event.error === 'network' || event.error === 'service-not-allowed' || event.error === 'no-speech') {
                // Fallback to server-side
                console.log("Switching to Server-Side Wake Word Detection due to error.");
                if (wakeWordRecognition) {
                    try { wakeWordRecognition.abort(); } catch(e) {}
                    wakeWordRecognition = null;
                }
                startServerWakeWordDetection();
            }
        };
        
        wakeWordRecognition.onend = () => {
            if (wakeWordEnabled && !isRecording && wakeWordRecognition) {
                try { wakeWordRecognition.start(); } catch (e) {}
            }
        };

        if (wakeWordEnabled) {
            startWakeWordDetection();
        }
    } catch (e) {
        console.error("Error initializing SpeechRecognition:", e);
        startServerWakeWordDetection();
    }
}

function startServerWakeWordDetection() {
    if (!wakeWordEnabled || isRecording) return;
    if (serverWakeWordRecorder && serverWakeWordRecorder.state === 'recording') return;

    console.log("Starting Server-Side Wake Word Detection...");
    
    // Notify server
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "wake_word_detection", enabled: true }));
    }

    navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
            serverWakeWordStream = stream;
            
            // Use AudioContext to get raw PCM data
            const audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
            const source = audioContext.createMediaStreamSource(stream);
            const processor = audioContext.createScriptProcessor(4096, 1, 1);
            
            source.connect(processor);
            processor.connect(audioContext.destination);
            
            processor.onaudioprocess = (e) => {
                if (!ws || ws.readyState !== WebSocket.OPEN) return;
                
                const inputData = e.inputBuffer.getChannelData(0);
                // Convert Float32 to Int16
                const buffer = new ArrayBuffer(inputData.length * 2);
                const view = new DataView(buffer);
                for (let i = 0; i < inputData.length; i++) {
                    const s = Math.max(-1, Math.min(1, inputData[i]));
                    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
                }
                ws.send(buffer);
            };
            
            // Store context to close later
            serverWakeWordRecorder = {
                stop: () => {
                    processor.disconnect();
                    source.disconnect();
                    audioContext.close();
                },
                state: 'recording'
            };
        })
        .catch(err => {
            console.error("Error accessing microphone for wake word:", err);
            // Only disable if it's a permission error
            if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                wakeWordEnabled = false;
                updateWakeWordUI();
            }
        });
}

function stopServerWakeWordDetection() {
    if (serverWakeWordRecorder) {
        serverWakeWordRecorder.stop();
        serverWakeWordRecorder = null;
    }
    if (serverWakeWordStream) {
        serverWakeWordStream.getTracks().forEach(track => track.stop());
        serverWakeWordStream = null;
    }
    // Notify server
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "wake_word_detection", enabled: false }));
    }
}

function startWakeWordDetection() {
    if (wakeWordRecognition && wakeWordEnabled) {
        try { wakeWordRecognition.start(); } catch (e) {}
    } else if (wakeWordEnabled) {
        startServerWakeWordDetection();
    }
}

function stopWakeWordDetection() {
    if (wakeWordRecognition) {
        try { wakeWordRecognition.abort(); } catch (e) {}
    }
    stopServerWakeWordDetection();
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
    google_calendar: {
        title: 'Google Calendar',
        desc: 'Manage your calendar events, schedule meetings, and check availability.'
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
    },
    eufy: {
        title: 'Eufy Security',
        desc: 'Integration for Eufy cameras to view live streams and check status.'
    },
    notion: {
        title: 'Notion',
        desc: 'Integrates with Notion to read and write notes, tasks, and databases.'
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
    stopAudioPlayback(); // Interrupt TTS
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

    if (languageSelector) {
        languageSelector.addEventListener("change", () => {
            const lang = languageSelector.value;
            console.log("Language changed to:", lang);
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: "language",
                    lang: lang
                }));
            }
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
