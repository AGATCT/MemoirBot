/**
 * PersonalAgent — 记忆浏览器交互逻辑
 */

document.addEventListener('DOMContentLoaded', () => {
    let currentType = '';
    let searchQuery = '';

    const memoryList = document.getElementById('memory-list');
    const memorySearch = document.getElementById('memory-search');
    const memoryStats = document.getElementById('memory-stats');
    const tabs = document.querySelectorAll('.memory-tab');

    // --- 初始化 ---
    loadMemories();
    loadStats();

    // --- 事件监听 ---
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentType = tab.dataset.type;
            loadMemories();
        });
    });

    let searchTimer = null;
    memorySearch.addEventListener('input', () => {
        searchQuery = memorySearch.value.trim();
        clearTimeout(searchTimer);
        searchTimer = setTimeout(loadMemories, 300);
    });

    async function loadMemories() {
        memoryList.innerHTML = '<p class="text-muted">加载中...</p>';

        try {
            let url;
            if (searchQuery) {
                url = `/api/memory/search?q=${encodeURIComponent(searchQuery)}&limit=100`;
                if (currentType) url += `&type=${encodeURIComponent(currentType)}`;
            } else {
                url = '/api/memory/all?limit=100';
                if (currentType) url += `&type=${encodeURIComponent(currentType)}`;
            }

            const resp = await fetch(url);
            const data = await resp.json();

            const memories = data.memories || [];
            if (memories.length === 0) {
                memoryList.innerHTML = '<div class="chat-placeholder" style="height:200px;"><p class="text-muted">暂无记忆</p><p class="text-muted text-sm">与 AI 对话或写日记后，系统会自动提取记忆</p></div>';
                return;
            }

            memoryList.innerHTML = memories.map(m => `
                <div class="memory-card">
                    <div class="memory-card-header">
                        <span class="memory-card-type type-${m.type}">${typeLabel(m.type)}</span>
                        <button class="btn btn-outline btn-sm" onclick="deleteMemory('${m.name}')" title="删除">删除</button>
                    </div>
                    <div class="memory-card-content">${escapeHtml(m.content)}</div>
                    <div class="memory-card-footer">
                        <span>${m.source || '未知来源'} · ${formatTime(m.updated_at)}</span>
                    </div>
                </div>
            `).join('');
        } catch (e) {
            console.error('加载记忆失败:', e);
            memoryList.innerHTML = '<p class="text-muted">加载失败</p>';
        }
    }

    async function loadStats() {
        try {
            const resp = await fetch('/api/memory/stats/counts');
            const data = await resp.json();
            memoryStats.textContent = `共 ${data.total} 条记忆`;
        } catch (e) {
            // ignore
        }
    }

    // --- 全局函数（供 HTML onclick 使用） ---
    window.deleteMemory = async function(name) {
        if (!confirm(`确定要删除记忆 "${name}" 吗？`)) return;
        try {
            await fetch(`/api/memory/${name}`, { method: 'DELETE' });
            loadMemories();
            loadStats();
        } catch (e) {
            console.error('删除失败:', e);
        }
    };

    // --- 辅助 ---
    function typeLabel(type) {
        const map = { user: '用户', feedback: '反馈', reference: '参考', event: '事件', state: '状态' };
        return map[type] || type;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatTime(isoStr) {
        if (!isoStr) return '';
        try { return new Date(isoStr).toLocaleString('zh-CN'); } catch(e) { return ''; }
    }
});
