/* ═══════════════════════════════════════════
   Relay — main.js
   Global utilities: clock, toasts, modals, sidebar
   ═══════════════════════════════════════════ */

// ── Live Clock ─────────────────────────────────────────────────
function updateClock() {
    const el = document.getElementById('liveClock');
    if (!el) return;
    const now = new Date();
    const opts = {
        timeZone: 'Asia/Kolkata',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
        weekday: 'short',
        day: 'numeric',
        month: 'short',
    };
    el.textContent = new Intl.DateTimeFormat('en-IN', opts).format(now);
}

setInterval(updateClock, 1000);
updateClock();

// ── Toast Notifications ─────────────────────────────────────────
function showToast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const icons = {
        success: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`,
        error:   `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
        info:    `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    };

    toast.innerHTML = `${icons[type] || icons.info}<span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// ── Modal Helpers ───────────────────────────────────────────────
function showModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('open');
}

function hideModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('open');
}

// Close modal when clicking overlay
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) {
        e.target.classList.remove('open');
    }
});

// Close modals on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.open')
                .forEach(m => m.classList.remove('open'));
    }
});

// ── Sidebar Toggle ──────────────────────────────────────────────
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    sidebar.style.transform = sidebar.style.transform === 'translateX(-100%)'
        ? 'translateX(0)'
        : 'translateX(-100%)';
}

// ── Flash Auto-Dismiss ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
        document.querySelectorAll('.flash').forEach(el => {
            el.style.transition = 'opacity 0.4s';
            el.style.opacity = '0';
            setTimeout(() => el.remove(), 400);
        });
    }, 4000);
});


// ── Theme Switcher (Cyber vs Solar) ─────────────────────────────
function initTheme() {
    const savedTheme = localStorage.getItem('relay_theme');
    const theme = (savedTheme === 'light') ? 'light' : 'midnight';
    selectTheme(theme);
}

function selectTheme(theme) {
    const activeTheme = (theme === 'light') ? 'light' : 'midnight';
    document.documentElement.setAttribute('data-theme', activeTheme);
    localStorage.setItem('relay_theme', activeTheme);

    const cyberBtn = document.getElementById('themeBtnCyber');
    const solarBtn = document.getElementById('themeBtnSolar');
    if (cyberBtn && solarBtn) {
        if (activeTheme === 'midnight') {
            cyberBtn.classList.add('active');
            solarBtn.classList.remove('active');
        } else {
            solarBtn.classList.add('active');
            cyberBtn.classList.remove('active');
        }
    }
}

// Run theme init on DOM load
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
});
