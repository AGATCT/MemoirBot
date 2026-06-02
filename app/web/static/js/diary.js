/**
 * PersonalAgent — 日记界面交互逻辑
 */

document.addEventListener('DOMContentLoaded', () => {
    // --- 状态 ---
    let currentDate = getToday();        // YYYY-MM-DD
    let viewYear, viewMonth;             // 当前日历显示的年月
    let savedContent = '';
    let autoSaveTimer = null;

    // --- DOM 元素 ---
    const calendarGrid = document.getElementById('calendar-grid');
    const currentMonthLabel = document.getElementById('current-month-label');
    const noEntryHint = document.getElementById('no-entry-hint');
    const entryEditor = document.getElementById('entry-editor');
    const entryDateLabel = document.getElementById('entry-date-label');
    const diaryTextarea = document.getElementById('diary-textarea');
    const entryMood = document.getElementById('entry-mood');
    const entryTags = document.getElementById('entry-tags');
    const saveStatus = document.getElementById('save-status');
    const entryListMini = document.getElementById('entry-list-mini');

    // --- 初始化 ---
    const today = getToday();
    const [ty, tm] = today.split('-');
    viewYear = parseInt(ty);
    viewMonth = parseInt(tm);
    renderCalendar();
    loadRecentEntries();

    // --- 事件监听 ---
    document.getElementById('btn-prev-month').addEventListener('click', () => {
        viewMonth--;
        if (viewMonth < 1) { viewMonth = 12; viewYear--; }
        renderCalendar();
    });

    document.getElementById('btn-next-month').addEventListener('click', () => {
        viewMonth++;
        if (viewMonth > 12) { viewMonth = 1; viewYear++; }
        renderCalendar();
    });

    document.getElementById('btn-today').addEventListener('click', () => {
        currentDate = getToday();
        [viewYear, viewMonth] = [new Date().getFullYear(), new Date().getMonth() + 1];
        renderCalendar();
        loadEntry(currentDate);
    });

    document.getElementById('btn-delete-entry').addEventListener('click', deleteEntry);

    diaryTextarea.addEventListener('input', () => {
        scheduleAutoSave();
    });

    entryMood.addEventListener('change', () => {
        scheduleAutoSave();
    });

    entryTags.addEventListener('input', () => {
        scheduleAutoSave();
    });

    // --- 日历渲染 ---

    async function renderCalendar() {
        currentMonthLabel.textContent = `${viewYear}年 ${viewMonth}月`;
        updateNavButtons();

        // 加载当月有日记的日期
        let markedDays = {};
        try {
            const resp = await fetch(`/api/diary/month/${viewYear}/${viewMonth}`);
            const data = await resp.json();
            markedDays = data.entries || {};
        } catch (e) {
            console.error('加载日历失败:', e);
        }

        // 生成日历网格
        const firstDay = new Date(viewYear, viewMonth - 1, 1).getDay(); // 0=周日
        const daysInMonth = new Date(viewYear, viewMonth, 0).getDate();
        const todayStr = getToday();

        let html = '<div style="display:grid; grid-template-columns:repeat(7,1fr); gap:2px; text-align:center;">';
        // 星期头
        ['日','一','二','三','四','五','六'].forEach(d => {
            html += `<div style="font-size:11px; color:var(--text-tertiary); padding:4px 0;">${d}</div>`;
        });

        // 空白填充
        for (let i = 0; i < firstDay; i++) {
            html += '<div></div>';
        }

        // 日期格子
        for (let day = 1; day <= daysInMonth; day++) {
            const dateStr = `${viewYear}-${String(viewMonth).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
            const isToday = dateStr === todayStr;
            const isSelected = dateStr === currentDate;
            const hasEntry = !!markedDays[String(day)];

            let style = 'padding:6px 2px; cursor:pointer; border-radius:4px; font-size:13px;';
            if (isToday) style += 'font-weight:bold;';
            if (isSelected) style += 'background:var(--accent); color:#fff;';

            html += `<div style="${style}" data-date="${dateStr}" class="cal-day">
                ${day}
                <div style="width:5px;height:5px;border-radius:50%;margin:2px auto 0;${hasEntry ? 'background:' + (isSelected ? '#fff' : 'var(--accent)') : ''}"></div>
            </div>`;
        }

        html += '</div>';
        calendarGrid.innerHTML = html;

        // 点击日期
        calendarGrid.querySelectorAll('.cal-day').forEach(el => {
            el.addEventListener('click', () => {
                currentDate = el.dataset.date;
                loadEntry(currentDate);
                renderCalendar();
            });
        });
    }

    function updateNavButtons() {
        const now = new Date();
        const btnNext = document.getElementById('btn-next-month');
        // 不能超过当月
        if (viewYear === now.getFullYear() && viewMonth >= now.getMonth() + 1) {
            btnNext.disabled = true;
        } else {
            btnNext.disabled = false;
        }
    }

    // --- 日记加载/保存 ---

    async function loadEntry(dateStr) {
        try {
            const resp = await fetch(`/api/diary/entries/${dateStr}`);
            if (!resp.ok) {
                // 新日记
                entryDateLabel.textContent = formatDateCN(dateStr);
                diaryTextarea.value = '';
                entryMood.value = '';
                entryTags.value = '';
                savedContent = '';
                showEditor();
                diaryTextarea.focus();
                return;
            }
            const entry = await resp.json();
            entryDateLabel.textContent = formatDateCN(entry.date);
            diaryTextarea.value = entry.content || '';
            entryMood.value = entry.mood || '';
            entryTags.value = (entry.tags || []).join(', ');
            savedContent = entry.content || '';
            showEditor();
        } catch (e) {
            console.error('加载日记失败:', e);
        }
    }

    async function saveEntry() {
        const content = diaryTextarea.value;
        if (content === savedContent) return;  // 没变化

        const tags = entryTags.value
            .split(',')
            .map(t => t.trim())
            .filter(t => t.length > 0);

        try {
            saveStatus.textContent = '保存中...';
            const resp = await fetch('/api/diary/entries', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    date: currentDate,
                    content: content,
                    mood: entryMood.value || null,
                    tags: tags,
                }),
            });
            if (resp.ok) {
                savedContent = content;
                saveStatus.textContent = '✓ 已保存';
            } else {
                saveStatus.textContent = '保存失败';
            }
        } catch (e) {
            saveStatus.textContent = '保存失败';
        }
        renderCalendar();  // 刷新日历标记
        loadRecentEntries();  // 刷新最近列表
    }

    function scheduleAutoSave() {
        saveStatus.textContent = '未保存';
        if (autoSaveTimer) clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(saveEntry, 1500);
    }

    async function deleteEntry() {
        if (!confirm('确定要删除这篇日记吗？此操作不可撤销。')) return;

        try {
            await fetch(`/api/diary/entries/${currentDate}`, { method: 'DELETE' });
            diaryTextarea.value = '';
            entryMood.value = '';
            entryTags.value = '';
            savedContent = '';
            noEntryHint.style.display = '';
            entryEditor.style.display = 'none';
            renderCalendar();
            loadRecentEntries();
        } catch (e) {
            console.error('删除日记失败:', e);
        }
    }

    function showEditor() {
        noEntryHint.style.display = 'none';
        entryEditor.style.display = 'flex';
    }

    // --- 最近条目 ---

    async function loadRecentEntries() {
        try {
            const resp = await fetch('/api/diary/entries?limit=20');
            const entries = await resp.json();
            if (entries.length === 0) {
                entryListMini.innerHTML = '<p class="text-muted text-sm" style="text-align:center;">暂无日记</p>';
                return;
            }
            entryListMini.innerHTML = entries.slice(0, 15).map(e => `
                <div style="padding:6px 0; cursor:pointer; border-bottom:1px solid var(--border); font-size:12px;"
                     data-date="${e.date}">
                    <span style="font-weight:500;">${formatDateCN(e.date)}</span>
                    ${e.mood ? `<span style="opacity:0.5;font-size:10px;">${e.mood}</span>` : ''}
                    <span style="color:var(--text-tertiary); display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${e.preview || '(空)'}</span>
                </div>
            `).join('');

            entryListMini.querySelectorAll('[data-date]').forEach(el => {
                el.addEventListener('click', () => {
                    currentDate = el.dataset.date;
                    const [y, m] = currentDate.split('-');
                    viewYear = parseInt(y);
                    viewMonth = parseInt(m);
                    renderCalendar();
                    loadEntry(currentDate);
                });
            });
        } catch (e) {
            console.error('加载日记列表失败:', e);
        }
    }

    // --- 辅助 ---

    function getToday() {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    }

    function formatDateCN(dateStr) {
        const [y, m, d] = dateStr.split('-');
        return `${y}年${parseInt(m)}月${parseInt(d)}日`;
    }

    function moodEmoji(mood) {
        const map = { happy:'Happy', sad:'Sad', productive:'Productive', tired:'Tired', excited:'Excited', neutral:'Neutral' };
        return map[mood] || '';
    }
});
