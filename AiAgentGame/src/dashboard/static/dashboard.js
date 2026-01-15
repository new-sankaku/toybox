// LLM config cache
let llmConfig = null;

// Load LLM config from server
async function loadLLMConfig() {
    try {
        const response = await fetch('/api/llm-config');
        const data = await response.json();
        llmConfig = data;
        initializeLLMSelectors(data);
    } catch (error) {
        console.error('Failed to load LLM config:', error);
        // Fallback to default config
        llmConfig = {
            providers: {
                anthropic: {
                    models: [
                        { id: 'claude-sonnet-4-20250514', name: 'Claude Sonnet 4', max_tokens: 8192 }
                    ]
                }
            },
            default: { provider: 'anthropic', model: 'claude-sonnet-4-20250514' }
        };
        initializeLLMSelectors(llmConfig);
    }
}

// Initialize LLM provider and model selectors
function initializeLLMSelectors(config) {
    const providerSelect = document.getElementById('llm-provider-select');
    const modelSelect = document.getElementById('llm-model-select');

    // Clear and populate provider select
    providerSelect.innerHTML = '';

    const providers = config.providers || {};
    const providerIds = Object.keys(providers);

    if (providerIds.length === 0) {
        // No providers available (no API keys set)
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'APIキーが設定されていません';
        providerSelect.appendChild(option);
        modelSelect.innerHTML = '<option value="">モデルなし</option>';
        return;
    }

    for (const [providerId, providerData] of Object.entries(providers)) {
        if (providerData.models && providerData.models.length > 0) {
            const option = document.createElement('option');
            option.value = providerId;
            option.textContent = getProviderDisplayName(providerId);
            providerSelect.appendChild(option);
        }
    }

    // Set default provider
    if (config.default && config.default.provider && providers[config.default.provider]) {
        providerSelect.value = config.default.provider;
    }

    // Update models for selected provider
    updateModelSelect();

    // Set default model if specified
    if (config.default && config.default.model) {
        modelSelect.value = config.default.model;
        updateMaxTokensLimit();
    }

    // Add event listeners
    providerSelect.addEventListener('change', () => {
        updateModelSelect();
        updateMaxTokensLimit();
    });

    modelSelect.addEventListener('change', updateMaxTokensLimit);
}

// Get display name for provider
function getProviderDisplayName(providerId) {
    const names = {
        'anthropic': 'Anthropic (Claude)',
        'openai': 'OpenAI (GPT)',
        'deepseek': 'DeepSeek',
        'custom': 'Custom'
    };
    return names[providerId] || providerId;
}

// Update model select based on provider
function updateModelSelect() {
    const providerSelect = document.getElementById('llm-provider-select');
    const modelSelect = document.getElementById('llm-model-select');
    const provider = providerSelect.value;

    modelSelect.innerHTML = '';

    if (llmConfig && llmConfig.providers && llmConfig.providers[provider]) {
        const models = llmConfig.providers[provider].models || [];
        for (const model of models) {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = model.name;
            option.dataset.maxTokens = model.max_tokens || 4096;
            modelSelect.appendChild(option);
        }
    }
}

// Update max tokens limit display
function updateMaxTokensLimit() {
    const modelSelect = document.getElementById('llm-model-select');
    const maxTokensInput = document.getElementById('llm-max-tokens-input');
    const maxTokensLimit = document.getElementById('llm-max-tokens-limit');

    const selectedOption = modelSelect.options[modelSelect.selectedIndex];
    if (selectedOption) {
        const maxTokens = parseInt(selectedOption.dataset.maxTokens) || 4096;
        maxTokensLimit.textContent = `(max: ${maxTokens})`;
        maxTokensInput.max = maxTokens;

        // Adjust current value if exceeds max
        if (parseInt(maxTokensInput.value) > maxTokens) {
            maxTokensInput.value = maxTokens;
        }
    }
}

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

// Asset subtabs
document.querySelectorAll('.asset-subtab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.asset-subtab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.asset-tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`asset-${tab.dataset.assetTab}`).classList.add('active');
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
        updateGameSpec(state.game_spec);
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
    // Update stat count
    document.getElementById('stat-assets').textContent = assets.length;

    // Process assets to update status in the dynamic asset grid
    assets.forEach(a => {
        if (a && a.type && a.category && a.name) {
            // Map asset type to tab key
            let tabKey = 'text';
            if (a.type === 'image' || a.type === 'sprite' || a.type === 'background') {
                tabKey = 'image';
            } else if (a.type === 'audio' || a.type === 'bgm' || a.type === 'se') {
                tabKey = 'audio';
            }
            updateAssetStatus(tabKey, a.category, a.name, a.status || 'completed');
        }
    });
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

// Update game spec display - maps to architecture fields
function updateGameSpec(spec) {
    if (!spec) return;
    updateArchitecture({
        genre: spec.genre,
        platform: spec.target_platform,
        art: spec.visual_style,
        audio: spec.audio_style,
        theme: spec.description
    });
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
        // Update architecture from individual spec fields
        const archUpdate = {};
        if (event.details.genre) archUpdate.genre = event.details.genre;
        if (event.details.target_platform) archUpdate.platform = event.details.target_platform;
        if (event.details.visual_style) archUpdate.art = event.details.visual_style;
        if (event.details.audio_style) archUpdate.audio = event.details.audio_style;
        if (event.details.description) archUpdate.theme = event.details.description;
        if (Object.keys(archUpdate).length > 0) {
            updateArchitecture(archUpdate);
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
    const provider = document.getElementById('llm-provider-select').value;
    const model = document.getElementById('llm-model-select').value;
    const temperature = parseFloat(document.getElementById('llm-temp-input').value);
    const maxTokens = parseInt(document.getElementById('llm-max-tokens-input').value);

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

    // Reset architecture display
    updateArchitecture({
        genre: '-', target: '-', platform: '-', theme: '-', coreFun: '-',
        rules: '-', controls: '-', flow: '-', difficulty: '-', reward: '-',
        scenario: '-', characters: '-', world: '-',
        art: '-', ui: '-', audio: '-',
        engine: '-', resolution: '-', data: '-', network: '-',
        stages: '-', placement: '-', tutorial: '-',
        monetize: '-', updates: '-', support: '-',
        schedule: '-', budget: '-', outsource: '-'
    });

    // Reset task and asset status
    taskStatus = {};
    assetStatus = {};
    renderTaskPhases();
    renderAssetSubtabs();
    renderAssetContent();

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
                    provider: provider,
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

// ============================================
// Dynamic Task Phases Rendering
// ============================================

// Default task phases structure (can be overridden by Planner Agent)
let taskPhases = [
    { id: 'concept', name: '企画・コンセプト', tasks: ['ゲームコンセプト決定', 'ターゲット層定義', 'コアメカニクス設計', 'マネタイズ方針'] },
    { id: 'design', name: 'ゲームデザイン', tasks: ['ルール設計', '難易度曲線設計', 'UI/UXフロー設計', 'バランス設計'] },
    { id: 'story', name: 'シナリオ・世界観', tasks: ['ストーリー構成', 'キャラクター設定', '世界観設定', 'ダイアログ作成'] },
    { id: 'prototype', name: 'プロトタイプ', tasks: ['コア機能実装', '仮アセット作成', '動作確認', 'フィードバック収集'] },
    { id: 'art', name: 'ビジュアル制作', tasks: ['キャラクターデザイン', '背景制作', 'UI素材制作', 'アニメーション制作', 'エフェクト制作'] },
    { id: 'audio', name: 'オーディオ制作', tasks: ['BGM作曲', 'SE制作', '環境音制作', 'ボイス収録'] },
    { id: 'implementation', name: '実装', tasks: ['ゲームシステム実装', 'UI実装', 'データ連携', 'セーブ/ロード機能'] },
    { id: 'integration', name: '統合・調整', tasks: ['アセット統合', 'パラメータ調整', 'バグ修正', '最適化'] },
    { id: 'testing', name: 'テスト', tasks: ['機能テスト', 'バランステスト', 'ユーザビリティテスト', '負荷テスト'] },
    { id: 'release', name: 'リリース', tasks: ['最終確認', 'ビルド作成', 'ストア申請', 'ランチプロモーション'] }
];

// Task status tracking
let taskStatus = {};

function renderTaskPhases() {
    const container = document.getElementById('task-phases-container');
    if (!container) return;

    container.innerHTML = taskPhases.map(phase => {
        const tasks = phase.tasks || [];
        const completed = tasks.filter(t => taskStatus[`${phase.id}:${t}`] === 'completed').length;
        const running = tasks.filter(t => taskStatus[`${phase.id}:${t}`] === 'running').length;
        const statusClass = running > 0 ? 'running' : (completed === tasks.length && tasks.length > 0 ? 'completed' : '');

        return `
            <div class="detail-section task-phase ${statusClass}">
                <div class="detail-section-title">${phase.name} <span class="phase-progress">(${completed}/${tasks.length})</span></div>
                <div class="task-grid">
                    ${tasks.map(task => {
                        const status = taskStatus[`${phase.id}:${task}`] || 'pending';
                        return `<div class="task-item ${status}" title="${task}">${task}</div>`;
                    }).join('')}
                </div>
            </div>
        `;
    }).join('');
}

// Update task phases from Planner Agent data
function updateTaskPhases(phases) {
    if (phases && Array.isArray(phases)) {
        taskPhases = phases;
        renderTaskPhases();
    }
}

// Update individual task status
function updateTaskStatus(phaseId, taskName, status) {
    taskStatus[`${phaseId}:${taskName}`] = status;
    renderTaskPhases();
}

// ============================================
// Dynamic Asset Rendering
// ============================================

// Default asset categories (can be overridden by Planner Agent)
let assetCategories = {
    image: {
        name: '画像系',
        categories: [
            { id: 'character', name: 'キャラクター', items: ['プレイヤー', '敵キャラ', 'NPC', 'ボス'] },
            { id: 'background', name: '背景', items: ['タイトル画面', 'ステージ背景', 'メニュー背景'] },
            { id: 'ui', name: 'UI', items: ['ボタン', 'アイコン', 'フレーム', 'ゲージ'] },
            { id: 'effect', name: 'エフェクト', items: ['パーティクル', 'ヒットエフェクト', '爆発'] },
            { id: 'item', name: 'アイテム・オブジェクト', items: ['アイテム', '障害物', 'コレクション'] }
        ]
    },
    audio: {
        name: 'サウンド系',
        categories: [
            { id: 'bgm', name: 'BGM', items: ['タイトルBGM', 'ゲームプレイBGM', 'ボス戦BGM', 'リザルトBGM'] },
            { id: 'se', name: '効果音', items: ['ジャンプ', '着地', '攻撃', 'ダメージ', 'アイテム取得', '決定', 'キャンセル'] },
            { id: 'ambient', name: '環境音', items: ['風', '水', '森', '街'] }
        ]
    },
    text: {
        name: 'テキスト系',
        categories: [
            { id: 'dialog', name: 'ダイアログ', items: ['オープニング', 'チュートリアル', 'エンディング', 'NPC会話'] },
            { id: 'ui-text', name: 'UI文言', items: ['メニュー', 'ヘルプ', 'チュートリアルガイド'] },
            { id: 'data', name: 'データ', items: ['ステージデータ', '敵パラメータ', 'アイテムマスタ', 'ローカライズ'] }
        ]
    }
};

// Asset status tracking
let assetStatus = {};
let currentAssetTab = 'image';

function renderAssetSubtabs() {
    const container = document.getElementById('asset-subtabs-container');
    if (!container) return;

    const tabs = Object.entries(assetCategories);
    container.innerHTML = tabs.map(([key, data], idx) => {
        const isActive = key === currentAssetTab;
        const totalAssets = data.categories.reduce((sum, cat) => sum + cat.items.length, 0);
        const completedAssets = data.categories.reduce((sum, cat) =>
            sum + cat.items.filter(item => assetStatus[`${key}:${cat.id}:${item}`] === 'completed').length, 0);
        return `<div class="asset-subtab ${isActive ? 'active' : ''}" data-asset-tab="${key}">
            ${data.name} <span class="asset-count">(${completedAssets}/${totalAssets})</span>
        </div>`;
    }).join('');

    // Re-attach event listeners
    container.querySelectorAll('.asset-subtab').forEach(tab => {
        tab.addEventListener('click', () => {
            currentAssetTab = tab.dataset.assetTab;
            renderAssetSubtabs();
            renderAssetContent();
        });
    });
}

function renderAssetContent() {
    const container = document.getElementById('asset-tabs-container');
    if (!container) return;

    const data = assetCategories[currentAssetTab];
    if (!data) {
        container.innerHTML = '<div class="empty-state">カテゴリなし</div>';
        return;
    }

    container.innerHTML = data.categories.map(cat => {
        const items = cat.items || [];
        return `
            <div class="detail-section">
                <div class="detail-section-title">${cat.name} (${items.length})</div>
                <div class="asset-grid">
                    ${items.map(item => {
                        const status = assetStatus[`${currentAssetTab}:${cat.id}:${item}`] || 'pending';
                        const canPreview = currentAssetTab === 'image' || currentAssetTab === 'audio';
                        const previewClick = canPreview ? `onclick="previewAsset('${currentAssetTab}', '${cat.id}', '${item}')"` : '';
                        return `<div class="asset-item ${status}" ${previewClick} title="${item}">
                            ${canPreview ? '<span class="preview-icon">👁</span>' : ''}
                            <span class="asset-name">${item}</span>
                            <span class="asset-status-icon">${getStatusIcon(status)}</span>
                        </div>`;
                    }).join('')}
                </div>
            </div>
        `;
    }).join('');
}

function getStatusIcon(status) {
    switch(status) {
        case 'completed': return '✓';
        case 'running': return '⟳';
        case 'error': return '✗';
        default: return '○';
    }
}

// Update asset categories from Planner Agent data
function updateAssetCategories(categories) {
    if (categories && typeof categories === 'object') {
        assetCategories = categories;
        renderAssetSubtabs();
        renderAssetContent();
    }
}

// Update individual asset status
function updateAssetStatus(tabKey, categoryId, itemName, status) {
    assetStatus[`${tabKey}:${categoryId}:${itemName}`] = status;
    renderAssetSubtabs();
    renderAssetContent();
}

// ============================================
// Asset Preview Functions
// ============================================

function previewAsset(tabKey, categoryId, itemName) {
    const modal = document.getElementById('asset-preview-modal');
    const title = document.getElementById('asset-preview-title');
    const body = document.getElementById('asset-preview-body');

    title.textContent = `${itemName} (${categoryId})`;

    // Check if asset exists and get path
    const assetPath = getAssetPath(tabKey, categoryId, itemName);

    if (tabKey === 'image') {
        body.innerHTML = `
            <div class="preview-image-container">
                <img src="${assetPath}" alt="${itemName}" onerror="this.parentElement.innerHTML='<div class=\\'preview-placeholder\\'>画像が生成されていません</div>'">
            </div>
        `;
    } else if (tabKey === 'audio') {
        body.innerHTML = `
            <div class="preview-audio-container">
                <audio controls src="${assetPath}" onerror="this.parentElement.innerHTML='<div class=\\'preview-placeholder\\'>音声が生成されていません</div>'">
                    音声ファイル
                </audio>
                <div class="audio-visualizer" id="audio-visualizer"></div>
            </div>
        `;
    } else {
        body.innerHTML = '<div class="preview-placeholder">このアセットはプレビューできません</div>';
    }

    modal.classList.add('active');
}

function getAssetPath(tabKey, categoryId, itemName) {
    // Generate asset path based on naming convention
    const safeName = itemName.replace(/[^a-zA-Z0-9\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]/g, '_').toLowerCase();
    const ext = tabKey === 'image' ? 'png' : (tabKey === 'audio' ? 'mp3' : 'json');
    return `/output/assets/${tabKey}/${categoryId}/${safeName}.${ext}`;
}

function closeAssetPreview() {
    const modal = document.getElementById('asset-preview-modal');
    modal.classList.remove('active');
}

// Close modal on outside click
document.addEventListener('click', (e) => {
    const modal = document.getElementById('asset-preview-modal');
    if (e.target === modal) {
        closeAssetPreview();
    }
});

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeAssetPreview();
    }
});

// ============================================
// Architecture Update Functions
// ============================================

// Architecture data structure
let architectureData = {
    // 基本コンセプト
    genre: '-',
    target: '-',
    platform: '-',
    theme: '-',
    coreFun: '-',
    // ゲームメカニクス
    rules: '-',
    controls: '-',
    flow: '-',
    difficulty: '-',
    reward: '-',
    // ストーリー・キャラクター
    scenario: '-',
    characters: '-',
    world: '-',
    // ビジュアル・オーディオ
    art: '-',
    ui: '-',
    audio: '-',
    // 技術仕様
    engine: '-',
    resolution: '-',
    data: '-',
    network: '-',
    // レベルデザイン
    stages: '-',
    placement: '-',
    tutorial: '-',
    // 収益・運営
    monetize: '-',
    updates: '-',
    support: '-',
    // スケジュール・リソース
    schedule: '-',
    budget: '-',
    outsource: '-'
};

function updateArchitecture(data) {
    if (!data) return;

    // Map data to architecture fields
    const fieldMap = {
        'arch-genre': data.genre || architectureData.genre,
        'arch-target': data.target || architectureData.target,
        'arch-platform': data.platform || architectureData.platform,
        'arch-theme': data.theme || architectureData.theme,
        'arch-core-fun': data.coreFun || architectureData.coreFun,
        'arch-rules': data.rules || architectureData.rules,
        'arch-controls': data.controls || architectureData.controls,
        'arch-flow': data.flow || architectureData.flow,
        'arch-difficulty': data.difficulty || architectureData.difficulty,
        'arch-reward': data.reward || architectureData.reward,
        'arch-scenario': data.scenario || architectureData.scenario,
        'arch-characters': data.characters || architectureData.characters,
        'arch-world': data.world || architectureData.world,
        'arch-art': data.art || architectureData.art,
        'arch-ui': data.ui || architectureData.ui,
        'arch-audio': data.audio || architectureData.audio,
        'arch-engine': data.engine || architectureData.engine,
        'arch-resolution': data.resolution || architectureData.resolution,
        'arch-data': data.data || architectureData.data,
        'arch-network': data.network || architectureData.network,
        'arch-stages': data.stages || architectureData.stages,
        'arch-placement': data.placement || architectureData.placement,
        'arch-tutorial': data.tutorial || architectureData.tutorial,
        'arch-monetize': data.monetize || architectureData.monetize,
        'arch-updates': data.updates || architectureData.updates,
        'arch-support': data.support || architectureData.support,
        'arch-schedule': data.schedule || architectureData.schedule,
        'arch-budget': data.budget || architectureData.budget,
        'arch-outsource': data.outsource || architectureData.outsource
    };

    // Update each field
    for (const [id, value] of Object.entries(fieldMap)) {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value;
            // Highlight if value changed
            if (value !== '-') {
                el.classList.add('has-value');
            }
        }
    }

    // Store updated values
    architectureData = { ...architectureData, ...data };
}

// ============================================
// Enhanced Event Handler
// ============================================

// Extended handleAgentEvent to process dynamic updates
const originalHandleAgentEvent = handleAgentEvent;
handleAgentEvent = function(event) {
    // Call original handler
    originalHandleAgentEvent(event);

    // Process additional dynamic updates
    if (event.details) {
        // Update task phases if provided
        if (event.details.task_phases) {
            updateTaskPhases(event.details.task_phases);
        }

        // Update individual task status
        if (event.details.task_update) {
            const { phaseId, taskName, status } = event.details.task_update;
            updateTaskStatus(phaseId, taskName, status);
        }

        // Update asset categories if provided
        if (event.details.asset_categories) {
            updateAssetCategories(event.details.asset_categories);
        }

        // Update individual asset status
        if (event.details.asset_update) {
            const { tabKey, categoryId, itemName, status } = event.details.asset_update;
            updateAssetStatus(tabKey, categoryId, itemName, status);
        }

        // Update architecture if provided
        if (event.details.architecture) {
            updateArchitecture(event.details.architecture);
        }
    }
};

// Initialize
connectWebSocket();
loadLLMConfig();
renderAgentList();
renderWorkflowGrid();
renderTaskPhases();
renderAssetSubtabs();
renderAssetContent();
