/**
 * PersonalAgent — 聊天界面交互逻辑
 */

document.addEventListener('DOMContentLoaded', () => {
    // --- 状态 ---
    let currentSessionId = null;
    let isStreaming = false;

    // --- DOM 元素 ---
    const btnNewSession = document.getElementById('btn-new-session');
    const sessionList = document.getElementById('session-list');
    const noSessionHint = document.getElementById('no-session-hint');
    const chatArea = document.getElementById('chat-area');
    const messageList = document.getElementById('message-list');
    const chatInput = document.getElementById('chat-input');
    const btnSend = document.getElementById('btn-send');

    // --- 初始化 ---
    loadSessions();

    // --- 事件监听 ---
    btnNewSession.addEventListener('click', createSession);

    chatInput.addEventListener('input', () => {
        btnSend.disabled = !chatInput.value.trim() || isStreaming;
    });

    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    btnSend.addEventListener('click', sendMessage);

    // 顶部标题栏双击重命名
    document.getElementById('chat-title-bar')?.addEventListener('dblclick', () => {
        if (currentSessionId) startRename(currentSessionId);
    });

    // --- 会话管理 ---

    async function loadSessions() {
        try {
            const resp = await fetch('/api/chat/sessions');
            const sessions = await resp.json();
            renderSessionList(sessions);
        } catch (err) {
            console.error('加载会话列表失败:', err);
            sessionList.innerHTML = '<p class="text-muted text-sm">加载失败</p>';
        }
    }

    function renderSessionList(sessions) {
        if (sessions.length === 0) {
            sessionList.innerHTML = '<p class="text-muted text-sm">暂无对话，点击上方按钮开始</p>';
            return;
        }
        sessionList.innerHTML = sessions.map(s => `
            <div class="session-item ${s.session_id === currentSessionId ? 'active' : ''}"
                 data-session-id="${s.session_id}">
                <div class="session-item-main" data-action="select">
                    <div class="session-item-title">${escapeHtml(s.title)}</div>
                    <div class="session-item-meta">${s.message_count} 条 · ${formatTime(s.updated_at)}</div>
                </div>
                <div class="session-item-actions">
                    <button class="btn-icon" data-action="rename" title="重命名" data-sid="${s.session_id}">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                    </button>
                    <button class="btn-icon" data-action="delete" title="删除" data-sid="${s.session_id}">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    </button>
                </div>
            </div>
        `).join('');

        // 事件委托
        sessionList.querySelectorAll('.session-item').forEach(el => {
            el.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                const sid = e.target.closest('[data-sid]')?.dataset.sid || el.dataset.sessionId;

                if (action === 'rename') {
                    e.stopPropagation();
                    startRename(sid);
                } else if (action === 'delete') {
                    e.stopPropagation();
                    deleteSession(sid);
                } else {
                    selectSession(sid);
                }
            });
        });
    }

    async function createSession() {
        try {
            const resp = await fetch('/api/chat/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            const data = await resp.json();
            selectSession(data.session_id);
            await loadSessions();
        } catch (err) {
            console.error('创建会话失败:', err);
        }
    }

    async function selectSession(sessionId) {
        currentSessionId = sessionId;
        chatInput.disabled = false;

        try {
            const resp = await fetch(`/api/chat/sessions/${sessionId}`);
            const data = await resp.json();

            noSessionHint.style.display = 'none';
            chatArea.style.display = '';
            messageList.innerHTML = '';
            data.messages.forEach(msg => appendMessage(msg.role, msg.content, msg.timestamp));

            // 更新顶部标题
            const titleBar = document.getElementById('chat-title-bar');
            if (titleBar) {
                titleBar.textContent = data.metadata.title || '对话';
                titleBar.title = '双击重命名';
            }

            await loadSessions();
            scrollToBottom();
            chatInput.focus();
        } catch (err) {
            console.error('加载会话失败:', err);
        }
    }

    // --- 重命名 ---

    function startRename(sessionId) {
        // 找到对应的会话项
        const item = document.querySelector(`.session-item[data-session-id="${sessionId}"]`);
        if (!item) return;

        const titleEl = item.querySelector('.session-item-title');
        if (!titleEl) return;

        const oldTitle = titleEl.textContent.trim();

        // 替换为输入框
        const input = document.createElement('input');
        input.type = 'text';
        input.value = oldTitle;
        input.className = 'rename-input';
        input.style.cssText = 'width:100%; padding:2px 4px; border:1px solid var(--color-primary); border-radius:4px; font-size:14px;';

        titleEl.replaceWith(input);
        input.focus();
        input.select();

        const finish = async () => {
            const newTitle = input.value.trim() || oldTitle;
            try {
                await fetch(`/api/chat/sessions/${sessionId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: newTitle }),
                });
            } catch (e) {
                console.error('重命名失败:', e);
            }
            loadSessions();
        };

        input.addEventListener('blur', finish);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
            if (e.key === 'Escape') { input.value = oldTitle; input.blur(); }
        });
    }

    // --- 删除 ---

    async function deleteSession(sessionId) {
        if (!confirm('确定删除这个对话？所有消息将被永久删除。')) return;

        try {
            await fetch(`/api/chat/sessions/${sessionId}`, { method: 'DELETE' });
            if (currentSessionId === sessionId) {
                // 回到空状态
                currentSessionId = null;
                chatArea.style.display = 'none';
                noSessionHint.style.display = '';
                messageList.innerHTML = '';
                chatInput.disabled = true;
            }
            await loadSessions();
        } catch (err) {
            console.error('删除会话失败:', err);
        }
    }

    // --- 发送消息 (SSE 流式) ---

    async function sendMessage() {
        if (!currentSessionId || isStreaming) return;
        const content = chatInput.value.trim();
        if (!content) return;

        isStreaming = true;
        chatInput.value = '';
        chatInput.disabled = true;
        btnSend.disabled = true;

        appendMessage('user', content, new Date().toISOString());
        const aiMsgEl = appendMessage('assistant', '', '');
        const aiBubble = aiMsgEl.querySelector('.message-bubble');

        try {
            const resp = await fetch(`/api/chat/sessions/${currentSessionId}/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content }),
            });

            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let fullText = '';
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                while (buffer.includes('\n\n')) {
                    const idx = buffer.indexOf('\n\n');
                    const eventBlock = buffer.slice(0, idx);
                    buffer = buffer.slice(idx + 2);

                    let eventType = '', eventData = '';
                    for (const line of eventBlock.split('\n')) {
                        if (line.startsWith('event: ')) eventType = line.slice(7).trim();
                        else if (line.startsWith('data: ')) eventData = line.slice(6);
                    }

                    if (eventType === 'token' && eventData) {
                        try {
                            const data = JSON.parse(eventData);
                            fullText += data.content || '';
                            aiBubble.innerHTML = simpleMarkdown(fullText);
                            scrollToBottom();
                        } catch (e) {}
                    }
                }
            }

            aiBubble.innerHTML = simpleMarkdown(fullText || '...');
            scrollToBottom();
            await loadSessions();
        } catch (err) {
            console.error('发送消息失败:', err);
            aiBubble.innerHTML = `<span style="color:var(--color-error)">发送失败: ${escapeHtml(err.message)}</span>`;
        } finally {
            isStreaming = false;
            chatInput.disabled = false;
            btnSend.disabled = true;
            chatInput.focus();
        }
    }

    // --- 辅助函数 ---

    function appendMessage(role, content, timestamp) {
        const el = document.createElement('div');
        el.className = `message ${role}`;
        el.innerHTML = `
            <div class="message-bubble">${role === 'assistant' ? simpleMarkdown(content) : escapeHtml(content)}</div>
            <div class="message-time">${timestamp ? formatTime(timestamp) : ''}</div>
        `;
        messageList.appendChild(el);
        scrollToBottom();
        return el;
    }

    function scrollToBottom() {
        messageList.scrollTop = messageList.scrollHeight;
    }

    function formatTime(isoStr) {
        if (!isoStr) return '';
        try {
            const d = new Date(isoStr);
            return d.toLocaleString('zh-CN', {
                month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
            });
        } catch (e) { return ''; }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function simpleMarkdown(text) {
        if (!text) return '';
        let html = escapeHtml(text);
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        html = html.replace(/\n/g, '<br>');
        return html;
    }
});
