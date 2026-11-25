(function () {
    const form = document.getElementById('history-filter-form');
    const presetBtns = Array.prototype.slice.call(document.querySelectorAll('.preset-btn'));
    const startInput = document.getElementById('filter-start');
    const endInput = document.getElementById('filter-end');
    const levelSelect = document.getElementById('filter-level');
    const minPm25Input = document.getElementById('filter-min-pm25');
    const maxPm25Input = document.getElementById('filter-max-pm25');
    const limitSelect = document.getElementById('filter-limit');
    const sortSelect = document.getElementById('filter-sort');
    const resetBtn = document.getElementById('reset-filters-btn');
    const exportBtn = document.getElementById('export-csv-btn');
    const minMaxToggle = document.getElementById('toggle-minmax-band');
    const errorBox = document.getElementById('history-error-box');

    let activeRange = '7d';
    let showMinMaxBand = true;

    function getPalette() {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        return {
            grid: isDark ? 'rgba(148, 163, 184, 0.14)' : 'rgba(15, 23, 42, 0.08)',
            tick: isDark ? '#94a3b8' : '#64748b',
            legend: isDark ? '#e2e8f0' : '#334155',
            pm1: isDark ? '#fbbf24' : '#f59e0b',
            pm25: isDark ? '#60a5fa' : '#3b82f6',
            pm25Band: isDark ? 'rgba(96, 165, 250, 0.16)' : 'rgba(59, 130, 246, 0.14)',
            pm10: isDark ? '#34d399' : '#10b981'
        };
    }

    function sincaBadgeForRow(pm25, pm10) {
        if (pm25 >= 170 || pm10 >= 330) return { label: 'Emergencia', cls: 'level-emergency' };
        if (pm25 >= 110 || pm10 >= 240) return { label: 'Preemergencia', cls: 'level-preemergency' };
        if (pm25 >= 80 || pm10 >= 195) return { label: 'Alerta', cls: 'level-alert' };
        if (pm25 >= 50 || pm10 >= 150) return { label: 'Regular', cls: 'level-regular' };
        return { label: 'Bueno', cls: 'level-good' };
    }

    // Initialize Historical Trend Line Chart
    const p = getPalette();
    const trendCtx = document.getElementById('historyTrendChart').getContext('2d');
    const trendChart = new Chart(trendCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'PM 2.5 Max',
                    data: [],
                    borderColor: 'transparent',
                    backgroundColor: p.pm25Band,
                    pointRadius: 0,
                    fill: '+1',
                    tension: 0.25
                },
                {
                    label: 'PM 2.5 Min',
                    data: [],
                    borderColor: 'transparent',
                    backgroundColor: 'transparent',
                    pointRadius: 0,
                    fill: false,
                    tension: 0.25
                },
                {
                    label: 'PM 1.0 Avg',
                    data: [],
                    borderColor: p.pm1,
                    borderWidth: 1.8,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: false,
                    tension: 0.25
                },
                {
                    label: 'PM 2.5 Avg',
                    data: [],
                    borderColor: p.pm25,
                    borderWidth: 2.3,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: false,
                    tension: 0.25
                },
                {
                    label: 'PM 10 Avg',
                    data: [],
                    borderColor: p.pm10,
                    borderWidth: 1.8,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: false,
                    tension: 0.25
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            animation: { duration: 250 },
            plugins: {
                legend: {
                    labels: {
                        color: p.legend,
                        usePointStyle: true,
                        boxWidth: 8,
                        filter: function (item) {
                            return item.text !== 'PM 2.5 Max' && item.text !== 'PM 2.5 Min';
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function (ctx) {
                            return ctx.dataset.label + ': ' + ctx.parsed.y + ' µg/m³';
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: p.grid },
                    ticks: { color: p.tick, maxTicksLimit: 8 }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: p.grid },
                    ticks: {
                        color: p.tick,
                        callback: function (v) { return v + ' µg/m³'; }
                    }
                }
            }
        }
    });

    // Initialize Time-of-Day Pattern Bar Chart
    const hourlyCtx = document.getElementById('hourlyPatternChart').getContext('2d');
    const hourlyChart = new Chart(hourlyCtx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Avg PM 2.5',
                    data: [],
                    backgroundColor: p.pm25,
                    borderRadius: 4
                },
                {
                    label: 'Avg PM 10',
                    data: [],
                    backgroundColor: p.pm10,
                    borderRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            animation: { duration: 250 },
            plugins: {
                legend: {
                    labels: { color: p.legend, usePointStyle: true, boxWidth: 8 }
                },
                tooltip: {
                    callbacks: {
                        label: function (ctx) {
                            const val = ctx.parsed.y;
                            return ctx.dataset.label + ': ' + (val !== null ? val + ' µg/m³' : 'No data');
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: p.grid },
                    ticks: { color: p.tick, maxTicksLimit: 12 }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: p.grid },
                    ticks: {
                        color: p.tick,
                        callback: function (v) { return v + ' µg/m³'; }
                    }
                }
            }
        }
    });

    function syncPresetUI(rangeVal) {
        activeRange = rangeVal;
        presetBtns.forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-range') === rangeVal);
        });
    }

    function buildQueryParams() {
        const params = new URLSearchParams();
        const sVal = startInput.value.trim();
        const eVal = endInput.value.trim();

        if (sVal || eVal) {
            params.set('range', 'custom');
            if (sVal) params.set('start', sVal);
            if (eVal) params.set('end', eVal);
        } else {
            params.set('range', activeRange || '7d');
        }

        if (levelSelect.value && levelSelect.value !== 'all') {
            params.set('level', levelSelect.value);
        }
        if (minPm25Input.value.trim() !== '') {
            params.set('min_pm25', minPm25Input.value.trim());
        }
        if (maxPm25Input.value.trim() !== '') {
            params.set('max_pm25', maxPm25Input.value.trim());
        }
        if (limitSelect.value) {
            params.set('limit', limitSelect.value);
        }
        if (sortSelect.value) {
            params.set('sort', sortSelect.value);
        }
        return params;
    }

    function updateExportLink(params) {
        if (!exportBtn) return;
        exportBtn.href = '/api/export?' + params.toString();
    }

    function populateControlsFromFilters(flt) {
        if (!flt) return;
        if (flt.range === 'custom') {
            syncPresetUI('custom');
            startInput.value = flt.start || '';
            endInput.value = flt.end || '';
        } else {
            syncPresetUI(flt.range || '7d');
            startInput.value = '';
            endInput.value = '';
        }
        levelSelect.value = flt.level || 'all';
        minPm25Input.value = flt.min_pm25 !== null && flt.min_pm25 !== undefined ? flt.min_pm25 : '';
        maxPm25Input.value = flt.max_pm25 !== null && flt.max_pm25 !== undefined ? flt.max_pm25 : '';
        limitSelect.value = String(flt.limit || 100);
        sortSelect.value = flt.sort || 'desc';
        updateExportLink(buildQueryParams());
    }

    function formatShortLabel(bucketStr, preset) {
        if (!bucketStr) return '';
        // 'YYYY-MM-DD HH:MM:SS'
        if (preset === '1h' || preset === '24h') {
            return bucketStr.slice(11, 16);
        }
        return bucketStr.slice(5, 16);
    }

    function renderBundle(bundle) {
        if (!bundle) return;
        if (errorBox) errorBox.classList.add('hidden');

        const flt = bundle.filters || {};
        const sum = bundle.summary || {};
        const series = bundle.series || [];
        const hourly = bundle.hourly_profile || [];
        const rows = bundle.rows || [];

        // 1. Summary Strip
        document.getElementById('sum-count').textContent = (sum.total_count || 0).toLocaleString();
        document.getElementById('sum-span').textContent = sum.first_ts && sum.last_ts
            ? sum.first_ts.slice(0, 16) + ' → ' + sum.last_ts.slice(0, 16)
            : 'No readings in window';

        document.getElementById('sum-avg-pm25').textContent = sum.avg_pm25 !== null && sum.avg_pm25 !== undefined
            ? sum.avg_pm25 + ' µg/m³'
            : '--';
        document.getElementById('sum-minmax-pm25').textContent =
            'Min ' + (sum.min_pm25 ?? '--') + ' · Max ' + (sum.max_pm25 ?? '--') + ' µg/m³';

        const sincaBadge = document.getElementById('sum-sinca-badge');
        if (sum.total_count > 0 && sum.avg_pm25 !== null) {
            const b = sincaBadgeForRow(sum.avg_pm25, sum.avg_pm10 || 0);
            sincaBadge.className = 'table-badge ' + b.cls;
            sincaBadge.textContent = b.label;
        } else {
            sincaBadge.className = 'table-badge level-unknown';
            sincaBadge.textContent = '--';
        }

        document.getElementById('sum-avg-pm10').textContent = sum.avg_pm10 !== null && sum.avg_pm10 !== undefined
            ? sum.avg_pm10 + ' µg/m³'
            : '--';
        document.getElementById('sum-minmax-pm10').textContent =
            'Min ' + (sum.min_pm10 ?? '--') + ' · Max ' + (sum.max_pm10 ?? '--') + ' µg/m³';

        document.getElementById('sum-avg-pm1').textContent = sum.avg_pm1 !== null && sum.avg_pm1 !== undefined
            ? sum.avg_pm1 + ' µg/m³'
            : '--';
        document.getElementById('sum-minmax-pm1').textContent =
            'Min ' + (sum.min_pm1 ?? '--') + ' · Max ' + (sum.max_pm1 ?? '--') + ' µg/m³';

        // 2. Historical Trend Chart
        const bucketInfo = document.getElementById('history-bucket-info');
        if (bucketInfo) {
            bucketInfo.textContent = 'Bucket resolution: ' + (flt.bucket_label || 'auto') + ' (' + series.length + ' points)';
        }

        trendChart.data.labels = series.map(function (pt) { return formatShortLabel(pt.bucket, flt.range); });
        trendChart.data.datasets[0].data = showMinMaxBand ? series.map(function (pt) { return pt.max_pm25; }) : [];
        trendChart.data.datasets[1].data = showMinMaxBand ? series.map(function (pt) { return pt.min_pm25; }) : [];
        trendChart.data.datasets[2].data = series.map(function (pt) { return pt.pm1; });
        trendChart.data.datasets[3].data = series.map(function (pt) { return pt.pm25; });
        trendChart.data.datasets[4].data = series.map(function (pt) { return pt.pm10; });
        trendChart.update();

        // 3. Time-of-Day Chart
        hourlyChart.data.labels = hourly.map(function (h) { return h.label; });
        hourlyChart.data.datasets[0].data = hourly.map(function (h) { return h.pm25; });
        hourlyChart.data.datasets[1].data = hourly.map(function (h) { return h.pm10; });
        hourlyChart.update();

        // 4. Filtered Raw Table
        const emptyState = document.getElementById('history-empty-state');
        const tableContainer = document.getElementById('history-table-container');
        const tbody = document.getElementById('history-table-body');
        const tableSub = document.getElementById('table-subtitle');

        if (tableSub) {
            tableSub.textContent = 'Showing ' + rows.length + ' of ' + (sum.total_count || 0).toLocaleString() + ' matching readings';
        }

        if (!rows.length) {
            emptyState.classList.remove('hidden');
            tableContainer.classList.add('hidden');
            tbody.innerHTML = '';
        } else {
            emptyState.classList.add('hidden');
            tableContainer.classList.remove('hidden');
            tbody.innerHTML = rows.map(function (r) {
                const lvl = sincaBadgeForRow(r.pm25, r.pm10);
                return (
                    '<tr>' +
                    '<td class="mono">' + r.timestamp + '</td>' +
                    '<td class="pm1-color bold">' + r.pm1 + '</td>' +
                    '<td class="pm25-color bold">' + r.pm25 + '</td>' +
                    '<td class="pm10-color bold">' + r.pm10 + '</td>' +
                    '<td><span class="table-badge ' + lvl.cls + '">' + lvl.label + '</span></td>' +
                    '</tr>'
                );
            }).join('');
        }
    }

    function applyFilters() {
        const params = buildQueryParams();
        updateExportLink(params);
        window.history.replaceState({}, '', '/history?' + params.toString());

        const applyBtn = document.getElementById('apply-filters-btn');
        if (applyBtn) applyBtn.textContent = 'Loading...';

        fetch('/api/history?' + params.toString())
            .then(function (r) {
                return r.text().then(function (txt) {
                    if (!txt || !txt.trim()) {
                        throw new Error('Server returned an empty response (HTTP ' + r.status + ' — request likely timed out). Please click Apply to retry.');
                    }
                    try {
                        return JSON.parse(txt);
                    } catch (parseErr) {
                        throw new Error('Server returned an unexpected response (HTTP ' + r.status + '). Please retry in a few seconds.');
                    }
                });
            })
            .then(function (data) {
                if (data.error) {
                    if (errorBox) {
                        errorBox.textContent = 'Database Error: ' + data.error;
                        errorBox.classList.remove('hidden');
                    }
                    return;
                }
                renderBundle(data);
            })
            .catch(function (err) {
                if (errorBox) {
                    errorBox.textContent = 'Failed to load history: ' + err;
                    errorBox.classList.remove('hidden');
                }
            })
            .finally(function () {
                if (applyBtn) applyBtn.textContent = 'Apply';
            });
    }

    // Preset pill clicks
    presetBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            startInput.value = '';
            endInput.value = '';
            syncPresetUI(btn.getAttribute('data-range'));
            applyFilters();
        });
    });

    // Clearing preset active pill when typing custom dates
    [startInput, endInput].forEach(function (inp) {
        inp.addEventListener('change', function () {
            if (startInput.value || endInput.value) {
                syncPresetUI('custom');
            }
            updateExportLink(buildQueryParams());
        });
    });

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        applyFilters();
    });

    resetBtn.addEventListener('click', function () {
        startInput.value = '';
        endInput.value = '';
        levelSelect.value = 'all';
        minPm25Input.value = '';
        maxPm25Input.value = '';
        limitSelect.value = '100';
        sortSelect.value = 'desc';
        syncPresetUI('all');
        applyFilters();
    });

    if (minMaxToggle) {
        minMaxToggle.addEventListener('change', function () {
            showMinMaxBand = minMaxToggle.checked;
            if (window.__LAST_BUNDLE__) {
                renderBundle(window.__LAST_BUNDLE__);
            } else if (window.__INITIAL_HISTORY__) {
                renderBundle(window.__INITIAL_HISTORY__);
            }
        });
    }

    // Wrap renderBundle so we remember last rendered data for band toggles
    const origRender = renderBundle;
    renderBundle = function (b) {
        window.__LAST_BUNDLE__ = b;
        origRender(b);
    };

    // Theme updates for both charts
    window.addEventListener('themechange', function () {
        const pal = getPalette();
        trendChart.data.datasets[0].backgroundColor = pal.pm25Band;
        trendChart.data.datasets[2].borderColor = pal.pm1;
        trendChart.data.datasets[3].borderColor = pal.pm25;
        trendChart.data.datasets[4].borderColor = pal.pm10;
        trendChart.options.plugins.legend.labels.color = pal.legend;
        trendChart.options.scales.x.grid.color = pal.grid;
        trendChart.options.scales.x.ticks.color = pal.tick;
        trendChart.options.scales.y.grid.color = pal.grid;
        trendChart.options.scales.y.ticks.color = pal.tick;
        trendChart.update('none');

        hourlyChart.data.datasets[0].backgroundColor = pal.pm25;
        hourlyChart.data.datasets[1].backgroundColor = pal.pm10;
        hourlyChart.options.plugins.legend.labels.color = pal.legend;
        hourlyChart.options.scales.x.grid.color = pal.grid;
        hourlyChart.options.scales.x.ticks.color = pal.tick;
        hourlyChart.options.scales.y.grid.color = pal.grid;
        hourlyChart.options.scales.y.ticks.color = pal.tick;
        hourlyChart.update('none');
    });

    // Lightweight sensor status pill check
    fetch('/api/data?t=' + Date.now())
        .then(function (r) { return r.json(); })
        .then(function (data) {
            const pill = document.getElementById('sensor-status-pill');
            const text = document.getElementById('sensor-status-text');
            if (!pill || !text || !data.meta) return;
            const s = data.meta.status || 'offline';
            pill.className = 'status-pill status-' + s;
            text.textContent = data.meta.has_data ? s.charAt(0).toUpperCase() + s.slice(1) : 'Waiting';
        })
        .catch(function () {});

    // Hydrate immediately from Flask-injected bundle (zero extra DB query on load!)
    if (window.__INITIAL_HISTORY__) {
        populateControlsFromFilters(window.__INITIAL_HISTORY__.filters);
        renderBundle(window.__INITIAL_HISTORY__);
    } else {
        applyFilters();
    }
})();
