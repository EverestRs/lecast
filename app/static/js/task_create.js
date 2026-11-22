/* task_create.js — 6 步任务创建向导（核心：导航 + 状态 + Step 1 + 工具函数） */
/* 步骤 2-6 定义在 task_create_steps.js 中 */

// ── 状态 ──
let currentStep = 0;
let taskId = new URLSearchParams(window.location.search).get('taskId') || '';
let taskName = '';
let apiKey = localStorage.getItem('apiKey') || '';
let pollingInterval = null;

const STEPS = ['step1', 'step2', 'step3', 'step4', 'step5', 'step6'];

// 防止文件被拖到页面非上传区时浏览器直接打开该文件
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('drop', e => e.preventDefault());

// ── 初始化 ──
document.addEventListener('DOMContentLoaded', () => {
    if (taskId) {
        Promise.all([
            fetch(`/api/task/detail/${taskId}`).then(r => r.json()),
            fetch(`/api/task/status/${taskId}`).then(r => r.json()),
        ]).then(([detailRes, statusRes]) => {
            if (detailRes.code === 200 && detailRes.data) {
                taskName = detailRes.data.taskName || '';
            }
            currentStep = resolveInitialStep(statusRes);
            renderStep();
            updateNav();
        }).catch(() => {
            renderStep();
            updateNav();
        });
    } else {
        renderStep();
        updateNav();
    }
    highlightNav();

    const stepsNav = document.getElementById('stepsNav');
    if (stepsNav) {
        stepsNav.addEventListener('keydown', e => {
            const item = e.target.closest('.step-item');
            if (item && (e.key === 'Enter' || e.key === ' ')) {
                e.preventDefault();
                jumpToStep(parseInt(item.dataset.step, 10));
            }
        });
    }
});

function resolveInitialStep(statusRes) {
    const urlStep = parseInt(new URLSearchParams(window.location.search).get('step'), 10);
    if (!Number.isNaN(urlStep) && urlStep >= 1 && urlStep <= 6) return urlStep - 1;
    const stepIndex = statusRes && statusRes.code === 200 && statusRes.data ? (statusRes.data.stepIndex || 0) : 0;
    return Math.min(stepIndex + 1, 5);
}

function syncStepToUrl() {
    if (!taskId) return;
    const url = new URL(window.location.href);
    url.searchParams.set('step', String(currentStep + 1));
    window.history.replaceState(null, '', url);
}

function highlightNav() {
    document.querySelectorAll('.nav-link').forEach(a => a.classList.remove('active'));
    const nav = document.getElementById('nav-taskList');
    if (nav) nav.classList.add('active');
}

// ── 步骤导航 ──
function updateNav() {
    document.querySelectorAll('.step-item').forEach((el, i) => {
        el.classList.remove('active', 'done');
        if (i === currentStep) el.classList.add('active');
        else if (i < currentStep) el.classList.add('done');
    });

    const progressEl = document.getElementById('stepProgress');
    if (progressEl) {
        progressEl.textContent = `第 ${currentStep + 1} / 6 步`;
    }

    document.getElementById('prevBtn').disabled = currentStep === 0;
    const nextBtn = document.getElementById('nextBtn');
    if (currentStep === 5) {
        nextBtn.style.display = 'none';
    } else {
        nextBtn.style.display = 'inline-block';
        nextBtn.innerHTML = currentStep === 0 && !taskId ? '开始生成 <i class="bi bi-chevron-right"></i>' : '下一步 <i class="bi bi-chevron-right"></i>';
    }
}

function checkGate(loaded, list, emptyMsg) {
    if (!loaded) return '数据加载中，请稍候';
    return list.length === 0 ? emptyMsg : null;
}

function validateStep(step) {
    switch (step) {
        case 0: return !taskId ? '请先上传课件并创建任务' : null;
        case 1:
            return !taskId ? '请先完成上一步' : checkGate(sectionsLoaded, sections, '请先生成章节');
        case 2:
            return checkGate(sectionsLoaded, sections, '请先完成"生成章节"步骤')
                || checkGate(slidesLoaded, slides, '请先生成幻灯片');
        case 3:
            return checkGate(slidesLoaded, slides, '请先完成"生成幻灯片"步骤')
                || checkGate(scriptsLoaded, scripts, '请先生成讲解稿');
        case 4:
            return checkGate(scriptsLoaded, scripts, '请先完成"生成讲解稿"步骤')
                || checkGate(ttsLoaded, ttsList, '请先生成音频');
        case 5:
            return checkGate(ttsLoaded, ttsList, '请先完成"生成音频"步骤');
        default: return null;
    }
}

function prevStep() {
    if (currentStep > 0) { currentStep--; renderStep(); updateNav(); syncStepToUrl(); }
}

function nextStep() {
    if (currentStep >= 5) return;
    const err = validateStep(currentStep);
    if (err) { toastWarning(err); return; }
    currentStep++;
    renderStep();
    updateNav();
    syncStepToUrl();
}

function jumpToStep(step) {
    if (step === currentStep) return;
    if (step > currentStep) {
        for (let i = currentStep; i < step; i++) {
            const err = validateStep(i);
            if (err) { toastWarning(`无法跳转：${err}`); return; }
        }
    }
    currentStep = step;
    renderStep();
    updateNav();
    syncStepToUrl();
}

function renderStep() {
    const container = document.getElementById('stepContent');
    switch (currentStep) {
        case 0: renderStep1(container); break;
        case 1: renderStep2(container); break;
        case 2: renderStep3(container); break;
        case 3: renderStep4(container); break;
        case 4: renderStep5(container); break;
        case 5: renderStep6(container); break;
    }
}

// ══════════════════════════════════════════════
//  Step 1: 选择课件
// ══════════════════════════════════════════════
let selectedFile = null;
let previewContent = '';

function renderStep1(container) {
    if (taskId) {
        fetch(`/api/task/detail/${taskId}`)
            .then(r => r.json())
            .then(res => {
                if (res.code === 200 && res.data) {
                    taskName = res.data.taskName || '';
                    previewContent = (res.data.content || '').substring(0, 200);
                    renderStep1HTML(container);
                }
            })
            .catch(() => renderStep1HTML(container));
    } else {
        renderStep1HTML(container);
    }
}

function renderStep1HTML(container) {
    const loaded = taskId ? `<div class="task-loaded-tip mb-3">
        <span class="badge bg-info">已加载任务：${escapeHtml(taskName)}</span>
        <p class="hint mt-1">当前为已有任务，无需重复上传课件</p>
    </div>` : '';

    const uploadArea = taskId ? '' : `
        <div class="upload-zone" id="uploadZone" onclick="document.getElementById('fileInput').click()"
             ondragover="event.preventDefault(); this.classList.add('dragover')"
             ondragleave="this.classList.remove('dragover')"
             ondrop="handleDrop(event)">
            <div class="upload-icon"><i class="bi bi-cloud-upload"></i></div>
            <div class="upload-text">点击或拖拽上传 <em>Markdown 文件</em></div>
            <div class="form-text">支持 .md 格式，最大 5MB</div>
            <input type="file" id="fileInput" accept=".md" style="display:none" onchange="handleFileSelect(event)">
        </div>
        <div id="fileInfo" class="file-info" style="display:none"></div>
    `;

    const filePreview = previewContent ? `
        <div class="preview-block">
            <h6>预览内容（前 200 字）：</h6>
            <div class="preview-content">${escapeHtml(previewContent)}</div>
        </div>
    ` : '';

    const submitBtn = taskId ? '' : `
        <button class="btn btn-primary mt-3" id="submitBtn" onclick="submitStep1()" disabled>
            <i class="bi bi-check-circle"></i> 创建任务
        </button>
    `;

    container.innerHTML = `
        <h3><i class="bi bi-file-earmark-text"></i> 选择课件（Markdown）</h3>
        <p class="step-desc-text">请上传一份结构清晰的 Markdown 格式课件文件（.md）</p>
        ${loaded}
        ${uploadArea}
        ${filePreview}
        <div class="mt-3">
            <label class="form-label fw-semibold">任务名称</label>
            <div class="d-flex gap-2 align-items-center">
                <input type="text" class="form-control" id="taskNameInput" placeholder="请输入任务名称（例如：Vue 3 响应式原理详解）"
                       maxlength="50" value="${escapeHtml(taskName)}">
                ${taskId ? '<button class="btn btn-outline-primary text-nowrap" id="renameBtn" style="display:none" onclick="renameTask()">保存新名称</button>' : ''}
            </div>
            <div class="form-text">${taskId ? '修改名称后点击「保存新名称」生效' : '建议用简洁、有辨识度的名称'}</div>
        </div>
        ${submitBtn}
    `;

    document.getElementById('taskNameInput').addEventListener('input', () => {
        if (!taskId) { checkStep1(); return; }
        const renameBtn = document.getElementById('renameBtn');
        if (renameBtn) {
            const newName = document.getElementById('taskNameInput').value.trim();
            renameBtn.style.display = (newName && newName !== taskName) ? '' : 'none';
        }
    });
}

async function renameTask() {
    const name = document.getElementById('taskNameInput').value.trim();
    if (!name) { toastWarning('任务名称不能为空'); return; }
    try {
        await apiFetch('/api/task/rename', {
            method: 'PUT',
            body: JSON.stringify({ task_id: taskId, task_name: name }),
        });
        taskName = name;
        toastSuccess('任务已重命名');
        const renameBtn = document.getElementById('renameBtn');
        if (renameBtn) renameBtn.style.display = 'none';
    } catch (err) {
        toastError('重命名失败：' + err.message);
    }
}

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file) processFile(file);
}

function handleDrop(event) {
    event.preventDefault();
    document.getElementById('uploadZone').classList.remove('dragover');
    const file = event.dataTransfer.files[0];
    if (file) processFile(file);
}

function processFile(file) {
    if (!file.name.toLowerCase().endsWith('.md')) {
        toastWarning('不支持的文件类型，请上传 .md 文件');
        return;
    }
    if (file.size > 5 * 1024 * 1024) {
        toastWarning('文件大小不能超过 5MB');
        return;
    }
    selectedFile = file;
    file.arrayBuffer().then(buf => {
        let text;
        try {
            text = new TextDecoder('utf-8', { fatal: true }).decode(buf);
        } catch (e) {
            selectedFile = null;
            toastError('文件不是 UTF-8 编码，请转换编码后重新上传');
            return;
        }
        previewContent = (text || '').substring(0, 200);
        document.getElementById('fileInfo').style.display = 'flex';
        document.getElementById('fileInfo').innerHTML = `
            <span class="badge bg-success">${escapeHtml(file.name)}</span>
            <a href="#" class="text-decoration-none" onclick="resetFile(); return false;">重新选择</a>
        `;
        checkStep1();
    });
}

function resetFile() {
    selectedFile = null;
    previewContent = '';
    document.getElementById('fileInfo').style.display = 'none';
    document.getElementById('fileInput').value = '';
    checkStep1();
}

function checkStep1() {
    const name = (document.getElementById('taskNameInput')?.value || '').trim();
    const btn = document.getElementById('submitBtn');
    if (btn) btn.disabled = !(selectedFile && name);
}

async function submitStep1() {
    const name = document.getElementById('taskNameInput').value.trim();
    if (!name || !selectedFile) return;

    const btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 上传中...';

    try {
        const formData = new FormData();
        formData.append('file', selectedFile);
        formData.append('taskName', name);

        const json = await apiFetch('/api/task/upload', { method: 'POST', body: formData });
        taskId = json.data;
        taskName = name;
        window.history.replaceState(null, '', `/taskCreate?taskId=${taskId}`);
        nextStep();
    } catch (err) {
        toastError('创建失败：' + err.message);
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-check-circle"></i> 创建任务';
    }
}

// ══════════════════════════════════════════════
//  通用工具函数
// ══════════════════════════════════════════════

function showEditModal(title, bodyHtml, onSave) {
    const modal = document.createElement('div');
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `
        <div class="modal-dialog modal-lg modal-dialog-scrollable">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">${title}</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">${bodyHtml}</div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
                    <button type="button" class="btn btn-primary" id="editModalSaveBtn">保存</button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    const bsModal = new bootstrap.Modal(modal);

    modal.querySelector('#editModalSaveBtn').addEventListener('click', async () => {
        const btn = modal.querySelector('#editModalSaveBtn');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 保存中...';
        try {
            await onSave();
            bsModal.hide();
        } catch (err) {
            toastError('保存失败：' + err.message);
        } finally {
            btn.disabled = false;
            btn.innerHTML = '保存';
        }
    });

    modal.addEventListener('hidden.bs.modal', () => modal.remove());
    bsModal.show();
}