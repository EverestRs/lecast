/* common.js — 全局工具函数（Toast 通知等） */

/**
 * 显示 Bootstrap Toast 通知
 * @param {string} message 提示内容（纯文本）
 * @param {'success'|'error'|'warning'|'info'} type 类型，决定配色与图标
 * @param {number} delay 自动关闭时间（ms），error 默认 6000，其余 3000
 */
function showToast(message, type = 'info', delay = null) {
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        document.body.appendChild(container);
    }

    const icons = {
        success: 'bi-check-circle-fill',
        error: 'bi-x-circle-fill',
        warning: 'bi-exclamation-triangle-fill',
        info: 'bi-info-circle-fill',
    };
    const colors = {
        success: 'text-success',
        error: 'text-danger',
        warning: 'text-warning',
        info: 'text-primary',
    };

    const el = document.createElement('div');
    el.className = 'toast align-items-center border-0';
    el.setAttribute('role', 'alert');

    const row = document.createElement('div');
    row.className = 'd-flex';

    const body = document.createElement('div');
    body.className = 'toast-body';
    const icon = document.createElement('i');
    icon.className = `bi ${icons[type] || icons.info} ${colors[type] || colors.info} me-2`;
    const text = document.createElement('span');
    text.textContent = String(message ?? '');
    body.appendChild(icon);
    body.appendChild(text);

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'btn-close me-2 m-auto';
    closeBtn.setAttribute('data-bs-dismiss', 'toast');

    row.appendChild(body);
    row.appendChild(closeBtn);
    el.appendChild(row);
    container.appendChild(el);

    const toast = new bootstrap.Toast(el, { delay: delay ?? (type === 'error' ? 6000 : 3000) });
    el.addEventListener('hidden.bs.toast', () => el.remove());
    toast.show();
}

/** 便捷封装 */
const toastSuccess = (msg) => showToast(msg, 'success');
const toastError = (msg) => showToast(msg, 'error');
const toastWarning = (msg) => showToast(msg, 'warning');
const toastInfo = (msg) => showToast(msg, 'info');

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * 统一 API 请求：附带 X-API-Key（对话生成）与 X-TTS-Key（语音合成），校验 HTTP 状态与业务 code
 * @returns {Promise<{code:number,message:string,data:any}>} 仅在 code===200 时 resolve
 */
async function apiFetch(url, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    const key = localStorage.getItem('apiKey') || '';
    if (key) headers['X-API-Key'] = key;
    const ttsKey = localStorage.getItem('apiKeyTts') || '';
    if (ttsKey) headers['X-TTS-Key'] = ttsKey;
    // FormData 由浏览器自动生成 multipart 边界，不能手动设 JSON Content-Type
    if (options.body && !(options.body instanceof FormData) && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
    }

    const res = await fetch(url, Object.assign({}, options, { headers }));
    let json = null;
    try { json = await res.json(); } catch (e) { /* 非 JSON 响应 */ }

    if (!res.ok) {
        const detail = json ? json.message || json.detail : null;
        const msg = Array.isArray(detail)
            ? detail.map(d => d.msg || d).join('；')
            : detail || `HTTP ${res.status}`;
        throw new Error(msg);
    }
    if (!json || json.code !== 200) {
        throw new Error((json && json.message) || `接口返回异常 code=${json ? json.code : 'null'}`);
    }
    return json;
}

function renderAreaLoading() {
    return '<div class="text-center text-muted py-3"><span class="spinner-border spinner-border-sm me-2"></span>加载中...</div>';
}

function renderAreaError(message, retryFnName) {
    return `<div class="text-center text-muted py-3">
        <div class="mb-2"><i class="bi bi-x-circle text-danger me-1"></i>${escapeHtml(message)}</div>
        <button class="btn btn-sm btn-outline-primary" onclick="${retryFnName}()">
            <i class="bi bi-arrow-clockwise"></i> 重试
        </button>
    </div>`;
}

/** 长操作按钮计时反馈，返回停止函数 */
function startElapsedTimer(btn, stageText) {
    const start = Date.now();
    const prefix = stageText ? escapeHtml(stageText) + '，' : '';
    const render = () => {
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>${prefix}已耗时 ${Math.floor((Date.now() - start) / 1000)}s`;
    };
    render();
    const id = setInterval(render, 1000);
    return () => clearInterval(id);
}

/** 通用确认弹窗；onOk 在点击确定后执行 */
function confirmModal(title, bodyHtml, onOk) {
    const modal = document.createElement('div');
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">${title}</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">${bodyHtml}</div>
                <div class="modal-footer border-0">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
                    <button type="button" class="btn btn-primary" id="confirmModalOkBtn">确定</button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    const bsModal = new bootstrap.Modal(modal);
    modal.querySelector('#confirmModalOkBtn').addEventListener('click', () => {
        bsModal.hide();
        onOk();
    });
    modal.addEventListener('hidden.bs.modal', () => modal.remove());
    bsModal.show();
}

/** 本地密钥与服务端默认密钥任一可用即可发起生成 */
function hasUsableKey() {
    return !!(localStorage.getItem('apiKey') || window.SERVER_SK);
}

/** 根据本地/服务端密钥配置情况刷新各页配置按钮状态 */
function refreshSkStatus() {
    const hasChat = !!(localStorage.getItem('apiKey') || window.SERVER_SK);
    const hasTts = !!(localStorage.getItem('apiKeyTts') || window.SERVER_MIMO_SK);
    document.querySelectorAll('.js-config-sk').forEach(btn => {
        btn.classList.toggle('btn-success', hasChat);
        btn.classList.toggle('btn-outline-secondary', !hasChat);
        const label = btn.querySelector('.sk-btn-text');
        if (label) label.textContent = hasChat ? (localStorage.getItem('apiKey') ? '已配置 SK' : '服务器密钥') : '配置 SK';
        const src = k => localStorage.getItem(k) ? '本地' : '未配置';
        const chatSrc = localStorage.getItem('apiKey') ? '本地' : (window.SERVER_SK ? '服务器密钥' : '未配置');
        btn.title = `对话生成：${chatSrc}；语音合成：${hasTts ? (localStorage.getItem('apiKeyTts') ? '本地' : '服务器密钥') : '未配置'}`;
    });
}

function configSK() {
    const el = document.getElementById('skModal');
    if (!el) return;
    // 回填已保存密钥，password 输入框以圆点密文显示
    document.getElementById('chatKeyInput').value = localStorage.getItem('apiKey') || '';
    document.getElementById('ttsKeyInput').value = localStorage.getItem('apiKeyTts') || '';
    bootstrap.Modal.getOrCreateInstance(el).show();
}

function saveSK() {
    const chatKey = document.getElementById('chatKeyInput').value.trim();
    const ttsKey = document.getElementById('ttsKeyInput').value.trim();
    if (!chatKey && !window.SERVER_SK) { toastWarning('对话生成 API Key 不能为空（且服务器未配置默认密钥）'); return; }
    if (chatKey) localStorage.setItem('apiKey', chatKey);
    else localStorage.removeItem('apiKey');
    if (ttsKey) localStorage.setItem('apiKeyTts', ttsKey);
    else localStorage.removeItem('apiKeyTts');
    // task_create 页缓存了 apiKey 全局变量，需同步
    if (typeof apiKey !== 'undefined') apiKey = chatKey;
    bootstrap.Modal.getInstance(document.getElementById('skModal')).hide();
    toastSuccess(chatKey || ttsKey ? 'API Key 配置成功！后续步骤将自动使用' : '已清除本地密钥，将使用服务器默认密钥');
    refreshSkStatus();
}

document.addEventListener('DOMContentLoaded', refreshSkStatus);

// 其他标签页修改了 apiKey 时同步本页缓存的全局变量
window.addEventListener('storage', e => {
    if (e.key === 'apiKey' && typeof apiKey !== 'undefined') apiKey = e.newValue || '';
});

/**
 * 轮询后台作业直到终态，期间把阶段进度渲染到按钮。
 * @param {string} step 作业类型（split/slides/scripts/tts/video/pptx）
 * @param {string} taskId
 * @param {HTMLElement|null} btn 进度展示按钮（可空）
 * @param {number} intervalMs 轮询间隔
 * @returns {Promise<{state:'success'|'failed'|'none', result?:string, error?:string}>}
 */
function pollJobUntilDone(step, taskId, btn, intervalMs = 2000) {
    const start = Date.now();
    let lastStage = '处理中';
    let pollId = null;
    let done = false;
    let resolvePromise = null;

    const renderBtn = () => {
        if (!btn) return;
        const secs = Math.floor((Date.now() - start) / 1000);
        const cnt = btn.dataset.jobTotal ? ` (${btn.dataset.jobCurrent || 0}/${btn.dataset.jobTotal})` : '';
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>${escapeHtml(lastStage)}${cnt} · 已耗时 ${secs}s`;
    };

    const finish = (outcome) => {
        if (done) return;
        done = true;
        clearInterval(pollId);
        if (btn) {
            btn.disabled = false;
            delete btn.dataset.jobTotal;
            delete btn.dataset.jobCurrent;
        }
        resolvePromise(outcome);
    };

    const poll = async () => {
        let d;
        try {
            const res = await apiFetch(`/api/task/job/${step}/${taskId}`);
            d = res.data || {};
        } catch (e) {
            return; // 单次轮询失败忽略，下一轮重试
        }
        if (d.state === 'running') {
            lastStage = d.stage || '处理中';
            if (btn) {
                if (d.total > 0) {
                    btn.dataset.jobTotal = d.total;
                    btn.dataset.jobCurrent = d.current;
                } else {
                    delete btn.dataset.jobTotal;
                }
            }
            renderBtn();
        } else if (d.state === 'success') {
            finish({ state: 'success', result: d.result });
        } else if (d.state === 'failed') {
            toastError(d.error || '后台任务执行失败');
            finish({ state: 'failed', error: d.error });
        } else {
            // state=none：服务重启导致内存作业丢失
            toastWarning('后台任务状态已失效（服务可能重启过），请刷新页面查看');
            finish({ state: 'none' });
        }
    };

    if (btn) btn.disabled = true;
    renderBtn();
    const promise = new Promise(resolve => { resolvePromise = resolve; });
    poll();
    pollId = setInterval(poll, intervalMs);
    return promise;
}