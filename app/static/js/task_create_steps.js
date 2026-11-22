/* task_create_steps.js — 6 步向导的第 2-6 步（分章/幻灯片/讲解稿/音频/导出） */

/**
 * 进入某步骤时恢复仍在后台运行的作业：接管按钮并继续轮询。
 * @param {string} step 作业类型
 * @param {HTMLElement|null} btn 该步骤的触发按钮
 * @param {Function} onDone 作业成功后的刷新回调（如 loadSections）
 */
async function resumeRunningJob(step, btn, onDone) {
    if (!taskId || !btn) return;
    let d;
    try {
        const res = await apiFetch(`/api/task/job/${step}/${taskId}`);
        d = res.data || {};
    } catch (e) {
        return;
    }
    if (d.state !== 'running') return;

    const label = btn.innerHTML;
    const job = await pollJobUntilDone(step, taskId, btn);
    if (document.body.contains(btn)) {
        btn.disabled = false;
        btn.innerHTML = label;
    }
    if (job.state === 'success') {
        toastSuccess(job.result || '后台任务已完成');
        if (onDone) onDone();
    }
}

// ══════════════════════════════════════════════
//  Step 2: 生成章节
// ══════════════════════════════════════════════
let sections = [];
let sectionsLoaded = false;

function renderStep2(container) {
    container.innerHTML = `
        <h3><i class="bi bi-book"></i> 生成章节</h3>
        <p class="step-desc-text">AI 将根据课件内容智能划分逻辑章节</p>
        <button class="btn btn-primary" id="splitBtn" onclick="splitSections()">
            <i class="bi bi-diagram-3"></i> 开始划分章节
        </button>
        <div id="sectionList" class="mt-3"></div>
    `;
    loadSections();
    resumeRunningJob('split', document.getElementById('splitBtn'), loadSections);
}

function loadSections() {
    if (!taskId) return;
    const box = document.getElementById('sectionList');
    if (box) box.innerHTML = renderAreaLoading();
    apiFetch(`/api/section/by-task-id?taskId=${taskId}`)
        .then(res => {
            sectionsLoaded = true;
            sections = res.data || [];
            renderSectionList();
        })
        .catch(err => {
            sectionsLoaded = false;
            if (box) box.innerHTML = renderAreaError('章节列表加载失败：' + err.message, 'loadSections');
            else toastError('加载章节列表失败：' + err.message);
        });
}

function renderSectionList() {
    const container = document.getElementById('sectionList');
    if (!sections.length) {
        container.innerHTML = '<div class="empty-state">还未生成章节，请点击上方按钮开始生成</div>';
        return;
    }
    document.getElementById('splitBtn').innerHTML = '<i class="bi bi-arrow-repeat"></i> 重新划分章节';

    container.innerHTML = `
        <h6 class="mb-3">已划分 ${sections.length} 个章节：</h6>
        ${sections.map((s, i) => `
            <div class="card item-card">
                <div class="card-header">
                    <span class="fw-semibold">第 ${i+1} 章：${escapeHtml(s.title)}</span>
                    <div class="item-actions">
                        <button class="btn btn-sm btn-outline-secondary" onclick="moveSection(${s.sectionOrder}, 'up')" title="上移" ${i === 0 ? 'disabled' : ''}>
                            <i class="bi bi-arrow-up"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="moveSection(${s.sectionOrder}, 'down')" title="下移" ${i === sections.length - 1 ? 'disabled' : ''}>
                            <i class="bi bi-arrow-down"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="editSection(${i})">
                            <i class="bi bi-pencil"></i> 编辑
                        </button>
                        <button class="btn btn-sm btn-outline-primary" onclick="regenSection(${s.sectionOrder})" id="regenSec${s.sectionOrder}">
                            <i class="bi bi-arrow-repeat"></i> 重生成
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteSection(${i})">
                            <i class="bi bi-trash"></i> 删除
                        </button>
                    </div>
                </div>
                <div class="card-body">
                    ${(s.content || '').length > 200
                        ? `<p class="item-content small sec-preview-${i}">${escapeHtml((s.content || '').substring(0, 200))}...</p>
                           <p class="item-content small d-none sec-full-${i}">${escapeHtml(s.content)}</p>
                           <a href="#" class="small" onclick="toggleSectionContent(${i}, this); return false;">展开全文</a>`
                        : `<p class="item-content small">${escapeHtml(s.content || '')}</p>`}
                </div>
            </div>
        `).join('')}
    `;
}

function toggleSectionContent(index, link) {
    const preview = document.querySelector(`.sec-preview-${index}`);
    const full = document.querySelector(`.sec-full-${index}`);
    if (!preview || !full) return;
    const expanding = full.classList.contains('d-none');
    full.classList.toggle('d-none', !expanding);
    preview.classList.toggle('d-none', expanding);
    link.textContent = expanding ? '收起' : '展开全文';
}

function splitSections() {
    if (!hasUsableKey()) { toastWarning('请先配置 SK'); return; }
    if (sections.length) {
        const downstream = hasDownstream()
            ? '<div class="alert alert-warning py-2 mt-2 mb-0"><i class="bi bi-exclamation-triangle me-1"></i>将同时清除已生成的幻灯片、讲解稿与音频，需逐步重新生成。</div>'
            : '';
        confirmModal('重新划分章节', `已存在 ${sections.length} 个章节，重新划分将<b class="text-danger">覆盖现有章节内容</b>。${downstream}是否继续？`, doSplitSections);
    } else {
        doSplitSections();
    }
}

function hasDownstream() {
    return slides.length || scripts.length || ttsList.length;
}

function downstreamWarnHtml() {
    return hasDownstream()
        ? '<div class="alert alert-warning py-2 mt-2 mb-0"><i class="bi bi-exclamation-triangle me-1"></i>章节结构变更将同时清除已生成的幻灯片/讲解稿/音频。</div>'
        : '';
}

function deleteSection(index) {
    const s = sections[index];
    confirmModal('删除章节', `
        确定删除「${escapeHtml(s.title)}」？后续章节序号将自动前移。
        ${downstreamWarnHtml()}
    `, async () => {
        try {
            await apiFetch(`/api/section/delete?taskId=${taskId}&sectionOrder=${s.sectionOrder}`, { method: 'DELETE' });
            toastSuccess('章节已删除');
            loadSections();
        } catch (err) {
            toastError('删除失败：' + err.message);
        }
    });
}

async function moveSection(order, direction) {
    try {
        await apiFetch(`/api/section/move?taskId=${taskId}&sectionOrder=${order}&direction=${direction}`, { method: 'POST' });
        loadSections();
    } catch (err) {
        toastError('移动失败：' + err.message);
    }
}

async function doSplitSections() {
    const btn = document.getElementById('splitBtn');
    btn.disabled = true;
    try {
        await apiFetch(`/api/section/split?taskId=${taskId}`, { method: 'POST' });
        const job = await pollJobUntilDone('split', taskId, btn);
        if (job.state === 'success') toastSuccess(job.result);
        loadSections();
    } catch (err) {
        toastError('划分失败：' + err.message);
        btn.disabled = false;
    } finally {
        if (!btn.dataset.jobTotal) btn.innerHTML = '<i class="bi bi-diagram-3"></i> 重新划分章节';
    }
}

function editSection(index) {
    const s = sections[index];
    showEditModal('编辑章节', `
        <div class="mb-3">
            <label class="form-label">标题</label>
            <input type="text" class="form-control" id="editSectionTitle" value="${escapeHtml(s.title || '')}">
        </div>
        <div class="mb-3">
            <label class="form-label">内容</label>
            <textarea class="form-control" id="editSectionContent" rows="8">${escapeHtml(s.content || '')}</textarea>
        </div>
    `, async () => {
        const title = document.getElementById('editSectionTitle').value.trim();
        const content = document.getElementById('editSectionContent').value.trim();
        if (!title || !content) { toastWarning('标题和内容不能为空'); return; }
        await apiFetch('/api/section/update', {
            method: 'PUT',
            body: JSON.stringify({ task_id: taskId, section_order: s.sectionOrder, title, content }),
        });
        toastSuccess('保存成功');
        loadSections();
    });
}

async function regenSection(order) {
    if (!hasUsableKey()) { toastWarning('请先配置 SK'); return; }
    const btn = document.getElementById(`regenSec${order}`);
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    try {
        await apiFetch(`/api/section/regenerate?taskId=${taskId}&sectionOrder=${order}`, { method: 'POST' });
        toastSuccess('本章已重新生成');
        loadSections();
    } catch (err) {
        toastError('重生成失败：' + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> 重生成';
    }
}

// ══════════════════════════════════════════════
//  Step 3: 生成幻灯片
// ══════════════════════════════════════════════
let slides = [];
let slidesLoaded = false;
let slideCarouselInstance = null;

// 预览缩放：幻灯片按 1920×1080 渲染后等比缩放适配容器，slideZoom 为“适配宽度”基准上的倍率
let slideZoom = 1;
const SLIDE_ZOOM_MIN = 0.5, SLIDE_ZOOM_MAX = 4, SLIDE_ZOOM_STEP = 0.25;

function applySlideZoom() {
    const host = document.getElementById('slideCarousel');
    if (!host) return;
    const pct = document.getElementById('slideZoomPct');
    if (pct) pct.textContent = Math.round(slideZoom * 100) + '%';
    const activeWrap = host.querySelector('.carousel-item.active .slide-iframe-wrapper');
    if (!activeWrap) return;
    // 用轮播容器宽度 + 当前视口高度计算“适配缩放”，避免内部滚动条导致的宽度抖动
    const z = Math.min(host.clientWidth / 1920, activeWrap.clientHeight / 1080) * slideZoom;
    host.querySelectorAll('.slide-canvas').forEach(c => {
        c.style.width = (1920 * z) + 'px';
        c.style.height = (1080 * z) + 'px';
        const f = c.querySelector('.slide-iframe');
        if (f) f.style.transform = 'scale(' + z + ')';
    });
}

function zoomSlide(delta) {
    slideZoom = Math.min(SLIDE_ZOOM_MAX, Math.max(SLIDE_ZOOM_MIN, Math.round((slideZoom + delta) * 100) / 100));
    applySlideZoom();
}

function resetSlideZoom() {
    slideZoom = 1;
    applySlideZoom();
}

window.addEventListener('resize', applySlideZoom);

function renderStep3(container) {
    container.innerHTML = `
        <h3><i class="bi bi-images"></i> 生成幻灯片（HTML）</h3>
        <p class="step-desc-text">为每个章节生成精美、适配大屏的 HTML 页面</p>
        <button class="btn btn-primary" id="genSlideBtn" onclick="genSlides()">
            <i class="bi bi-play-circle"></i> 开始生成幻灯片
        </button>
        <div id="slideArea" class="mt-3"></div>
        <div id="pptxArea" class="mt-3" style="display:none"></div>
    `;
    loadSlides();
    resumeRunningJob('slides', document.getElementById('genSlideBtn'), loadSlides);
}

function loadSlides() {
    if (!taskId) return;
    const box = document.getElementById('slideArea');
    if (box) box.innerHTML = renderAreaLoading();
    apiFetch(`/api/slide/by-task-id?taskId=${taskId}`)
        .then(res => {
            slidesLoaded = true;
            slides = res.data || [];
            renderSlideArea();
        })
        .catch(err => {
            slidesLoaded = false;
            if (box) box.innerHTML = renderAreaError('幻灯片列表加载失败：' + err.message, 'loadSlides');
            else toastError('加载幻灯片列表失败：' + err.message);
        });
}

function renderSlideArea() {
    const container = document.getElementById('slideArea');
    if (!slides.length) {
        container.innerHTML = '<div class="empty-state">还未生成幻灯片，请点击上方按钮开始生成</div>';
        return;
    }
    document.getElementById('genSlideBtn').innerHTML = '<i class="bi bi-arrow-repeat"></i> 重新生成幻灯片';

    let indicators = slides.map((_, i) =>
        `<button type="button" data-bs-target="#slideCarousel" data-bs-slide-to="${i}" aria-label="跳转到第 ${i+1} 页" ${i === 0 ? 'class="active"' : ''}></button>`
    ).join('');

    let items = slides.map((s, i) => {
        const failed = s.status === 'failed';
        const inner = failed ? `
            <div class="slide-iframe-wrapper d-flex align-items-center justify-content-center">
                <div class="text-center text-muted">
                    <div class="mb-2"><i class="bi bi-x-octagon-fill text-danger fs-2"></i></div>
                    <div>第 ${i+1} 张幻灯片生成失败，请重试</div>
                </div>
            </div>
            <div class="slide-actions-overlay">
                <button class="btn btn-sm btn-outline-primary" onclick="regenSlide(${s.slideOrder})" id="regenSl${s.slideOrder}">
                    <i class="bi bi-arrow-clockwise"></i> 重试
                </button>
            </div>` : `
            <div class="slide-iframe-wrapper">
                <div class="slide-canvas">
                    <iframe src="/api/slide/html?taskId=${taskId}&slideOrder=${s.slideOrder}"
                            class="slide-iframe" title="幻灯片第${i+1}页"
                            sandbox="allow-scripts"></iframe>
                </div>
            </div>
            <div class="slide-actions-overlay">
                <button class="btn btn-sm btn-light" onclick="viewSlide(${s.slideOrder})">
                    <i class="bi bi-box-arrow-up-right"></i> 预览
                </button>
                <button class="btn btn-sm btn-outline-secondary" onclick="editSlide(${s.slideOrder})">
                    <i class="bi bi-pencil"></i> 编辑
                </button>
                <button class="btn btn-sm btn-outline-primary" onclick="regenSlide(${s.slideOrder})" id="regenSl${s.slideOrder}">
                    <i class="bi bi-arrow-repeat"></i> 重生成
                </button>
            </div>`;
        return `<div class="carousel-item ${i === 0 ? 'active' : ''}">${inner}</div>`;
    }).join('');

    container.innerHTML = `
        <h6 class="mb-3">已生成 ${slides.length} 张幻灯片：</h6>
        <div id="slideCarousel" class="carousel slide slide-carousel" data-bs-ride="false">
            <div class="carousel-indicators">${indicators}</div>
            <div class="carousel-inner">${items}</div>
            <button class="carousel-control-prev" type="button" data-bs-target="#slideCarousel" data-bs-slide="prev" aria-label="上一张幻灯片">
                <span class="carousel-control-prev-icon"></span>
            </button>
            <button class="carousel-control-next" type="button" data-bs-target="#slideCarousel" data-bs-slide="next" aria-label="下一张幻灯片">
                <span class="carousel-control-next-icon"></span>
            </button>
            <div class="slide-zoom-bar" role="group" aria-label="预览缩放控制">
                <button type="button" class="btn-zoom" onclick="zoomSlide(-${SLIDE_ZOOM_STEP})" aria-label="缩小"><i class="bi bi-dash-lg"></i></button>
                <span class="zoom-pct" id="slideZoomPct">100%</span>
                <button type="button" class="btn-zoom" onclick="zoomSlide(${SLIDE_ZOOM_STEP})" aria-label="放大"><i class="bi bi-plus-lg"></i></button>
                <button type="button" class="btn-zoom" onclick="resetSlideZoom()" aria-label="重置为适合宽度"><i class="bi bi-arrows-angle-contract"></i></button>
            </div>
        </div>
    `;

    // 销毁旧实例重建
    if (slideCarouselInstance) slideCarouselInstance.dispose();
    slideCarouselInstance = new bootstrap.Carousel(document.getElementById('slideCarousel'), { interval: false });
    applySlideZoom();

    checkPptxStatus();
}

function genSlides() {
    if (!hasUsableKey()) { toastWarning('请先配置 SK'); return; }
    if (slides.length) {
        confirmModal('重新生成幻灯片', `已存在 ${slides.length} 张幻灯片，重新生成将<b class="text-danger">覆盖全部幻灯片</b>，是否继续？`, doGenSlides);
    } else {
        doGenSlides();
    }
}

async function doGenSlides() {
    const btn = document.getElementById('genSlideBtn');
    btn.disabled = true;
    try {
        await apiFetch(`/api/slide/generate-all?taskId=${taskId}`, { method: 'POST' });
        const job = await pollJobUntilDone('slides', taskId, btn);
        if (job.state === 'success') toastSuccess(job.result);
        loadSlides();
    } catch (err) {
        toastError('生成失败：' + err.message);
        btn.disabled = false;
    } finally {
        if (!btn.dataset.jobTotal) btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> 重新生成幻灯片';
    }
}

function viewSlide(order) {
    window.open(`/api/slide/html?taskId=${taskId}&slideOrder=${order}`, '_blank');
}

function editSlide(order) {
    apiFetch(`/api/slide/content?taskId=${taskId}&slideOrder=${order}`)
        .then(res => {
            showEditModal('编辑幻灯片 HTML', `
                <div class="mb-3">
                    <label class="form-label">HTML 内容</label>
                    <textarea class="form-control modal-textarea" id="editSlideContent" rows="15">${escapeHtml(res.data || '')}</textarea>
                    <div class="form-text">HTML 必须是完整、可独立运行的片段</div>
                </div>
            `, async () => {
                const html = document.getElementById('editSlideContent').value.trim();
                if (!html) { toastWarning('HTML 内容不能为空'); return; }
                await apiFetch('/api/slide/update', {
                    method: 'PUT',
                    body: JSON.stringify({ task_id: taskId, slide_order: order, content: html }),
                });
                toastSuccess('保存成功');
                loadSlides();
            });
        })
        .catch(err => toastError('加载幻灯片内容失败：' + err.message));
}

async function regenSlide(order) {
    if (!hasUsableKey()) { toastWarning('请先配置 SK'); return; }
    const btn = document.getElementById(`regenSl${order}`);
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    try {
        await apiFetch(`/api/slide/regenerate?taskId=${taskId}&slideOrder=${order}`, { method: 'POST' });
        toastSuccess('重生成成功');
        loadSlides();
    } catch (err) {
        toastError('重生成失败：' + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> 重生成';
    }
}

function checkPptxStatus() {
    if (!taskId) return;
    const area = document.getElementById('pptxArea');
    if (!area) return;
    area.style.display = 'block';
    area.innerHTML = renderAreaLoading();
    apiFetch(`/api/task/has-pptx/${taskId}`)
        .then(res => renderPptxArea(res.data || {}))
        .catch(err => {
            area.innerHTML = renderAreaError('PPTX 状态检查失败：' + err.message, 'checkPptxStatus');
        });
}

let pptxExists = false;

function renderPptxArea(info) {
    const area = document.getElementById('pptxArea');
    pptxExists = !!info.exists;
    area.style.display = 'block';
    if (info.exists) {
        const staleTip = info.stale
            ? `<span class="badge bg-warning text-dark"><i class="bi bi-exclamation-triangle me-1"></i>课件已变更，建议重新导出</span>`
            : '';
        area.innerHTML = `
            <div class="d-flex align-items-center gap-3 flex-wrap">
                <span class="fw-semibold">PowerPoint 文件：</span>
                <a href="/api/task/download-pptx/${taskId}" class="btn btn-success btn-sm" download>
                    <i class="bi bi-download"></i> 下载 presentation.pptx
                </a>
                ${staleTip}
                ${info.stale ? `
                <button class="btn btn-outline-primary btn-sm" onclick="exportPptx()" id="pptxBtn">
                    <i class="bi bi-arrow-repeat"></i> 重新导出
                </button>` : ''}
            </div>
        `;
    } else {
        area.innerHTML = `
            <button class="btn btn-outline-primary" onclick="exportPptx()" id="pptxBtn">
                <i class="bi bi-file-ppt"></i> 导出为 PPTX
            </button>
        `;
        resumeRunningJob('pptx', document.getElementById('pptxBtn'), checkPptxStatus);
    }
}

function exportPptx() {
    if (pptxExists) {
        confirmModal('重新导出 PPTX', '将<b class="text-danger">覆盖现有 presentation.pptx</b>，是否继续？', doExportPptx);
    } else {
        doExportPptx();
    }
}

async function doExportPptx() {
    const btn = document.getElementById('pptxBtn');
    if (btn) btn.disabled = true;
    try {
        await apiFetch(`/api/task/export-pptx/${taskId}`, { method: 'POST' });
        const job = await pollJobUntilDone('pptx', taskId, btn);
        if (job.state === 'success') toastSuccess('PPTX 导出完成！');
    } catch (err) {
        toastError('导出失败：' + err.message);
    } finally {
        checkPptxStatus();
    }
}

// ══════════════════════════════════════════════
//  Step 4: 生成讲解稿
// ══════════════════════════════════════════════
let scripts = [];
let scriptsLoaded = false;

function renderStep4(container) {
    container.innerHTML = `
        <h3><i class="bi bi-mic"></i> 生成讲解稿</h3>
        <p class="step-desc-text">为每章生成口语化、自然流畅的语音讲解脚本</p>
        <button class="btn btn-primary" id="genScriptBtn" onclick="genScripts()">
            <i class="bi bi-play-circle"></i> 开始生成讲解稿
        </button>
        <div id="scriptList" class="mt-3"></div>
    `;
    loadScripts();
    resumeRunningJob('scripts', document.getElementById('genScriptBtn'), loadScripts);
}

function loadScripts() {
    if (!taskId) return;
    const box = document.getElementById('scriptList');
    if (box) box.innerHTML = renderAreaLoading();
    apiFetch(`/api/script/by-task-id?taskId=${taskId}`)
        .then(res => {
            scriptsLoaded = true;
            scripts = res.data || [];
            renderScriptList();
        })
        .catch(err => {
            scriptsLoaded = false;
            if (box) box.innerHTML = renderAreaError('讲解稿列表加载失败：' + err.message, 'loadScripts');
            else toastError('加载讲解稿列表失败：' + err.message);
        });
}

function renderScriptList() {
    const container = document.getElementById('scriptList');
    if (!scripts.length) {
        container.innerHTML = '<div class="empty-state">还未生成讲解稿，请点击上方按钮开始生成</div>';
        return;
    }
    document.getElementById('genScriptBtn').innerHTML = '<i class="bi bi-arrow-repeat"></i> 重新生成讲解稿';

    container.innerHTML = `
        <h6 class="mb-3">已生成 ${scripts.length} 篇讲解稿：</h6>
        ${scripts.map((s, i) => {
            const failed = s.status === 'failed';
            const len = (s.content || '').length;
            return `
            <div class="card item-card${failed ? ' border-danger' : ''}">
                <div class="card-header">
                    <span class="fw-semibold">第 ${i+1} 篇：${escapeHtml(s.title || '无标题')}
                        ${failed ? '<span class="badge bg-danger ms-2">生成失败</span>' : ''}</span>
                    <div class="item-actions">
                        <button class="btn btn-sm btn-outline-secondary" onclick="editScript(${s.scriptOrder})">
                            <i class="bi bi-pencil"></i> 编辑
                        </button>
                        <button class="btn btn-sm btn-outline-primary" onclick="regenScript(${s.scriptOrder})" id="regenSc${s.scriptOrder}">
                            <i class="bi ${failed ? 'bi-arrow-clockwise' : 'bi-arrow-repeat'}"></i> ${failed ? '重试' : '重生成'}
                        </button>
                    </div>
                </div>
                <div class="card-body">
                    ${failed
                        ? '<p class="item-content text-danger small mb-0"><i class="bi bi-x-circle me-1"></i>本篇讲解稿生成失败，请点击「重试」重新生成</p>'
                        : `<p class="item-content">${escapeHtml(s.content || '')}</p>
                           <p class="word-count ${len > 350 ? 'over-limit' : ''}">${len} 字</p>`}
                </div>
            </div>`;
        }).join('')}
    `;
}

async function genScripts() {
    if (!hasUsableKey()) { toastWarning('请先配置 SK'); return; }
    if (scripts.length) {
        confirmModal('重新生成讲解稿', `已存在 ${scripts.length} 篇讲解稿，重新生成将<b class="text-danger">覆盖全部讲解稿</b>，是否继续？`, doGenScripts);
    } else {
        doGenScripts();
    }
}

async function doGenScripts() {
    const btn = document.getElementById('genScriptBtn');
    btn.disabled = true;
    try {
        await apiFetch(`/api/script/generate-all?taskId=${taskId}`, { method: 'POST' });
        const job = await pollJobUntilDone('scripts', taskId, btn);
        if (job.state === 'success') toastSuccess(job.result);
        loadScripts();
    } catch (err) {
        toastError('生成失败：' + err.message);
        btn.disabled = false;
    } finally {
        if (!btn.dataset.jobTotal) btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> 重新生成讲解稿';
    }
}

function editScript(order) {
    const s = scripts.find(x => x.scriptOrder === order);
    if (!s) return;
    showEditModal('编辑讲解稿', `
        <div class="mb-3">
            <label class="form-label">内容</label>
            <textarea class="form-control" id="editScriptContent" rows="10">${escapeHtml(s.content || '')}</textarea>
        </div>
    `, async () => {
        const content = document.getElementById('editScriptContent').value.trim();
        if (!content) { toastWarning('内容不能为空'); return; }
        await apiFetch('/api/script/update', {
            method: 'PUT',
            body: JSON.stringify({ task_id: taskId, script_order: order, content }),
        });
        toastSuccess('保存成功');
        loadScripts();
    });
}

async function regenScript(order) {
    if (!hasUsableKey()) { toastWarning('请先配置 SK'); return; }
    const btn = document.getElementById(`regenSc${order}`);
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    try {
        await apiFetch(`/api/script/regenerate?taskId=${taskId}&scriptOrder=${order}`, { method: 'POST' });
        toastSuccess('重生成成功');
        loadScripts();
    } catch (err) {
        toastError('重生成失败：' + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> 重生成';
    }
}

// ══════════════════════════════════════════════
//  Step 5: 生成音频
// ══════════════════════════════════════════════
let ttsList = [];
let ttsLoaded = false;

function renderStep5(container) {
    const voices = Array.isArray(window.TTS_VOICES) ? window.TTS_VOICES : [];
    const voiceOptions = voices.map(v => `<option value="${v}">${v}</option>`).join('');
    container.innerHTML = `
        <h3><i class="bi bi-volume-up"></i> 生成音频（TTS）</h3>
        <p class="step-desc-text">将每篇讲解稿合成为高质量语音 MP3</p>
        ${voices.length ? `
        <div class="d-flex align-items-center gap-2 mb-3 flex-wrap">
            <label class="form-label mb-0 fw-semibold">音色：</label>
            <select id="ttsVoiceSelect" class="form-select form-select-sm w-auto" onchange="saveTtsVoice(this.value)">
                <option value="">加载中…</option>
            </select>
            <span class="form-text mb-0">重新生成音频时生效</span>
        </div>` : ''}
        <button class="btn btn-primary" id="genTtsBtn" onclick="genTTS()">
            <i class="bi bi-play-circle"></i> 开始生成音频
        </button>
        <div id="ttsListContainer" class="mt-3"></div>
    `;
    loadTTS();
    initVoiceSelect();
    resumeRunningJob('tts', document.getElementById('genTtsBtn'), loadTTS);
}

function initVoiceSelect() {
    if (!taskId) return;
    const sel = document.getElementById('ttsVoiceSelect');
    if (!sel) return;
    apiFetch(`/api/task/detail/${taskId}`)
        .then(res => {
            const current = (res.data && res.data.ttsVoice) || window.TTS_VOICE_DEFAULT || '';
            sel.innerHTML = (window.TTS_VOICES || []).map(v =>
                `<option value="${v}" ${v === current ? 'selected' : ''}>${v}</option>`).join('');
        })
        .catch(() => { sel.innerHTML = '<option value="">默认音色</option>'; });
}

async function saveTtsVoice(voice) {
    try {
        await apiFetch('/api/task/voice', {
            method: 'PUT',
            body: JSON.stringify({ task_id: taskId, voice }),
        });
        toastSuccess(`音色已保存为 ${voice}，重新生成音频时生效`);
    } catch (err) {
        toastError('音色保存失败：' + err.message);
    }
}

function editAndResynthesize(order) {
    if (!hasUsableKey()) { toastWarning('请先配置 SK'); return; }
    const t = ttsList.find(x => x.ttsOrder === order);
    if (!t) return;
    showEditModal('编辑讲解稿并重合成', `
        <div class="mb-3">
            <label class="form-label">讲解稿内容</label>
            <textarea class="form-control" id="editResynthContent" rows="10">${escapeHtml(t.script || '')}</textarea>
            <div class="form-text">保存后将自动用当前音色重新合成该条音频</div>
        </div>
    `, async () => {
        const content = document.getElementById('editResynthContent').value.trim();
        if (!content) { toastWarning('内容不能为空'); return; }
        await apiFetch('/api/script/update', {
            method: 'PUT',
            body: JSON.stringify({ task_id: taskId, script_order: order, content }),
        });
        const s = scripts.find(x => x.scriptOrder === order);
        if (s) s.content = content;
        t.script = content;
        await apiFetch(`/api/tts/regenerate?taskId=${taskId}&ttsOrder=${order}`, { method: 'POST' });
        toastSuccess('讲解稿已更新并重新合成');
        loadScripts();
        loadTTS();
    });
}

function loadTTS() {
    if (!taskId) return;
    const box = document.getElementById('ttsListContainer');
    if (box) box.innerHTML = renderAreaLoading();
    apiFetch(`/api/tts/by-task-id?taskId=${taskId}`)
        .then(res => {
            ttsLoaded = true;
            ttsList = res.data || [];
            renderTTSList();
        })
        .catch(err => {
            ttsLoaded = false;
            if (box) box.innerHTML = renderAreaError('音频列表加载失败：' + err.message, 'loadTTS');
            else toastError('加载音频列表失败：' + err.message);
        });
}

function renderTTSList() {
    const container = document.getElementById('ttsListContainer');
    if (!ttsList.length) {
        container.innerHTML = '<div class="empty-state">还未生成音频，请点击上方按钮开始生成</div>';
        return;
    }
    document.getElementById('genTtsBtn').innerHTML = '<i class="bi bi-arrow-repeat"></i> 重新生成音频';

    container.innerHTML = `
        <h6 class="mb-3">已生成 ${ttsList.length} 条音频：</h6>
        ${ttsList.map((t, i) => {
            const failed = t.status === 'failed';
            return `
            <div class="card item-card${failed ? ' border-danger' : ''}">
                <div class="card-header">
                    <span class="fw-semibold">第 ${i+1} 条：${escapeHtml(t.title || '无标题')}
                        ${failed ? '<span class="badge bg-danger ms-2">生成失败</span>' : ''}</span>
                    <div class="item-actions">
                        <button class="btn btn-sm btn-outline-secondary" onclick="editAndResynthesize(${t.ttsOrder})">
                            <i class="bi bi-pencil"></i> 编辑讲解稿
                        </button>
                        <button class="btn btn-sm btn-outline-primary" onclick="regenTTS(${t.ttsOrder})" id="regenTts${t.ttsOrder}">
                            <i class="bi ${failed ? 'bi-arrow-clockwise' : 'bi-arrow-repeat'}"></i> ${failed ? '重试' : '重生成'}
                        </button>
                    </div>
                </div>
                <div class="card-body">
                    <div class="script-preview">${escapeHtml((t.script || '').substring(0, 200))}</div>
                    ${failed
                        ? '<div class="text-danger small mt-2"><i class="bi bi-x-circle me-1"></i>音频合成失败，请点击「重试」</div>'
                        : `<audio controls preload="none" src="/api/tts/audio?taskId=${taskId}&ttsOrder=${t.ttsOrder}" class="w-100 mt-2"></audio>`}
                </div>
            </div>`;
        }).join('')}
    `;
}

function genTTS() {
    if (!hasUsableKey()) { toastWarning('请先配置 SK'); return; }
    if (ttsList.length) {
        confirmModal('重新生成音频', `已存在 ${ttsList.length} 条音频，重新生成将<b class="text-danger">覆盖全部音频</b>，是否继续？`, doGenTTS);
    } else {
        doGenTTS();
    }
}

async function doGenTTS() {
    const btn = document.getElementById('genTtsBtn');
    btn.disabled = true;
    try {
        await apiFetch(`/api/tts/generate-all?taskId=${taskId}`, { method: 'POST' });
        const job = await pollJobUntilDone('tts', taskId, btn);
        if (job.state === 'success') toastSuccess(job.result);
        loadTTS();
    } catch (err) {
        toastError('合成失败：' + err.message);
        btn.disabled = false;
    } finally {
        if (!btn.dataset.jobTotal) btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> 重新生成音频';
    }
}

async function regenTTS(order) {
    if (!hasUsableKey()) { toastWarning('请先配置 SK'); return; }
    const btn = document.getElementById(`regenTts${order}`);
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    try {
        await apiFetch(`/api/tts/regenerate?taskId=${taskId}&ttsOrder=${order}`, { method: 'POST' });
        toastSuccess('重生成成功');
        loadTTS();
    } catch (err) {
        toastError('重生成失败：' + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> 重生成';
    }
}

// ══════════════════════════════════════════════
//  Step 6: 导出视频
// ══════════════════════════════════════════════
let plyrInstance = null;

function renderStep6(container) {
    container.innerHTML = `
        <h3><i class="bi bi-film"></i> 导出最终视频</h3>
        <p class="step-desc-text">将幻灯片与音频合成高清 MP4 视频文件</p>
        <button class="btn btn-primary" id="exportBtn" onclick="dumpAndExport()">
            <i class="bi bi-play-circle"></i> 执行导出
        </button>
        <div id="videoArea" class="mt-3" style="display:none"></div>
    `;
    checkVideoStatus();
    resumeRunningJob('video', document.getElementById('exportBtn'), () => checkVideoStatus());
}

function checkVideoStatus() {
    if (!taskId) return;
    const area = document.getElementById('videoArea');
    if (!area) return;
    area.style.display = 'block';
    area.innerHTML = renderAreaLoading();
    apiFetch(`/api/task/has-final/${taskId}`)
        .then(res => {
            const info = res.data || {};
            finalExists = !!info.exists;
            finalStale = !!info.stale;
            if (info.exists) showVideo();
            else area.style.display = 'none';
        })
        .catch(err => {
            area.innerHTML = renderAreaError('视频状态检查失败：' + err.message, 'checkVideoStatus');
        });
}

function showVideo() {
    finalExists = true;
    const area = document.getElementById('videoArea');
    area.style.display = 'block';
    const staleTip = finalStale
        ? '<div class="alert alert-warning py-2"><i class="bi bi-exclamation-triangle me-1"></i>课件内容在上次导出后已变更，建议重新导出视频。</div>'
        : '';
    area.innerHTML = `
        <h6 class="mb-3">最终视频预览：</h6>
        ${staleTip}
        <div class="video-preview">
            <video id="finalVideo" playsinline controls style="width:100%">
                <source src="/api/task/download-final/${taskId}" type="video/mp4">
            </video>
            <div class="mt-3 text-center">
                <a href="/api/task/download-final/${taskId}" class="btn btn-success" download>
                    <i class="bi bi-download"></i> 下载视频
                </a>
            </div>
        </div>
    `;
    // 初始化 Plyr
    if (plyrInstance) plyrInstance.destroy();
    const video = document.getElementById('finalVideo');
    if (video) {
        plyrInstance = new Plyr(video, {
            iconUrl: '/static/vendor/plyr/plyr.svg',
            tooltips: { controls: true },
            clickToPlay: true,
            keyboard: { focused: true, global: true },
        });
    }
    document.getElementById('exportBtn').innerHTML = '<i class="bi bi-arrow-repeat"></i> 重新导出';
}

let finalExists = false;
let finalStale = false;

function dumpAndExport() {
    // 已加载的列表中存在失败记录时直接拦截（服务端 dump 也会拒绝）
    const failedSlides = slides.filter(s => s.status === 'failed').length;
    const failedTts = ttsList.filter(t => t.status === 'failed').length;
    if (failedSlides || failedTts) {
        toastWarning(`检测到生成失败的记录（幻灯片 ${failedSlides} 张、音频 ${failedTts} 条），请先回到对应步骤重试后再导出`);
        return;
    }
    if (finalExists) {
        confirmModal('重新导出视频', `将<b class="text-danger">覆盖现有最终视频</b>${finalStale ? '（课件已变更）' : ''}，是否继续？`, doDumpAndExport);
    } else {
        doDumpAndExport();
    }
}

async function doDumpAndExport() {
    const btn = document.getElementById('exportBtn');
    btn.disabled = true;

    try {
        // Step 1: dump（快速同步操作）
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>正在转储幻灯片与音频...';
        await apiFetch(`/api/task/dump/${taskId}`, { method: 'POST' });

        // Step 2: 后台合成视频，轮询进度
        await apiFetch(`/api/task/export-final/${taskId}`, { method: 'POST' });
        const job = await pollJobUntilDone('video', taskId, btn);
        if (job.state === 'success') {
            toastSuccess('🎉 视频合成完成！');
            showVideo();
        }
    } catch (err) {
        toastError(err.message || '导出失败');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> 重新导出';
    }
}