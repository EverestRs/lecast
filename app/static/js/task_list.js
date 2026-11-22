/* task_list.js — 任务列表页面 */

let currentPage = 1;
let searchKeyword = '';
let deleteTaskId = null;
let lastPageCount = 0;

// ── 状态徽章配色映射（文案 statusLabel 由后端统一下发）──
const STATUS_BADGE = {
    uploaded: 'bg-secondary',
    sections_done: 'bg-info',
    slides_done: 'bg-primary',
    scripts_done: 'bg-warning text-dark',
    tts_done: 'bg-orange',
    video_done: 'bg-success',
};

function loadTasks(page = 1) {
    currentPage = page;
    let url = `/api/task/list?current=${page}`;
    if (searchKeyword) {
        url += `&task_name=${encodeURIComponent(searchKeyword)}`;
    }

    document.getElementById('taskTableBody').innerHTML =
        `<tr><td colspan="5" class="text-center text-muted py-4"><span class="spinner-border spinner-border-sm me-2"></span>加载中...</td></tr>`;

    apiFetch(url)
        .then(res => {
            const data = res.data;
            lastPageCount = (data.records || []).length;
            const tbody = document.getElementById('taskTableBody');
            if (!data.records || data.records.length === 0) {
                tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">暂无任务</td></tr>`;
                document.getElementById('pagination').innerHTML = '';
                return;
            }
            tbody.innerHTML = data.records.map(t => {
                const badge = STATUS_BADGE[t.status] || 'bg-secondary';
                const label = escapeHtml(t.statusLabel || t.status || '');
                return `
                <tr>
                    <td class="fw-semibold">${escapeHtml(t.taskName)}</td>
                    <td><span class="badge ${badge}">${label}</span></td>
                    <td><code class="text-muted small">${escapeHtml(t.taskId)}</code></td>
                    <td>${formatDate(t.createTime)}</td>
                    <td>
                        <button class="btn btn-sm btn-outline-primary me-1" onclick="viewDetail('${t.taskId}')">
                            <i class="bi bi-eye"></i> 详情
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="showDeleteModal('${t.taskId}')">
                            <i class="bi bi-trash"></i> 删除
                        </button>
                    </td>
                </tr>`;
            }).join('');

            const totalPages = Math.ceil(data.total / data.size) || 1;
            renderPagination(data.current, totalPages);
        })
        .catch(err => {
            document.getElementById('taskTableBody').innerHTML =
                `<tr><td colspan="5" class="text-center text-danger py-4">${escapeHtml(err.message)}
                    <div class="mt-2"><button class="btn btn-sm btn-outline-primary" onclick="retryLoadTasks()">
                        <i class="bi bi-arrow-clockwise"></i> 重试
                    </button></div>
                </td></tr>`;
            document.getElementById('pagination').innerHTML = '';
        });
}

function retryLoadTasks() {
    loadTasks(currentPage);
}

function pageItems(current, total) {
    // 首末页恒显 + 当前页 ±2，其余以省略号折叠
    const pages = new Set([1, total]);
    for (let p = current - 2; p <= current + 2; p++) {
        if (p >= 1 && p <= total) pages.add(p);
    }
    return [...pages].sort((a, b) => a - b);
}

function renderPagination(current, total) {
    const ul = document.getElementById('pagination');
    if (total <= 1) { ul.innerHTML = ''; return; }

    let html = `<li class="page-item ${current <= 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="loadTasks(${current - 1}); return false;">上一页</a></li>`;

    let prev = 0;
    for (const p of pageItems(current, total)) {
        if (p - prev > 1) {
            html += `<li class="page-item disabled"><span class="page-link">…</span></li>`;
        }
        html += `<li class="page-item ${p === current ? 'active' : ''}">
            <a class="page-link" href="#" onclick="loadTasks(${p}); return false;">${p}</a></li>`;
        prev = p;
    }

    html += `<li class="page-item ${current >= total ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="loadTasks(${current + 1}); return false;">下一页</a></li>`;
    ul.innerHTML = html;
}

function viewDetail(taskId) {
    window.location.href = `/taskCreate?taskId=${taskId}`;
}

function showDeleteModal(taskId) {
    deleteTaskId = taskId;
    new bootstrap.Modal(document.getElementById('deleteModal')).show();
}

function confirmDelete() {
    if (!deleteTaskId) return;
    const btn = document.getElementById('deleteConfirmBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 删除中...';

    apiFetch(`/api/task/${deleteTaskId}`, { method: 'DELETE' })
        .then(() => {
            bootstrap.Modal.getInstance(document.getElementById('deleteModal')).hide();
            toastSuccess('任务已删除');
            const targetPage = (lastPageCount === 1 && currentPage > 1) ? currentPage - 1 : currentPage;
            loadTasks(targetPage);
        })
        .catch(err => toastError(err.message || '删除失败，请稍后重试'))
        .finally(() => {
            btn.disabled = false;
            btn.innerHTML = '确定删除';
            deleteTaskId = null;
        });
}

function searchTasks() {
    const keyword = document.getElementById('searchInput').value.trim();
    searchKeyword = keyword;
    document.getElementById('clearSearchBtn').style.display = keyword ? 'inline-block' : 'none';
    loadTasks(1);
}

function clearSearch() {
    document.getElementById('searchInput').value = '';
    searchKeyword = '';
    document.getElementById('clearSearchBtn').style.display = 'none';
    loadTasks(1);
}

function goToCreate() {
    window.location.href = '/taskCreate';
}

function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleString();
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadTasks(1);
    const nav = document.getElementById('nav-taskList');
    if (nav) nav.classList.add('active');
});