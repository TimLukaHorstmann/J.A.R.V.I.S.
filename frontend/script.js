const ws = new WebSocket(`ws://${location.host}/ws`);

// DOM Elements
const statusDot = document.getElementById("connection-status");
const statusText = document.getElementById("status-text");
const conversation = document.getElementById("conversation");
const textInput = document.getElementById("text-input");
const sendButton = document.getElementById("send-button");
const micButton = document.getElementById("mic-button");
const wakeWordToggle = document.getElementById("wake-word-toggle");
const languageSelector = document.getElementById("language-selector");

// State
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let wakeWordEnabled = true;
let wakeWordRecognition = null;

// WebSocket Events
ws.onopen = () => {
    updateStatus("connected");
    console.log("WebSocket connected");
};

ws.onclose = () => {
    updateStatus("disconnected");
    console.log("WebSocket disconnected");
};

ws.onmessage = async (event) => {
    // Handle binary audio data
    if (event.data instanceof Blob) {
        playAudio(event.data);
        return;
    }

    // Handle JSON text data
    try {
        const data = JSON.parse(event.data);
        
        if (data.type === "transcription") {
            addMessage(data.text, "user");
        } else if (data.type === "text") {
            // Handle both streaming chunks and full content
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
        } else if (data.type === "error") {
            console.error("Server error:", data.message);
            addMessage(`Error: ${data.message}`, "system");
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

function appendToMessage(text, type) {
    if (!text) return; // Don't append empty text

    if (!currentMessageDiv || currentMessageType !== type) {
        addMessage("", type); // Create new empty bubble
        currentMessageDiv = conversation.lastElementChild;
        currentMessageType = type;
    }
    
    const contentDiv = currentMessageDiv.querySelector(".content");
    
    if (type === "jarvis") {
        // We need to store raw text to re-render markdown
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
    // Reset current streaming message if we add a new full message
    currentMessageDiv = null;
    currentMessageType = null;

    const messageDiv = document.createElement("div");
    messageDiv.className = `message ${sender}`;
    
    const contentDiv = document.createElement("div");
    contentDiv.className = "content";
    
    // Ensure text is not undefined/null
    const safeText = text || "";

    // Render Markdown for Jarvis messages
    if (sender === "jarvis" && window.marked) {
        contentDiv.dataset.raw = safeText;
        contentDiv.innerHTML = marked.parse(safeText);
    } else {
        contentDiv.textContent = safeText;
    }
    
    messageDiv.appendChild(contentDiv);
    conversation.appendChild(messageDiv);
    
    // Scroll to bottom
    conversation.scrollTop = conversation.scrollHeight;
}

// Audio Functions
function playAudio(blob) {
    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    
    audio.onended = () => {
        URL.revokeObjectURL(audioUrl);
        // Resume wake word detection if enabled
        if (wakeWordEnabled) {
            startWakeWordDetection();
        }
    };
    
    // Stop wake word detection while playing audio to avoid self-triggering
    stopWakeWordDetection();
    
    audio.play().catch(e => {
        console.error("Audio playback failed:", e);
    });
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
            // Send audio blob directly
            // Note: WebSocket.send() handles Blobs automatically
            ws.send(audioBlob);
            
            // Stop all tracks
            stream.getTracks().forEach(track => track.stop());
        };

        mediaRecorder.start();
        isRecording = true;
        micButton.classList.add("recording");
        stopWakeWordDetection(); // Stop wake word while recording
        
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
        // Wake word will be restarted after response audio plays
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
        console.log("Wake word error:", event.error);
        if (event.error === 'not-allowed') {
            wakeWordEnabled = false;
            updateWakeWordUI();
        }
    };
    
    wakeWordRecognition.onend = () => {
        if (wakeWordEnabled && !isRecording) {
            try {
                wakeWordRecognition.start();
            } catch (e) {
                // Ignore
            }
        }
    };

    if (wakeWordEnabled) {
        startWakeWordDetection();
    }
}

function startWakeWordDetection() {
    if (wakeWordRecognition && wakeWordEnabled) {
        try {
            wakeWordRecognition.start();
        } catch (e) {
            // Already started
        }
    }
}

function stopWakeWordDetection() {
    if (wakeWordRecognition) {
        try {
            wakeWordRecognition.stop();
        } catch (e) {
            // Ignore
        }
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
        // Send JSON message
        ws.send(JSON.stringify({
            type: "text",
            text: text,
            language: languageSelector.value
        }));
        
        addMessage(text, "user");
        textInput.value = "";
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

wakeWordToggle.addEventListener("click", () => {
    wakeWordEnabled = !wakeWordEnabled;
    updateWakeWordUI();
    
    if (wakeWordEnabled) {
        startWakeWordDetection();
    } else {
        stopWakeWordDetection();
    }
});

// Initialize
initWakeWordDetection();
