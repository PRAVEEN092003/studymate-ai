document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const chatForm = document.getElementById("chat-form");
    const userInput = document.getElementById("user-input");
    const sendButton = document.getElementById("send-button");
    const chatMessages = document.getElementById("chat-messages");
    const loadingIndicator = document.getElementById("loading-indicator");
    const errorBanner = document.getElementById("error-banner");
    const errorMessageText = document.getElementById("error-message-text");
    const dismissErrorBtn = document.getElementById("dismiss-error-btn");
    const retryBtn = document.getElementById("retry-btn");
    const healthBadge = document.getElementById("health-badge");
    const newChatBtn = document.getElementById("new-chat-btn");
    const sidebarNewChatBtn = document.getElementById("sidebar-new-chat-btn");
    const sessionsList = document.getElementById("sessions-list");
    const noSessionsMsg = document.getElementById("no-sessions-msg");
    const chatSidebar = document.getElementById("chat-sidebar");
    const toggleSidebarBtn = document.getElementById("toggle-sidebar-btn");
    const sidebarCloseBtn = document.getElementById("sidebar-close-btn");
    const sidebarBackdrop = document.getElementById("sidebar-backdrop");
    const activeSessionTitle = document.getElementById("active-session-title");
    const sessionSearchInput = document.getElementById("session-search-input");
    const sessionsCounter = document.getElementById("sessions-counter");
    const charCounter = document.getElementById("char-counter");
    const themeToggleBtn = document.getElementById("theme-toggle-btn");
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || "";

    // State
    let sessionId = localStorage.getItem("current_session_id") || generateUUID();
    let isSubmitting = false;
    let lastFailedMessage = null;
    let allSessions = [];

    localStorage.setItem("current_session_id", sessionId);

    function authHeaders(extra = {}) {
        return {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
            ...extra
        };
    }

    // Initializations
    initApp();

    function initApp() {
        initTheme();
        bindEvents();
        checkHealth();
        loadSessions();
        loadActiveSessionMessages();
    }

    function initTheme() {
        const savedTheme = localStorage.getItem("studymate_theme") || "light";
        applyTheme(savedTheme);
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("studymate_theme", theme);
        if (themeToggleBtn) {
            const nextMode = theme === "light" ? "Dark" : "Light";
            themeToggleBtn.setAttribute("aria-label", `Switch to ${nextMode} Mode`);
            themeToggleBtn.setAttribute("title", `Switch to ${nextMode} Mode`);
        }
    }

    function toggleTheme() {
        const currentTheme = document.documentElement.getAttribute("data-theme") || "light";
        const newTheme = currentTheme === "light" ? "dark" : "light";
        applyTheme(newTheme);
    }

    function bindEvents() {
        if (themeToggleBtn) {
            themeToggleBtn.addEventListener("click", toggleTheme);
        }
        chatForm.addEventListener("submit", handleSubmit);
        userInput.addEventListener("keydown", handleKeydown);
        userInput.addEventListener("input", handleInputResize);
        dismissErrorBtn.addEventListener("click", hideError);
        retryBtn.addEventListener("click", handleRetry);
        newChatBtn.addEventListener("click", startNewChat);
        sidebarNewChatBtn.addEventListener("click", startNewChat);
        toggleSidebarBtn.addEventListener("click", toggleSidebar);

        if (sidebarCloseBtn) {
            sidebarCloseBtn.addEventListener("click", closeMobileSidebar);
        }
        if (sidebarBackdrop) {
            sidebarBackdrop.addEventListener("click", closeMobileSidebar);
        }

        if (sessionSearchInput) {
            sessionSearchInput.addEventListener("input", handleSessionSearch);
        }

        // Delegate Starter Cards / Prompt Chips
        document.addEventListener("click", (e) => {
            const card = e.target.closest(".starter-card");
            if (card && !isSubmitting) {
                const promptText = card.getAttribute("data-prompt");
                if (promptText) {
                    userInput.value = promptText;
                    handleInputResize();
                    chatForm.requestSubmit();
                }
            }
        });
    }

    function generateUUID() {
        if (crypto && crypto.randomUUID) {
            return crypto.randomUUID();
        }
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    function toggleSidebar() {
        if (window.innerWidth <= 768) {
            chatSidebar.classList.toggle("mobile-open");
            sidebarBackdrop.classList.toggle("active");
        } else {
            chatSidebar.classList.toggle("collapsed");
        }
    }

    function closeMobileSidebar() {
        chatSidebar.classList.remove("mobile-open");
        if (sidebarBackdrop) {
            sidebarBackdrop.classList.remove("active");
        }
    }

    function handleInputResize() {
        // Auto-resize textarea height smoothly
        userInput.style.height = "auto";
        userInput.style.height = `${Math.min(userInput.scrollHeight, 180)}px`;

        // Update character counter
        const currentLength = userInput.value.length;
        if (charCounter) {
            charCounter.textContent = `${currentLength} / 4000`;
            if (currentLength > 3800) {
                charCounter.style.color = "var(--status-warning)";
            } else {
                charCounter.style.color = "var(--text-muted)";
            }
        }
    }

    function checkHealth() {
        fetch("/api/health")
            .then(res => res.json())
            .then(data => {
                if (data.status === "online" && data.database === "healthy") {
                    healthBadge.textContent = "Ready to help";
                    healthBadge.className = "status-indicator online";
                } else {
                    healthBadge.textContent = "Temporarily unavailable";
                    healthBadge.className = "status-indicator warning";
                }
            })
            .catch(() => {
                healthBadge.textContent = "Temporarily unavailable";
                healthBadge.className = "status-indicator error";
            });
    }

    async function loadSessions() {
        try {
            const res = await fetch("/api/sessions", { headers: authHeaders() });
            if (res.status === 401) {
                window.location.href = "/auth/login";
                return;
            }
            const data = await res.json();
            if (data.success && Array.isArray(data.sessions)) {
                allSessions = data.sessions;
                renderSessionsList(allSessions);
            }
        } catch (err) {
            console.error("Failed to load chat sessions:", err);
        }
    }

    function handleSessionSearch(e) {
        const query = e.target.value.toLowerCase().trim();
        if (!query) {
            renderSessionsList(allSessions);
            return;
        }

        const filtered = allSessions.filter(s => 
            (s.title || "").toLowerCase().includes(query)
        );
        renderSessionsList(filtered);
    }

    function renderSessionsList(sessions) {
        sessionsList.innerHTML = "";
        if (sessionsCounter) {
            sessionsCounter.textContent = sessions.length;
        }

        if (!sessions || sessions.length === 0) {
            noSessionsMsg.style.display = "block";
            return;
        }

        noSessionsMsg.style.display = "none";
        sessions.forEach(session => {
            const li = document.createElement("li");
            li.className = `session-item ${session.id === sessionId ? "active" : ""}`;
            li.dataset.sessionId = session.id;

            const titleSpan = document.createElement("span");
            titleSpan.className = "session-info";
            titleSpan.textContent = session.title || "Study Session";
            titleSpan.title = session.title || "Study Session";

            const deleteBtn = document.createElement("button");
            deleteBtn.className = "session-delete-btn";
            deleteBtn.innerHTML = "&times;";
            deleteBtn.title = "Delete conversation";
            deleteBtn.setAttribute("aria-label", "Delete conversation");

            deleteBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                handleDeleteSession(session.id);
            });

            li.appendChild(titleSpan);
            li.appendChild(deleteBtn);

            li.addEventListener("click", () => {
                if (session.id !== sessionId && !isSubmitting) {
                    switchSession(session.id, session.title);
                }
            });

            sessionsList.appendChild(li);
        });
    }

    async function loadActiveSessionMessages() {
        if (!sessionId) return;

        try {
            const res = await fetch(`/api/sessions/${sessionId}/messages`, { headers: authHeaders() });
            if (res.status === 401) {
                window.location.href = "/auth/login";
                return;
            }
            const data = await res.json();

            if (data.success && Array.isArray(data.messages) && data.messages.length > 0) {
                renderMessagesStream(data.messages);
            } else {
                renderWelcomeScreen();
            }
        } catch (err) {
            console.error("Failed to load active session messages:", err);
            renderWelcomeScreen();
        }
    }

    function switchSession(newSessionId, title) {
        sessionId = newSessionId;
        localStorage.setItem("current_session_id", sessionId);
        activeSessionTitle.textContent = title || "Study Session";
        hideError();
        loadSessions();
        loadActiveSessionMessages();
        closeMobileSidebar();
    }

    function startNewChat() {
        sessionId = generateUUID();
        localStorage.setItem("current_session_id", sessionId);
        activeSessionTitle.textContent = "New Study Session";
        hideError();
        lastFailedMessage = null;
        renderWelcomeScreen();
        loadSessions();
        userInput.value = "";
        handleInputResize();
        userInput.focus();
        closeMobileSidebar();
    }

    async function handleDeleteSession(idToDelete) {
        if (!confirm("Are you sure you want to delete this study session?")) {
            return;
        }

        try {
            const res = await fetch(`/api/sessions/${idToDelete}`, {
                method: "DELETE",
                headers: authHeaders()
            });
            if (res.status === 401) {
                window.location.href = "/auth/login";
                return;
            }
            const data = await res.json();
            if (data.success) {
                if (idToDelete === sessionId) {
                    startNewChat();
                } else {
                    loadSessions();
                }
            } else {
                showError("Unable to delete conversation. Please try again.");
            }
        } catch (err) {
            showError("Unable to delete conversation. Please try again.");
        }
    }

    function handleKeydown(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (!isSubmitting) {
                chatForm.requestSubmit();
            }
        }
    }

    async function handleSubmit(e) {
        e.preventDefault();
        const text = userInput.value.trim();

        if (!text || isSubmitting) {
            return;
        }

        if (text.length > 4000) {
            showError("Your message exceeds 4000 characters. Please shorten it.");
            return;
        }

        // Remove welcome screen if present
        const welcome = document.getElementById("welcome-container");
        if (welcome) {
            welcome.remove();
        }

        hideError();
        setIsSubmitting(true);
        lastFailedMessage = null;

        // Deduplication guard against repeated visual rendering:
        // If the last message currently rendered in the chat stream is already this user message
        // (e.g. from an immediate retry or resubmission of a failed turn), do not append it a second time.
        const lastMsgEl = chatMessages.lastElementChild;
        const alreadyRendered = lastMsgEl && 
            lastMsgEl.classList.contains("user-message") && 
            lastMsgEl.querySelector(".message-content")?.textContent.trim() === text;

        if (!alreadyRendered) {
            appendMessage({
                role: "user",
                content: text,
                sender: "You",
                time: formatTime(new Date())
            });
        }

        userInput.value = "";
        handleInputResize();
        showLoading(true);

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: authHeaders(),
                body: JSON.stringify({
                    message: text,
                    session_id: sessionId
                })
            });

            if (response.status === 401) {
                window.location.href = "/auth/login";
                return;
            }

            const data = await response.json();

            if (!response.ok || !data.success) {
                lastFailedMessage = text;
                let errMsg = "Response couldn't be generated. Please try again.";
                if (response.status === 429 || data.is_rate_limit) {
                    errMsg = "You're temporarily unable to send a message. Please try again shortly.";
                } else if (data.error && typeof data.error === "string" && !data.error.toLowerCase().includes("groq") && !data.error.toLowerCase().includes("http") && !data.error.toLowerCase().includes("status")) {
                    errMsg = data.error;
                }
                showError(errMsg, true);
            } else {
                lastFailedMessage = null;
                if (data.session_id) {
                    sessionId = data.session_id;
                    localStorage.setItem("current_session_id", sessionId);
                }

                if (data.session_title) {
                    activeSessionTitle.textContent = data.session_title;
                }

                appendMessage({
                    role: "assistant",
                    content: data.response,
                    sender: "StudyMate AI",
                    time: formatTime(new Date())
                });

                loadSessions();
            }
        } catch (err) {
            lastFailedMessage = text;
            showError("Response couldn't be generated. Please try again.", true);
        } finally {
            showLoading(false);
            setIsSubmitting(false);
            userInput.focus();
        }
    }

    function handleRetry() {
        if (lastFailedMessage && !isSubmitting) {
            userInput.value = lastFailedMessage;
            handleInputResize();
            hideError();
            chatForm.requestSubmit();
        }
    }

    function renderWelcomeScreen() {
        chatMessages.innerHTML = `
            <div id="welcome-container" class="welcome-container">
                <div class="welcome-card">
                    <div class="welcome-icon-badge">
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                        </svg>
                    </div>
                    <h2 class="welcome-heading">Your personal AI study companion.</h2>
                    <p class="welcome-desc">
                        Ask questions, understand concepts, and learn with confidence.
                    </p>
                    
                    <div class="starter-cards-grid">
                        <button type="button" class="starter-card prompt-chip" data-prompt="Can you explain the intuition behind Eigenvalues and Eigenvectors in linear algebra, using an intuitive geometric analogy?">
                            <div class="card-icon-box">💡</div>
                            <div class="card-text-group">
                                <h3 class="card-title">Explain a difficult concept</h3>
                                <p class="card-prompt-preview">Break down complex theories and theorems with simple intuition.</p>
                            </div>
                        </button>

                        <button type="button" class="starter-card prompt-chip" data-prompt="Help me understand the difference between stack and heap memory in C++ with memory layouts and a short code example.">
                            <div class="card-icon-box">💻</div>
                            <div class="card-text-group">
                                <h3 class="card-title">Help me understand programming</h3>
                                <p class="card-prompt-preview">Clarify syntax, debug errors, and explore data structures.</p>
                            </div>
                        </button>

                        <button type="button" class="starter-card prompt-chip" data-prompt="Can you create a structured, high-yield revision checklist and practice flashcard questions for an upcoming Computer Networks exam?">
                            <div class="card-icon-box">🎯</div>
                            <div class="card-text-group">
                                <h3 class="card-title">Prepare me for an exam</h3>
                                <p class="card-prompt-preview">Generate revision outlines, flashcard questions, and test reviews.</p>
                            </div>
                        </button>

                        <button type="button" class="starter-card prompt-chip" data-prompt="Help me structure an academic research paper on Artificial Intelligence ethics, focusing on literature review and methodology sections.">
                            <div class="card-icon-box">📝</div>
                            <div class="card-text-group">
                                <h3 class="card-title">Help me structure an assignment</h3>
                                <p class="card-prompt-preview">Organize outlines, literature reviews, and problem-solving steps.</p>
                            </div>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    function renderMessagesStream(messages) {
        chatMessages.innerHTML = "";
        messages.forEach(msg => {
            appendMessage({
                role: msg.role,
                content: msg.content,
                sender: msg.role === "user" ? "You" : "StudyMate AI",
                time: formatTime(new Date(msg.created_at || Date.now()))
            });
        });
        scrollChatToBottom();
    }

    function renderMarkdownSafely(text) {
        if (window.marked && window.DOMPurify) {
            marked.setOptions({
                breaks: true,
                gfm: true
            });
            const rawHtml = marked.parse(text);
            return DOMPurify.sanitize(rawHtml);
        }
        // Safe fallback
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML.replace(/\n/g, "<br>");
    }

    function appendMessage({ role, content, sender, time }) {
        const msgDiv = document.createElement("div");
        msgDiv.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;

        const metaDiv = document.createElement("div");
        metaDiv.className = "message-meta";

        const senderGroup = document.createElement("div");
        senderGroup.className = "sender-group";

        const senderSpan = document.createElement("span");
        senderSpan.className = "sender-name";
        senderSpan.textContent = sender;
        senderGroup.appendChild(senderSpan);

        if (role === "assistant") {
            const assistantPill = document.createElement("span");
            assistantPill.className = "assistant-pill";
            assistantPill.textContent = "AI";
            senderGroup.appendChild(assistantPill);
        }

        const rightMeta = document.createElement("div");
        rightMeta.className = "meta-actions";

        if (role === "assistant") {
            const copyBtn = document.createElement("button");
            copyBtn.type = "button";
            copyBtn.className = "copy-btn";
            copyBtn.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                </svg>
                <span>Copy</span>
            `;
            copyBtn.title = "Copy response to clipboard";
            copyBtn.addEventListener("click", () => copyToClipboard(content, copyBtn));
            rightMeta.appendChild(copyBtn);
        }

        const timeSpan = document.createElement("span");
        timeSpan.className = "message-time";
        timeSpan.textContent = time;
        rightMeta.appendChild(timeSpan);

        metaDiv.appendChild(senderGroup);
        metaDiv.appendChild(rightMeta);

        const contentDiv = document.createElement("div");
        contentDiv.className = "message-content";

        if (role === "assistant") {
            contentDiv.innerHTML = renderMarkdownSafely(content);
            enhanceCodeBlocks(contentDiv);
        } else {
            contentDiv.textContent = content;
        }

        msgDiv.appendChild(metaDiv);
        msgDiv.appendChild(contentDiv);

        chatMessages.appendChild(msgDiv);
        scrollChatToBottom();
    }

    function enhanceCodeBlocks(container) {
        const pres = container.querySelectorAll("pre");
        pres.forEach(pre => {
            const code = pre.querySelector("code");
            const rawCode = code ? code.innerText : pre.innerText;

            // Extract language if specified in class e.g. language-python
            let lang = "CODE";
            if (code && code.className) {
                const match = code.className.match(/language-([a-zA-Z0-9_-]+)/);
                if (match) {
                    lang = match[1].toUpperCase();
                }
            }

            const wrapper = document.createElement("div");
            wrapper.className = "code-block-wrapper";

            const header = document.createElement("div");
            header.className = "code-block-header";

            const langLabel = document.createElement("span");
            langLabel.className = "code-lang-label";
            langLabel.textContent = lang;

            const copyBtn = document.createElement("button");
            copyBtn.type = "button";
            copyBtn.className = "code-copy-btn";
            copyBtn.textContent = "Copy";
            copyBtn.addEventListener("click", () => copyToClipboard(rawCode, copyBtn));

            header.appendChild(langLabel);
            header.appendChild(copyBtn);

            pre.parentNode.insertBefore(wrapper, pre);
            wrapper.appendChild(header);
            wrapper.appendChild(pre);
        });
    }

    function copyToClipboard(text, btnElement) {
        const onSuccess = () => {
            const originalHtml = btnElement.innerHTML;
            btnElement.textContent = "Copied!";
            setTimeout(() => {
                btnElement.innerHTML = originalHtml;
            }, 1800);
        };

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(onSuccess).catch(() => {
                fallbackCopyText(text, onSuccess);
            });
        } else {
            fallbackCopyText(text, onSuccess);
        }
    }

    function fallbackCopyText(text, callback) {
        const tempTextarea = document.createElement("textarea");
        tempTextarea.value = text;
        tempTextarea.style.position = "fixed";
        tempTextarea.style.opacity = "0";
        document.body.appendChild(tempTextarea);
        tempTextarea.select();
        try {
            document.execCommand("copy");
            if (callback) callback();
        } catch (e) {
            console.error("Fallback copy failed:", e);
        }
        document.body.removeChild(tempTextarea);
    }

    function setIsSubmitting(submitting) {
        isSubmitting = submitting;
        sendButton.disabled = submitting;
        userInput.disabled = submitting;
    }

    function showLoading(show) {
        loadingIndicator.style.display = show ? "flex" : "none";
        if (show) {
            scrollChatToBottom();
        }
    }

    function showError(message, allowRetry = false) {
        errorMessageText.textContent = message;
        retryBtn.style.display = allowRetry ? "inline-block" : "none";
        errorBanner.style.display = "flex";
    }

    function hideError() {
        errorBanner.style.display = "none";
        errorMessageText.textContent = "";
        retryBtn.style.display = "none";
    }

    function scrollChatToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function formatTime(date) {
        if (isNaN(date.getTime())) {
            return "Just now";
        }
        return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
});
