const ws = new WebSocket(`ws://${location.host}/ws`);
const indicator = document.getElementById("indicator");
const textInput = document.getElementById("textInput");
const sendText = document.getElementById("sendText");
const micButton = document.getElementById("micButton");
const conversation = document.getElementById("conversation");
const languageSelector = document.getElementById("languageSelector");

let recorder = null;
let mediaStream = null;
let isRecording = false;
let selectedLanguage = "en"; // Default language


// Replace the existing wake word initialization 
let wakeWordRecognition = null;

function initWakeWordDetection() {
  if (!('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)) {
    console.warn("Speech recognition not supported in this browser");
    return;
  }
  
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  
  // Clean up existing instance if any
  if (wakeWordRecognition) {
    try {
      wakeWordRecognition.stop();
    } catch (e) {
      console.warn("Error stopping previous wake word detection:", e);
    }
  }
  
  wakeWordRecognition = new SR();
  wakeWordRecognition.continuous = true;
  wakeWordRecognition.interimResults = false;
  wakeWordRecognition.lang = 'en-US';
  
  wakeWordRecognition.onresult = e => {
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) {
        const t = e.results[i][0].transcript.trim().toLowerCase();
        console.log("Wake word detection heard:", t);
        if (t.includes('hey jarvis')) {
          // auto-trigger the mic when you say "Hey Jarvis"
          if (!isRecording) startRecording();
        }
      }
    }
  };
  
  wakeWordRecognition.onend = () => {
    console.log("Wake word detection ended, restarting...");
    // Restart wake word detection if it ended unexpectedly
    if (!isRecording) { // Don't restart if we're already recording
      setTimeout(() => {
        initWakeWordDetection();
      }, 100);
    }
  };
  
  wakeWordRecognition.onerror = err => {
    console.error("Wake-word error:", err);
    // Don't restart on errors like "no-speech" to avoid excessive retries
    if (err.error !== 'no-speech' && err.error !== 'aborted') {
      setTimeout(() => {
        initWakeWordDetection();
      }, 1000);
    }
  };
  
  wakeWordRecognition.start();
  console.log("Wake word detection started");
}

// Call this on page load
initWakeWordDetection();

// Audio Queue System
class AudioQueue {
  constructor() {
    this.queue = [];
    this.isPlaying = false;
    this.currentAudio = null;
    
    // Create a single Audio element we'll reuse
    this.audioElement = new Audio();
    this.audioElement.addEventListener('ended', () => this.playNext());
    this.audioElement.addEventListener('error', (e) => {
      console.error('Audio playback error:', e);
      this.playNext();
    });
  }
  
  add(audioBlob) {
    const url = URL.createObjectURL(audioBlob);
    this.queue.push(url);
    
    // Start playing if not already playing
    if (!this.isPlaying) {
      this.playNext();
    }
  }
  
  playNext() {
    // Clean up previous audio URL if exists
    if (this.currentAudio) {
      URL.revokeObjectURL(this.currentAudio);
      this.currentAudio = null;
    }
    
    if (this.queue.length === 0) {
      this.isPlaying = false;
      return;
    }
    
    this.isPlaying = true;
    this.currentAudio = this.queue.shift();
    this.audioElement.src = this.currentAudio;
    
    // Play with a small delay to ensure smooth transition
    setTimeout(() => {
      const playPromise = this.audioElement.play();
      
      // Handle play() promise to avoid DOMException
      if (playPromise !== undefined) {
        playPromise.catch(error => {
          console.warn('Audio playback was prevented:', error);
          // Try again after user interaction or skip
          this.playNext();
        });
      }
    }, 50);
  }
  
  clear() {
    // Clean up all URLs in the queue
    this.queue.forEach(url => URL.revokeObjectURL(url));
    this.queue = [];
    
    if (this.currentAudio) {
      this.audioElement.pause();
      URL.revokeObjectURL(this.currentAudio);
      this.currentAudio = null;
    }
    
    this.isPlaying = false;
  }
}

// Add this after creating the audioQueue
let audioInitialized = false;

// Initialize audio playback on first user interaction
document.addEventListener('click', () => {
  if (!audioInitialized) {
    // Create and play a silent audio element to unlock audio
    const silentAudio = new Audio("data:audio/mp3;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4LjI5LjEwMAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABIADAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV6urq6urq6urq6urq6urq6urq6urq6v////////////////////////////////8AAAAATGF2YzU4LjU0AAAAAAAAAAAAAAAAJAZtAAAAAAAAASDoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==");
    silentAudio.play().then(() => {
      audioInitialized = true;
      console.log("Audio playback initialized");
    }).catch(err => {
      console.warn("Audio initialization failed:", err);
    });
  }
}, { once: false });

// Create audio queue instance
const audioQueue = new AudioQueue();

// User location tracking
let userLocation = {
  city: localStorage.getItem("jarvisUserCity") || null,
  latitude: localStorage.getItem("jarvisUserLat") || null,
  longitude: localStorage.getItem("jarvisUserLon") || null,
  lastUpdated: localStorage.getItem("jarvisLocationTimestamp") || null
};

// Get user location if we don't have it or it's older than 24 hours
function updateUserLocation() {
  const ONE_DAY = 24 * 60 * 60 * 1000; // 24 hours in milliseconds
  const needsUpdate = !userLocation.lastUpdated || 
                     (Date.now() - parseInt(userLocation.lastUpdated)) > ONE_DAY;
  
  if (needsUpdate && navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(async position => {
      userLocation.latitude = position.coords.latitude;
      userLocation.longitude = position.coords.longitude;
      userLocation.lastUpdated = Date.now();
      
      // Save to localStorage
      localStorage.setItem("jarvisUserLat", userLocation.latitude);
      localStorage.setItem("jarvisUserLon", userLocation.longitude);
      localStorage.setItem("jarvisLocationTimestamp", userLocation.lastUpdated);
      
      // Reverse geocode to get city name
      try {
        const response = await fetch(
          `https://geocoding-api.open-meteo.com/v1/search?latitude=${userLocation.latitude}&longitude=${userLocation.longitude}&count=1`
        );
        const data = await response.json();
        if (data.results && data.results.length > 0) {
          userLocation.city = data.results[0].name;
          localStorage.setItem("jarvisUserCity", userLocation.city);
          console.log(`User location set to: ${userLocation.city}`);
        }
      } catch (err) {
        console.error("Failed to reverse geocode location:", err);
      }
    }, error => {
      console.warn("Geolocation error:", error.message);
    }, {
      enableHighAccuracy: false,
      timeout: 5000,
      maximumAge: ONE_DAY
    });
  }
}

// Call this when app starts
updateUserLocation();

// Initialize language from local storage if available
if (localStorage.getItem("jarvisLanguage")) {
  selectedLanguage = localStorage.getItem("jarvisLanguage");
  languageSelector.value = selectedLanguage;
}

// Language selection handler
languageSelector.addEventListener("change", function() {
  selectedLanguage = this.value;
  localStorage.setItem("jarvisLanguage", selectedLanguage);
});

// Auto-resize textarea as user types
textInput.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = (this.scrollHeight) + 'px';
  // Limit to 150px max height
  if (this.scrollHeight > 150) {
    this.style.overflowY = 'auto';
    this.style.height = '150px';
  } else {
    this.style.overflowY = 'hidden';
  }
});

// WS lifecycle with better status indicators
ws.onopen = () => {
  console.log("WebSocket ▶ connected");
  indicator.textContent = "Connected";
  indicator.style.backgroundColor = "#3DD6F5";
};

ws.onerror = err => {
  console.error("WebSocket ▶ error", err);
  indicator.textContent = "Connection error!";
  indicator.style.backgroundColor = "#FF4A6E";
};

ws.onclose = () => {
  console.log("WebSocket ▶ closed");
  indicator.textContent = "Disconnected";
  indicator.style.backgroundColor = "#666";
};

ws.binaryType = "arraybuffer";

// Modified appendMessage function to handle tool calls
function appendMessage(sender, text) {
  // Remove typing indicator if present
  const typingIndicator = document.querySelector('.typing-indicator');
  if (typingIndicator) {
    typingIndicator.remove();
  }
  
  const messageDiv = document.createElement("div");
  messageDiv.className = `message ${sender}`;
  
  // Create avatar
  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  
  // Use icons instead of text for avatars
  if (sender === "user") {
    avatar.innerHTML = '<i class="bi bi-person-fill"></i>';
  } else {
    avatar.innerHTML = '<i class="bi bi-robot"></i>';
  }
  
  // Create message content
  const content = document.createElement("div");
  content.className = "message-content";
  
  if (sender === "jarvis") {
    // Process the message to find and format tool calls
    let processedContent = processToolCalls(text);
    
    if (typeof processedContent === 'string') {
      // Render markdown content
      content.innerHTML = marked.parse(processedContent);
    } else {
      content.appendChild(processedContent);
    }
  } else {
    // Regular user message - no markdown for user messages
    content.textContent = text;
  }
  
  // Append elements
  messageDiv.appendChild(content);
  messageDiv.appendChild(avatar);
  conversation.appendChild(messageDiv);
  
  // Scroll to bottom
  conversation.scrollTop = conversation.scrollHeight;
}

// Process text to extract and format tool calls
function processToolCalls(text) {
  // Check if there are tool calls in the text
  if (!text.includes("<tool_call>")) {
    return text;
  }
  
  const fragment = document.createDocumentFragment();
  const toolCallRegex = /<tool_call>([\s\S]*?)<\/tool_call>/g;
  
  let lastIndex = 0;
  let match;
  
  while ((match = toolCallRegex.exec(text)) !== null) {
    // Add text before tool call - with markdown parsing
    if (match.index > lastIndex) {
      const textBefore = document.createElement('div');
      textBefore.innerHTML = marked.parse(text.substring(lastIndex, match.index));
      fragment.appendChild(textBefore);
    }
    
    // Process the tool call
    try {
      const toolCallJson = match[1].trim();
      const toolData = JSON.parse(toolCallJson);
      // Ensure tool call is collapsed by default
      fragment.appendChild(createToolCallElement(toolData, true));
    } catch (e) {
      console.error("Error parsing tool call:", e);
      const fallbackText = document.createTextNode(match[0]);
      fragment.appendChild(fallbackText);
    }
    
    lastIndex = match.index + match[0].length;
  }
  
  // Add any remaining text after the last tool call - with markdown parsing
  if (lastIndex < text.length) {
    const textAfter = document.createElement('div');
    textAfter.innerHTML = marked.parse(text.substring(lastIndex));
    fragment.appendChild(textAfter);
  }
  
  return fragment;
}

// Create a formatted tool call element
function createToolCallElement(toolData, collapsed = true) {
  const toolName = toolData.name || "Unknown Tool";
  const args = toolData.arguments || {};
  
  // Create container
  const toolCallDiv = document.createElement("div");
  toolCallDiv.className = "tool-call";
  if (collapsed) {
    toolCallDiv.classList.add("collapsed");
  }
  
  // Create header with icon
  const headerDiv = document.createElement("div");
  headerDiv.className = "tool-call-header";
  
  // Select appropriate icon based on tool name
  let iconClass = "bi-robot";
  if (toolName.toLowerCase().includes("map")) {
    iconClass = "bi-map";
  } else if (toolName.toLowerCase().includes("search")) {
    iconClass = "bi-search";
  } else if (toolName.toLowerCase().includes("fetch")) {
    iconClass = "bi-cloud-download";
  } else if (toolName.toLowerCase().includes("magic")) {
    iconClass = "bi-stars";
  } else if (toolName.toLowerCase().includes("google")) {
    iconClass = "bi-google";
  } else if (toolName.toLowerCase().includes("brave")) {
    iconClass = "bi-search";
  }
  
  // Create icon element
  const iconDiv = document.createElement("div");
  iconDiv.className = "tool-icon";
  iconDiv.innerHTML = `<i class="bi ${iconClass}"></i>`;
  
  // Create tool name element
  const nameDiv = document.createElement("div");
  nameDiv.className = "tool-name";
  nameDiv.textContent = formatToolName(toolName);
  
  // Add status indicator
  const statusDiv = document.createElement("div");
  statusDiv.className = "tool-status pending";
  statusDiv.textContent = "Working...";
  
  // Toggle button
  const toggleBtn = document.createElement("div");
  toggleBtn.className = "tool-toggle";
  toggleBtn.innerHTML = collapsed ? '<i class="bi bi-chevron-down"></i>' : '<i class="bi bi-chevron-up"></i>';
  
  // Add click handler to toggle visibility - fixed to work correctly
  const toggleCollapse = () => {
    toolCallDiv.classList.toggle("collapsed");
    toggleBtn.innerHTML = toolCallDiv.classList.contains("collapsed") 
      ? '<i class="bi bi-chevron-down"></i>' 
      : '<i class="bi bi-chevron-up"></i>';
  };
  
  // Attach click handler to both header and toggle button
  headerDiv.addEventListener('click', toggleCollapse);
  toggleBtn.addEventListener('click', (e) => {
    e.stopPropagation(); // Prevent double-triggering via header
    toggleCollapse();
  });
  
  // Assemble header
  headerDiv.appendChild(iconDiv);
  headerDiv.appendChild(nameDiv);
  headerDiv.appendChild(statusDiv);
  toolCallDiv.appendChild(headerDiv);
  toolCallDiv.appendChild(toggleBtn);
  
  // Create content container
  const contentDiv = document.createElement("div");
  contentDiv.className = "tool-content";
  
  // Add the arguments as code - USE PRE ELEMENT for better formatting
  const codeDiv = document.createElement("pre");
  codeDiv.className = "tool-code";
  
  // Format arguments
  let formattedArgs;
  if (typeof args === 'string') {
    try {
      // Try to parse as JSON if it's a string
      const jsonObj = JSON.parse(args);
      formattedArgs = JSON.stringify(jsonObj, null, 2);
    } catch {
      // If it's not valid JSON, display as-is without truncation
      formattedArgs = args;
    }
  } else {
    // If it's already an object, format it properly
    formattedArgs = JSON.stringify(args, null, 2);
  }

  // Ensure the code block uses pre to preserve formatting and prevent truncation
  codeDiv.className = "tool-code";
  codeDiv.textContent = formattedArgs; // textContent ensures proper escaping
  contentDiv.appendChild(codeDiv);
  toolCallDiv.appendChild(contentDiv);
  
  // Store tool data for future reference
  toolCallDiv.dataset.toolName = toolName;
  
  return toolCallDiv;
}


// Helper function to format tool names nicely
function formatToolName(name) {
  return name
    .replace(/_/g, ' ')
    .replace(/([A-Z])/g, ' $1') // Add space before capital letters
    .split(' ')
    .filter(word => word.length > 0)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

// Start response handling - for streaming audio response
let isReceivingAudioResponse = false;

ws.onmessage = ev => {
  console.log("WS message received, type:", typeof ev.data);
  
  if (typeof ev.data === "string") {
    let msg;
    try {
      console.log("Raw string data:", ev.data);
      msg = JSON.parse(ev.data);
      console.log("Parsed server event ▶", msg);
    } catch (err) {
      console.error("Invalid JSON:", ev.data, err);
      indicator.textContent = "Received invalid data";
      return;
    }
    
    if (!msg || !msg.event) {
      console.warn("Received message without event type:", msg);
      return;
    }
    
    switch (msg.event) {
      case "processing":
        indicator.textContent = "Processing...";
        showTypingIndicator();
        // Reset audio state for new response
        isReceivingAudioResponse = true;
        
        // REMOVED: Don't clear previous tool messages anymore
        // Let each message have its own tool calls
        break;
        
        case "text_response":
          indicator.textContent = "Connected";
          
          // Always remove typing indicator when receiving a text response
          const responseTypingIndicator = document.querySelector('.typing-indicator');
          if (responseTypingIndicator) {
            responseTypingIndicator.remove();
          }
          
          // Check if there's a thinking message we can update instead of creating a new one
          const thinkingMsg = document.querySelector('.message.jarvis.assistant-thinking');
          if (thinkingMsg) {
            // Convert the thinking message into a regular message with the response
            thinkingMsg.classList.remove('assistant-thinking');
            
            // Get the content container (excluding any tool calls)
            const contentContainer = thinkingMsg.querySelector('.message-content');
            
            // Create a response div with markdown rendering
            const responseDiv = document.createElement('div');
            responseDiv.className = 'assistant-response';
            responseDiv.innerHTML = marked.parse(msg.text);
            
            // Add response after the tools container
            contentContainer.appendChild(responseDiv);
          } else {
            // No thinking message found, create a new message
            appendMessage("jarvis", msg.text);
          }
          
          // Signal end of audio response
          isReceivingAudioResponse = false;
          
          // Scroll to bottom
          conversation.scrollTop = conversation.scrollHeight;
          break;

      case "tool_call":
        console.log("⚙️ Tool call received:", msg.name);
        // Remove typing indicator if present
        const typingIndicator = document.querySelector('.typing-indicator');
        if (typingIndicator) {
          typingIndicator.remove();
        }
        
        // Handle tool calls with the appropriate UI
        handleToolCall(msg.name, msg.arguments);
        break;
        
      case "tool_result":
        console.log("🔧 Tool result received:", msg.tool);
        if (msg.tool && msg.result) {
          // Find the matching tool call element and add result
          appendToolResult(msg.tool, msg.result);
        }
        break;
        
      case "transcription":
        // when the server tells us "here's what I heard", show it as your bubble
        appendMessage("user", msg.text);
        break;

      case "transcription_debug":
        console.log("Transcription debug:", msg.text);
        break;
        
      default:
        console.warn("Unknown event:", msg.event);
    }
  } else if (ev.data instanceof ArrayBuffer) {
    console.log("Received audio data, length:", ev.data.byteLength);
    
    // Create a blob from the audio buffer
    const blob = new Blob([ev.data], { type: "audio/wav" });
    
    // Add to our queue instead of immediately playing
    audioQueue.add(blob);
  } else {
    console.warn("Received unknown data type:", ev.data);
  }
};



// Function to append a tool result to its corresponding tool call
function appendToolResult(toolName, result) {
  // Find any assistant message that has this tool
  const toolCall = document.querySelector(`.tool-call[data-tool-name="${toolName}"]`);
  
  if (toolCall) {
    // Check if it already has a result
    if (!toolCall.querySelector('.tool-result')) {
      // Update status indicator
      const statusDiv = toolCall.querySelector('.tool-status');
      if (statusDiv) {
        statusDiv.className = "tool-status completed";
        statusDiv.textContent = "Completed";
      }
      
      // Stop the pulsing animation on the icon
      const icon = toolCall.querySelector('.tool-icon');
      if (icon) {
        icon.style.animation = 'none';
      }
      
      // Add the result to the content div
      const contentDiv = toolCall.querySelector('.tool-content');
      if (contentDiv) {
        // Use PRE element for better code formatting
        const resultDiv = document.createElement("pre");
        resultDiv.className = 'tool-result';
        
        // Format the result if it's JSON
        let formattedResult;
        try {
          // Try to parse as JSON
          const jsonResult = JSON.parse(result);
          formattedResult = JSON.stringify(jsonResult, null, 2);
        } catch (e) {
          formattedResult = result;
        }
        
        resultDiv.textContent = formattedResult; // Use textContent to ensure proper escaping
        contentDiv.appendChild(resultDiv);
        
        // Keep tool result collapsed by default
        // toolCall.classList.remove('collapsed');
        // const toggleBtn = toolCall.querySelector('.tool-toggle');
        // if (toggleBtn) {
        //   toggleBtn.innerHTML = '<i class="bi bi-chevron-up"></i>';
        // }
        
        // Scroll to ensure visibility
        conversation.scrollTop = conversation.scrollHeight;
      }
    }
  }
}


function handleToolCall(toolName, argumentsStr) {
  console.log("Handling tool call:", toolName, argumentsStr);
  
  // Find existing assistant message or create one as a container
  let messageDiv = document.querySelector('.message.jarvis.assistant-thinking');
  let isNewMessage = false;
  
  if (!messageDiv) {
    isNewMessage = true;
    messageDiv = document.createElement("div");
    messageDiv.className = "message jarvis assistant-thinking";
    
    // Create avatar
    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.innerHTML = '<i class="bi bi-robot"></i>';
    
    // Create message content container
    const contentContainer = document.createElement("div");
    contentContainer.className = "message-content";
    
    // Create a tools container
    const toolsContainer = document.createElement("div");
    toolsContainer.className = "tools-container";
    
    // Add a header for the tools section
    const toolsHeader = document.createElement("div");
    toolsHeader.className = "tools-header";
    toolsHeader.innerHTML = '<i class="bi bi-gear-fill"></i> Using tools to answer your question...';
    toolsContainer.appendChild(toolsHeader);
    
    contentContainer.appendChild(toolsContainer);
    messageDiv.appendChild(contentContainer);
    messageDiv.appendChild(avatar);
  }
  
  // Parse arguments if needed
  let args = argumentsStr;
  if (typeof args === 'string') {
    try {
      args = JSON.parse(args);
    } catch (e) {
      console.warn("Could not parse tool arguments as JSON:", e);
    }
  }
  
  // Create tool call element
  const toolData = {
    name: toolName,
    arguments: args
  };
  
  // Get or update the tool call visualization
  const toolsContainer = messageDiv.querySelector('.tools-container');
  
  // Check if this tool already exists
  let existingToolCall = messageDiv.querySelector(`.tool-call[data-tool-name="${toolName}"]`);
  
  if (existingToolCall) {
    // Update existing tool call
    const wasCollapsed = existingToolCall.classList.contains('collapsed');
    existingToolCall.remove();
    
    // Create new tool call with the same collapsed state
    const newToolCall = createToolCallElement(toolData, wasCollapsed);
    toolsContainer.appendChild(newToolCall);
  } else {
    // Create new tool call (always collapsed initially)
    toolsContainer.appendChild(createToolCallElement(toolData, true));
  }
  
  // If this is a new message, add it to the conversation
  if (isNewMessage) {
    conversation.appendChild(messageDiv);
  }
  
  // Scroll to bottom
  conversation.scrollTop = conversation.scrollHeight;
  
  // Show typing indicator after tool call to indicate processing continues
  // Only add a new typing indicator if the previous one was removed
  if (!document.querySelector('.typing-indicator')) {
    showTypingIndicator();
  }
}


// Add showTypingIndicator function if it doesn't exist
function showTypingIndicator() {
  // Remove existing typing indicator
  const existingIndicator = document.querySelector('.typing-indicator');
  if (existingIndicator) {
    existingIndicator.remove();
  }
  
  // Create new typing indicator
  const indicator = document.createElement('div');
  indicator.className = 'typing-indicator';
  
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement('div');
    dot.className = 'typing-dot';
    indicator.appendChild(dot);
  }
  
  conversation.appendChild(indicator);
  conversation.scrollTop = conversation.scrollHeight;
}

sendText.addEventListener("click", () => {
  const text = textInput.value.trim();
  if (!text) return;
  
  // Check WebSocket connection
  if (ws.readyState !== WebSocket.OPEN) {
    console.error("WebSocket not connected!");
    indicator.textContent = "Not connected!";
    indicator.style.backgroundColor = "#FF4A6E";
    return;
  }
  
  // Clear the audio queue when sending a new message
  audioQueue.clear();
  
  appendMessage("user", text);
  
  try {
    const payload = JSON.stringify({ 
      type: "text", 
      text,
      language: selectedLanguage,
      location: userLocation.city || null,
      coordinates: userLocation.latitude && userLocation.longitude ? 
        { lat: userLocation.latitude, lon: userLocation.longitude } : null
    });
    console.log("Sending to server:", payload);
    ws.send(payload);
    textInput.value = "";
    // Reset textarea height
    textInput.style.height = 'auto';
    showTypingIndicator();
    indicator.textContent = "Processing...";
  } catch (err) {
    console.error("Failed to send message:", err);
    indicator.textContent = "Failed to send message!";
    indicator.style.backgroundColor = "#FF4A6E";
  }
});

textInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendText.click();
  }
});

micButton.addEventListener("click", () => {
  if (isRecording) {
    stopRecording();
  } else {
    startRecording();
  }
});

function startRecording() {
  // Clear the audio queue when starting a new recording
  audioQueue.clear();
  
  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
      mediaStream = stream;
      
      // Modern approach using AnalyserNode instead of ScriptProcessor
      const audioContext = new AudioContext();
      const analyser = audioContext.createAnalyser();
      const microphone = audioContext.createMediaStreamSource(stream);
      
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.5;
      microphone.connect(analyser);
      
      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);
      
      let lastSpokeAt = Date.now();
      let silenceDetectionInterval = setInterval(() => {
        analyser.getByteFrequencyData(dataArray);
        
        // Calculate average volume level
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
          sum += dataArray[i];
        }
        const average = sum / bufferLength;
        
        if (average > 15) { // Threshold for speech detection
          lastSpokeAt = Date.now();
        } else if (Date.now() - lastSpokeAt > 2500) { // 1.5s of silence
          clearInterval(silenceDetectionInterval);
          stopRecording();
        }
      }, 100);
      
      // Rest of your recorder setup code
      let mimeType = 'audio/webm';
      
      if (MediaRecorder.isTypeSupported('audio/wav')) {
        mimeType = 'audio/wav';
      } else if (MediaRecorder.isTypeSupported('audio/webm;codecs=pcm')) {
        mimeType = 'audio/webm;codecs=pcm';
      }
      
      console.log(`Using MIME type: ${mimeType} for recording`);
      recorder = new MediaRecorder(stream, { mimeType: mimeType });
      
      // Existing chunk collection code...
      const audioChunks = [];
      
      recorder.ondataavailable = e => {
        if (e.data.size > 0) {
          audioChunks.push(e.data);
        }
      };
      
      // Existing onstop handler...
      recorder.onstop = () => {
        clearInterval(silenceDetectionInterval);
        // Rest of your existing onstop code...
        if (audioChunks.length === 0) {
          console.error("No audio data collected");
          return;
        }
        
        const audioBlob = new Blob(audioChunks);
        console.log(`Audio recorded: ${audioBlob.size} bytes, type: ${audioBlob.type}`);
        
        // Send metadata first
        ws.send(JSON.stringify({
          type: "audio_meta",
          language: selectedLanguage,
          location: userLocation.city || null,
          coordinates: userLocation.latitude && userLocation.longitude ? 
            { lat: userLocation.latitude, lon: userLocation.longitude } : null,
          format: mimeType
        }));
        
        // Convert to ArrayBuffer and send
        audioBlob.arrayBuffer().then(buffer => {
          // Send the audio data in smaller chunks to avoid WebSocket frame size issues
          const CHUNK_SIZE = 16384; // 16KB chunks
          let offset = 0;
          
          while (offset < buffer.byteLength) {
            const size = Math.min(CHUNK_SIZE, buffer.byteLength - offset);
            const chunk = buffer.slice(offset, offset + size);
            ws.send(chunk);
            offset += size;
          }
          
          // Send an empty buffer to signal the end of the audio stream
          ws.send(new ArrayBuffer(0));
          console.log(`Sent audio data in ${Math.ceil(buffer.byteLength/CHUNK_SIZE)} chunks`);
        }).catch(err => {
          console.error("Error sending audio data:", err);
        });
      };
      
      recorder.start(250);
      micButton.classList.add("recording");
      micButton.innerHTML = '<i class="bi bi-mic-fill"></i>';
      indicator.textContent = "Recording...";
      indicator.style.backgroundColor = "#FF4A6E";
      isRecording = true;
      console.log("Started recording");
    })
    .catch(err => {
      console.error("Mic error ▶", err);
      alert("Could not access microphone.");
    });
}

function stopRecording() {
  if (recorder && recorder.state !== "inactive") {
    recorder.stop();
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach(t => t.stop());
  }
  micButton.classList.remove("recording");
  micButton.innerHTML = '<i class="bi bi-mic-fill"></i>';
  indicator.textContent = "Processing...";
  indicator.style.backgroundColor = "#3DD6F5";
  isRecording = false;
  showTypingIndicator();
  console.log("Stopped recording");
}

// Initialize textarea height
textInput.setAttribute('style', 'height:' + (textInput.scrollHeight) + 'px;overflow-y:hidden;');