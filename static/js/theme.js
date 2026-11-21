(function () {
    const STORAGE_KEY = 'aq_theme';

    function getCurrentTheme() {
        return document.documentElement.getAttribute('data-theme') || 'light';
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        try {
            localStorage.setItem(STORAGE_KEY, theme);
        } catch (e) {}
        window.dispatchEvent(new CustomEvent('themechange', { detail: { theme: theme } }));
    }

    document.addEventListener('DOMContentLoaded', function () {
        const btn = document.getElementById('theme-toggle');
        if (!btn) return;

        btn.addEventListener('click', function () {
            const next = getCurrentTheme() === 'dark' ? 'light' : 'dark';
            applyTheme(next);
        });
    });
})();
