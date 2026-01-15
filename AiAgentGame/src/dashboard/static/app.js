// Agent definitions with workflow order
const AGENTS = [
    { id: 'planner', name: 'Planner', label: '企画', order: 1 },
    { id: 'coder', name: 'Coder', label: 'コード', order: 2 },
    { id: 'asset_coordinator', name: 'Asset Coordinator', label: 'アセット', order: 3 },
    { id: 'tester', name: 'Tester', label: 'テスト', order: 4 },
    { id: 'debugger', name: 'Debugger', label: 'デバッグ', order: 5 },
    { id: 'reviewer', name: 'Reviewer', label: 'レビュー', order: 6 }
];

const STATUS_LABELS = {
    pending: '待機中',
    running: '実行中',
    completed: '完了',
    error: 'エラー'
};

let ws;
let eventCount = 0;
let reconnectInterval;
let selectedAgent = null;
let agentStates = {};
let agentEvents = {};
let startTime = null;
let elapsedInterval = null;

// Initialize agent states with detailed info
AGENTS.forEach(a => {
    agentStates[a.id] = {
        status: 'pending',
        message: '',
        progress: 0,
        details: {},  // Store extra details (counts, lists, etc.)
        result: ''    // Final result summary
    };
    agentEvents[a.id] = [];
});

// Format progress info for each agent type
function getAgentProgressInfo(agentId, state) {
    const d = state.details || {};
    switch(agentId) {
        case 'planner':
            if (d.task_count) return `タスク: ${d.task_count}件生成`;
            return '';
        case 'coder':
            if (d.files) return `ファイル: ${d.files}件 (${d.total_lines || 0}行)`;
            return '';
        case 'asset_coordinator':
            if (d.assets) return `アセット: ${d.assets}件 (画像${d.image_count || 0}/音声${d.audio_count || 0})`;
            return '';
        case 'tester':
            if (d.files_tested !== undefined) {
                if (d.test_passed) return `テスト: ${d.files_tested}ファイル全て成功`;
                return `テスト: ${d.errors}件エラー / ${d.files_tested}ファイル`;
            }
            return '';
        case 'debugger':
            if (d.iteration) return `試行${d.iteration}/10 - ${d.errors_fixed || 0}件修正`;
            return '';
        case 'reviewer':
            if (d.comments !== undefined) return `コメント: ${d.comments}件 (重大${d.critical_count || 0}/警告${d.warning_count || 0})`;
            return '';
        default:
            return '';
    }
}

// Render functions
function renderAgentList() {
    const container = document.getElementById('agent-list');
    container.innerHTML = AGENTS.map(a => {
        const state = agentStates[a.id];
        const isSelected = selectedAgent === a.id;
        const statusLabel = STATUS_LABELS[state.status] || state.status;
        const progressInfo = getAgentProgressInfo(a.id, state);
        return `
            <div class="agent-item ${isSelected ? 'selected' : ''}" onclick="selectAgent('${a.id}')">
                <div class="agent-item-header">
                    <span class="agent-name">${a.label} [${a.name}]</span>
                    <span class="agent-status ${state.status}">${statusLabel}</span>
                </div>
                <div class="agent-message">${state.message || '-'}</div>
                ${progressInfo ? `<div class="agent-progress-info">${progressInfo}</div>` : ''}
                ${state.status === 'running' ? `
                    <div class="agent-progress">
                        <div class="agent-progress-bar" style="width: ${state.progress}%"></div>
                    </div>
                ` : ''}
            </div>
        `;
    }).join('');
}

function renderWorkflowGrid() {
    // Removed - using agent list only
}

function renderSelectedAgent() {
    if (!selectedAgent) return;

    const agent = AGENTS.find(a => a.id === selectedAgent);
    const state = agentStates[selectedAgent];
    const events = agentEvents[selectedAgent] || [];
    const statusLabel = STATUS_LABELS[state.status] || state.status;

    document.getElementById('selected-agent-header').innerHTML = `
        <div class="agent-detail-name">${agent.label} [${agent.name}]</div>
        <div class="agent-detail-status">${statusLabel} - ${state.message || '待機中...'}</div>
    `;

    document.getElementById('agent-events').innerHTML = events.slice(-20).reverse().map(e => `
        <div class="agent-event">
            <div class="agent-event-time">${e.timestamp}</div>
            <div class="agent-event-message">${e.message}</div>
        </div>
    `).join('') || '<div class="agent-event"><div class="agent-event-message">イベントなし</div></div>';
}

function addLogEntry(event) {
    const container = document.getElementById('log-view');
    const entry = document.createElement('div');
    entry.className = `log-entry ${event.status}`;
    entry.innerHTML = `
        <span class="log-time">${event.timestamp}</span>
        <span class="log-agent">${event.agent}</span>
        <span class="log-message">${event.message}</span>
    `;
    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
}

function selectAgent(agentId) {
    selectedAgent = agentId;
    renderAgentList();
    renderSelectedAgent();
}

function updateProgress() {
    const completed = AGENTS.filter(a => agentStates[a.id].status === 'completed').length;
    const total = AGENTS.length;
    document.getElementById('progress-text').textContent = `完了: ${completed}/${total}`;
}

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
    });
});

document.querySelectorAll('.detail-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.detail-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.detail-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`detail-${tab.dataset.detail}`).classList.add('active');
    });
});

// WebSocket
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        document.getElementById('connection-dot').classList.add('connected');
        document.getElementById('connection-text').textContent = 'CONNECTED';
        if (reconnectInterval) {
            clearInterval(reconnectInterval);
            reconnectInterval = null;
        }
    };

    ws.onclose = () => {
        document.getElementById('connection-dot').classList.remove('connected');
        document.getElementById('connection-text').textContent = 'DISCONNECTED';
        if (!reconnectInterval) {
            reconnectInterval = setInterval(connectWebSocket, 3000);
        }
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        if (msg.type === 'state_update') {
            updateState(msg.data);
        } else if (msg.type === 'agent_event') {
            handleAgentEvent(msg.data);
        }
    };
}

function updateState(state) {
    document.getElementById('current-phase').textContent = state.phase.toUpperCase();

    for (const [agent, status] of Object.entries(state.agents)) {
        if (agentStates[agent]) {
            agentStates[agent].status = status;
        }
    }

    if (state.game_spec) {
        document.getElementById('spec-title').textContent = state.game_spec.title || '-';
        document.getElementById('spec-genre').textContent = state.game_spec.genre || '-';
        document.getElementById('spec-platform').textContent = state.game_spec.target_platform || '-';
        document.getElementById('spec-description').textContent = state.game_spec.description || '-';
        document.getElementById('spec-visual').textContent = state.game_spec.visual_style || '-';
        document.getElementById('spec-audio').textContent = state.game_spec.audio_style || '-';
    }

    eventCount = state.events?.length || 0;
    document.getElementById('stat-events').textContent = eventCount;

    state.events?.forEach(e => {
        if (agentEvents[e.agent]) {
            agentEvents[e.agent].push(e);
        }
    });

    // Update lists
    renderTaskList(state.tasks || []);
    renderErrorList(state.errors || []);
    renderAssetList(state.assets || []);
    renderReviewList(state.review_comments || []);
    renderFileList(state.code_files || []);

    // Update LLM interactions
    if (state.llm_interactions) {
        currentLLMInteractions = state.llm_interactions;
        renderLLMList(currentLLMInteractions);
    }
    if (state.total_tokens) {
        updateTokens(state.total_tokens);
    }

    renderAgentList();
    renderWorkflowGrid();
    renderSelectedAgent();
    updateProgress();
}

function renderTaskList(tasks) {
    const container = document.getElementById('task-list');
    document.getElementById('task-count').textContent = `(${tasks.length})`;
    if (tasks.length === 0) {
        container.innerHTML = '<div class="empty-state">タスクなし</div>';
        return;
    }
    container.innerHTML = tasks.map(t => `
        <div class="item-entry">
            <div class="item-title">${t.id || '-'}</div>
            <div class="item-desc">${t.description || '-'}</div>
            <div class="item-meta">${t.assigned_agent || '-'} / ${t.status || '-'}</div>
        </div>
    `).join('');
}

function renderErrorList(errors) {
    const container = document.getElementById('error-list');
    document.getElementById('error-count').textContent = `(${errors.length})`;
    document.getElementById('stat-errors').textContent = errors.length;
    if (errors.length === 0) {
        container.innerHTML = '<div class="empty-state">エラーなし</div>';
        return;
    }
    container.innerHTML = errors.map(e => {
        const msg = typeof e === 'string' ? e : (e.message || e.error || JSON.stringify(e));
        return `<div class="item-entry error-item"><div class="item-desc">${msg}</div></div>`;
    }).join('');
}

function renderAssetList(assets) {
    const container = document.getElementById('asset-list');
    document.getElementById('asset-count').textContent = `(${assets.length})`;
    document.getElementById('stat-assets').textContent = assets.length;
    if (assets.length === 0) {
        container.innerHTML = '<div class="empty-state">アセットなし</div>';
        return;
    }
    container.innerHTML = assets.map(a => `
        <div class="item-entry">
            <div class="item-title">${a.name || a}</div>
            <div class="item-meta">${a.type || '-'}</div>
        </div>
    `).join('');
}

function renderReviewList(comments) {
    const container = document.getElementById('review-list');
    document.getElementById('review-count').textContent = `(${comments.length})`;
    if (comments.length === 0) {
        container.innerHTML = '<div class="empty-state">コメントなし</div>';
        return;
    }
    container.innerHTML = comments.map(c => {
        const msg = typeof c === 'string' ? c : (c.message || c.comment || JSON.stringify(c));
        const severity = c.severity || 'info';
        return `<div class="item-entry ${severity === 'error' ? 'error-item' : ''}"><div class="item-desc">${msg}</div></div>`;
    }).join('');
}

function renderFileList(files) {
    const container = document.getElementById('file-list');
    document.getElementById('stat-files').textContent = files.length;
    if (files.length === 0) {
        container.innerHTML = '<div class="empty-state">ファイルなし</div>';
        return;
    }
    container.innerHTML = files.map(f => `
        <div class="item-entry"><div class="item-title">${f}</div></div>
    `).join('');
}

// Store lists globally for updates
let currentTasks = [];
let currentErrors = [];
let currentAssets = [];
let currentReviews = [];
let currentFiles = [];
let currentLLMInteractions = [];
let totalTokens = { input: 0, output: 0 };

// Render LLM interaction list
function renderLLMList(interactions) {
    const container = document.getElementById('llm-list');
    document.getElementById('llm-count').textContent = `(${interactions.length})`;
    if (interactions.length === 0) {
        container.innerHTML = '<div class="empty-state">LLMやり取りなし</div>';
        return;
    }
    container.innerHTML = interactions.slice().reverse().map(i => `
        <div class="llm-entry">
            <div class="llm-entry-header">
                <span class="llm-entry-agent">${i.agent}</span>
                <span class="llm-entry-tokens">入力: ${i.input_tokens} / 出力: ${i.output_tokens}</span>
            </div>
            <div class="llm-entry-params">
                <span>Model: ${i.model || '-'}</span>
                <span>Temp: ${i.temperature !== undefined ? i.temperature : '-'}</span>
                <span>MaxTok: ${i.max_tokens || '-'}</span>
            </div>
            <div class="llm-entry-label">プロンプト</div>
            <div class="llm-entry-prompt">${escapeHtml(i.prompt || '')}</div>
            <div class="llm-entry-label">応答</div>
            <div class="llm-entry-response">${escapeHtml(i.response || '')}</div>
        </div>
    `).join('');
}

// Escape HTML for safe display
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Update token display
function updateTokens(tokens) {
    if (tokens) {
        totalTokens = tokens;
        document.getElementById('token-input').textContent = tokens.input || 0;
        document.getElementById('token-output').textContent = tokens.output || 0;
    }
}

// Update game spec display
function updateGameSpec(spec) {
    if (!spec) return;
    document.getElementById('spec-title').textContent = spec.title || '-';
    document.getElementById('spec-genre').textContent = spec.genre || '-';
    document.getElementById('spec-platform').textContent = spec.target_platform || '-';
    document.getElementById('spec-visual').textContent = spec.visual_style || '-';
    document.getElementById('spec-audio').textContent = spec.audio_style || '-';
    document.getElementById('spec-description').textContent = spec.description || '-';
}

function handleAgentEvent(event) {
    eventCount++;
    document.getElementById('stat-events').textContent = eventCount;

    if (agentStates[event.agent]) {
        agentStates[event.agent].status = event.status;
        agentStates[event.agent].message = event.message;

        // Store event details for progress display
        if (event.details) {
            agentStates[event.agent].details = {
                ...agentStates[event.agent].details,
                ...event.details
            };
        }

        // Estimate progress based on status
        if (event.status === 'running') {
            agentStates[event.agent].progress = 50;
        } else if (event.status === 'completed') {
            agentStates[event.agent].progress = 100;
        }
    }

    if (!agentEvents[event.agent]) {
        agentEvents[event.agent] = [];
    }
    agentEvents[event.agent].push(event);

    // Update lists from event details (real-time)
    if (event.details) {
        if (event.details.task_list !== undefined) {
            currentTasks = event.details.task_list;
            renderTaskList(currentTasks);
        }
        if (event.details.error_list !== undefined) {
            currentErrors = event.details.error_list;
            renderErrorList(currentErrors);
        }
        if (event.details.asset_list !== undefined) {
            currentAssets = event.details.asset_list;
            renderAssetList(currentAssets);
        }
        if (event.details.comment_list !== undefined) {
            currentReviews = event.details.comment_list;
            renderReviewList(currentReviews);
        }
        if (event.details.file_list !== undefined) {
            currentFiles = event.details.file_list;
            renderFileList(currentFiles);
        }
        // Also update spec if available (full game_spec or individual fields)
        if (event.details.game_spec) {
            updateGameSpec(event.details.game_spec);
        }
        if (event.details.title) {
            document.getElementById('spec-title').textContent = event.details.title;
        }
        if (event.details.genre) {
            document.getElementById('spec-genre').textContent = event.details.genre;
        }
        if (event.details.target_platform) {
            document.getElementById('spec-platform').textContent = event.details.target_platform;
        }
        if (event.details.visual_style) {
            document.getElementById('spec-visual').textContent = event.details.visual_style;
        }
        if (event.details.audio_style) {
            document.getElementById('spec-audio').textContent = event.details.audio_style;
        }
        if (event.details.description) {
            document.getElementById('spec-description').textContent = event.details.description;
        }
        // Handle LLM interactions
        if (event.details.llm_interaction) {
            currentLLMInteractions.push(event.details.llm_interaction);
            renderLLMList(currentLLMInteractions);
        }
        if (event.details.total_tokens) {
            updateTokens(event.details.total_tokens);
        }
    }

    addLogEntry(event);
    renderAgentList();
    renderWorkflowGrid();
    if (selectedAgent === event.agent) {
        renderSelectedAgent();
    }
    updateProgress();
}

async function startWorkflow() {
    const request = document.getElementById('request-input').value;
    const phase = document.getElementById('phase-select').value;
    const model = document.getElementById('llm-model-select').value;
    const temperature = parseFloat(document.getElementById('llm-temp-input').value);
    const maxTokens = parseInt(document.getElementById('llm-max-tokens-input').value);

    // Update LLM config display
    document.getElementById('llm-model').textContent = model;
    document.getElementById('llm-temperature').textContent = temperature;
    document.getElementById('llm-max-tokens').textContent = maxTokens;

    // Reset state with new structure
    AGENTS.forEach(a => {
        agentStates[a.id] = {
            status: 'pending',
            message: '',
            progress: 0,
            details: {},
            result: ''
        };
        agentEvents[a.id] = [];
    });
    eventCount = 0;

    // Reset all lists
    currentTasks = [];
    currentErrors = [];
    currentAssets = [];
    currentReviews = [];
    currentFiles = [];
    renderTaskList([]);
    renderErrorList([]);
    renderAssetList([]);
    renderReviewList([]);
    renderFileList([]);

    // Reset spec display
    document.getElementById('spec-title').textContent = '-';
    document.getElementById('spec-genre').textContent = '-';
    document.getElementById('spec-platform').textContent = '-';
    document.getElementById('spec-visual').textContent = '-';
    document.getElementById('spec-audio').textContent = '-';
    document.getElementById('spec-description').textContent = '-';

    // Reset LLM interactions
    currentLLMInteractions = [];
    totalTokens = { input: 0, output: 0 };
    renderLLMList([]);
    updateTokens({ input: 0, output: 0 });

    // Reset stats
    document.getElementById('log-view').innerHTML = '';
    document.getElementById('stat-events').textContent = '0';
    document.getElementById('stat-files').textContent = '0';
    document.getElementById('stat-assets').textContent = '0';
    document.getElementById('stat-errors').textContent = '0';

    startTime = new Date();
    document.getElementById('stat-started').textContent = startTime.toLocaleTimeString();

    if (elapsedInterval) clearInterval(elapsedInterval);
    elapsedInterval = setInterval(() => {
        const elapsed = Math.floor((new Date() - startTime) / 1000);
        const min = Math.floor(elapsed / 60);
        const sec = elapsed % 60;
        document.getElementById('stat-elapsed').textContent = `${min}:${sec.toString().padStart(2, '0')}`;
    }, 1000);

    renderAgentList();
    renderWorkflowGrid();

    try {
        await fetch('/api/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                request,
                phase,
                llm_config: {
                    model: model,
                    temperature: temperature,
                    max_tokens: maxTokens
                }
            })
        });
    } catch (error) {
        console.error('Failed to start:', error);
    }
}

async function stopWorkflow() {
    if (elapsedInterval) {
        clearInterval(elapsedInterval);
        elapsedInterval = null;
    }
    try {
        await fetch('/api/stop', { method: 'POST' });
    } catch (error) {
        console.error('Failed to stop:', error);
    }
}

// Initialize
connectWebSocket();
renderAgentList();
renderWorkflowGrid();
