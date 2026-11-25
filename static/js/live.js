(function () {
    const POLL_INTERVAL_MS = 5000;
    const STATS_POLL_INTERVAL_MS = 300000; // 5 minutes (matches server TTL cache)
    const SCALE_STORAGE_KEY = 'aq_scale';
    const THRESHOLD_STORAGE_KEY = 'aq_show_thresholds';

    let pollTimer = null;
    let statsTimer = null;
    let relativeTimer = null;
    let lastServerData = null;
    let lastRollingStats = null;
    let lastReceivedClientMs = null;
    let showThresholds = true;
    let currentScale = 'sinca';

    // Load saved user preferences
    try {
        currentScale = localStorage.getItem(SCALE_STORAGE_KEY) || 'sinca';
        const savedThresh = localStorage.getItem(THRESHOLD_STORAGE_KEY);
        if (savedThresh !== null) {
            showThresholds = savedThresh === 'true';
        }
    } catch (e) {}

    // Threshold reference lines for PM2.5 context
    const THRESHOLD_LINES = [
        { value: 15, label: 'WHO 15', color: '#0ea5e9' },
        { value: 25, label: 'LED 25', color: '#f97316' },
        { value: 50, label: 'SINCA 50', color: '#ef4444' }
    ];

    // Lightweight inline Chart.js plugin to draw horizontal threshold reference lines
    const thresholdLinesPlugin = {
        id: 'thresholdLines',
        afterDatasetsDraw: function (chart) {
            if (!showThresholds) return;

            const ctx = chart.ctx;
            const yScale = chart.scales.y;
            const area = chart.chartArea;
            if (!yScale || !area) return;

            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

            ctx.save();
            THRESHOLD_LINES.forEach(function (line) {
                if (line.value < yScale.min || line.value > yScale.max) return;
                const y = yScale.getPixelForValue(line.value);
                if (y < area.top || y > area.bottom) return;

                // Dashed reference line
                ctx.beginPath();
                ctx.setLineDash([6, 5]);
                ctx.lineWidth = 1.4;
                ctx.strokeStyle = line.color;
                ctx.moveTo(area.left, y);
                ctx.lineTo(area.right, y);
                ctx.stroke();

                // Right-aligned pill tag
                ctx.setLineDash([]);
                ctx.font = '600 10px "Segoe UI", system-ui, sans-serif';
                const textWidth = ctx.measureText(line.label).width;
                const padX = 5;
                const boxH = 16;
                const boxW = textWidth + padX * 2;
                const boxX = area.right - boxW - 4;
                const boxY = Math.max(area.top + 2, y - boxH - 3);

                ctx.fillStyle = isDark ? 'rgba(19, 28, 49, 0.88)' : 'rgba(255, 255, 255, 0.9)';
                ctx.fillRect(boxX, boxY, boxW, boxH);
                ctx.strokeStyle = line.color;
                ctx.lineWidth = 1;
                ctx.strokeRect(boxX, boxY, boxW, boxH);

                ctx.fillStyle = line.color;
                ctx.textAlign = 'left';
                ctx.textBaseline = 'middle';
                ctx.fillText(line.label, boxX + padX, boxY + boxH / 2);
            });
            ctx.restore();
        }
    };

    function getChartPalette() {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        return {
            grid: isDark ? 'rgba(148, 163, 184, 0.14)' : 'rgba(15, 23, 42, 0.08)',
            tick: isDark ? '#94a3b8' : '#64748b',
            legend: isDark ? '#e2e8f0' : '#334155',
            pm1: isDark ? '#fbbf24' : '#f59e0b',
            pm25: isDark ? '#60a5fa' : '#3b82f6',
            pm10: isDark ? '#34d399' : '#10b981'
        };
    }

    function formatRelativeSeconds(sec) {
        if (sec === null || sec === undefined) return 'No pings received yet';
        if (sec < 5) return 'Just now';
        if (sec < 60) return sec + 's ago';
        const mins = Math.floor(sec / 60);
        if (mins < 60) return mins + 'm ' + (sec % 60) + 's ago';
        const hrs = Math.floor(mins / 60);
        return hrs + 'h ' + (mins % 60) + 'm ago';
    }

    // Initialize Chart.js
    const palette = getChartPalette();
    const ctx = document.getElementById('airQualityChart').getContext('2d');
    const airChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'PM 1.0',
                    data: [],
                    borderColor: palette.pm1,
                    backgroundColor: 'rgba(245, 158, 11, 0.12)',
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'PM 2.5',
                    data: [],
                    borderColor: palette.pm25,
                    backgroundColor: 'rgba(59, 130, 246, 0.12)',
                    borderWidth: 2.2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'PM 10',
                    data: [],
                    borderColor: palette.pm10,
                    backgroundColor: 'rgba(16, 185, 129, 0.10)',
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: true,
                    tension: 0.3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            animation: { duration: 300 },
            plugins: {
                legend: {
                    labels: {
                        color: palette.legend,
                        usePointStyle: true,
                        boxWidth: 8
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
                    grid: { color: palette.grid },
                    ticks: { color: palette.tick, maxTicksLimit: 10 }
                },
                y: {
                    beginAtZero: true,
                    suggestedMax: 30,
                    grid: { color: palette.grid },
                    ticks: {
                        color: palette.tick,
                        callback: function (v) { return v + ' µg/m³'; }
                    }
                }
            }
        },
        plugins: [thresholdLinesPlugin]
    });

    function updateChartTheme() {
        const p = getChartPalette();
        airChart.data.datasets[0].borderColor = p.pm1;
        airChart.data.datasets[1].borderColor = p.pm25;
        airChart.data.datasets[2].borderColor = p.pm10;
        airChart.options.plugins.legend.labels.color = p.legend;
        airChart.options.scales.x.grid.color = p.grid;
        airChart.options.scales.x.ticks.color = p.tick;
        airChart.options.scales.y.grid.color = p.grid;
        airChart.options.scales.y.ticks.color = p.tick;
        airChart.update('none');
    }

    function updateAqiBanner(live, hasData) {
        const banner = document.getElementById('aqi-banner');
        const scaleLabel = document.getElementById('aqi-scale-label');
        const indexVal = document.getElementById('aqi-index-val');
        const badge = document.getElementById('aqi-category-badge');
        const driverText = document.getElementById('aqi-driver-text');
        const adviceText = document.getElementById('aqi-advice-text');

        if (!hasData || !live) {
            banner.setAttribute('data-level', 'unknown');
            scaleLabel.textContent = currentScale === 'epa'
                ? 'US EPA AQI (2024)'
                : currentScale === 'who'
                    ? 'WHO 2021 24h Guidelines'
                    : 'Chile ICAP / SINCA';
            indexVal.textContent = '--';
            badge.textContent = 'Waiting';
            driverText.textContent = 'Waiting for live sensor reading...';
            adviceText.textContent = 'Connect the Pico weather station to begin streaming real-time particulate matter readings.';
            return;
        }

        const result = window.AirQualityIndex.evaluate(currentScale, live.pm25, live.pm10);
        banner.setAttribute('data-level', result.level);
        scaleLabel.textContent = result.scaleLabel;
        indexVal.textContent = result.displayValue;
        badge.textContent = result.category;
        driverText.textContent = result.driverText;
        adviceText.textContent = result.advice;
    }

    function updateStatusUI(meta) {
        const pill = document.getElementById('sensor-status-pill');
        const statusText = document.getElementById('sensor-status-text');
        const relEl = document.getElementById('relative-time');
        const countEl = document.getElementById('session-count');

        if (!meta) return;

        let elapsed = meta.seconds_since_update;
        if (elapsed !== null && lastReceivedClientMs !== null) {
            elapsed = Math.max(0, Math.floor((Date.now() - lastReceivedClientMs) / 1000));
        }

        let status = meta.status || 'offline';
        if (meta.has_data && elapsed !== null) {
            if (elapsed <= 30) status = 'online';
            else if (elapsed <= 300) status = 'stale';
            else status = 'offline';
        }

        pill.className = 'status-pill status-' + status;
        if (!meta.has_data) {
            statusText.textContent = 'Waiting';
        } else if (status === 'online') {
            statusText.textContent = 'Online';
        } else if (status === 'stale') {
            statusText.textContent = 'Stale · ' + formatRelativeSeconds(elapsed);
        } else {
            statusText.textContent = 'Offline · ' + formatRelativeSeconds(elapsed);
        }

        relEl.textContent = meta.has_data ? 'Seen ' + formatRelativeSeconds(elapsed) : 'No live pings yet';
        countEl.textContent = 'Session: ' + (meta.buffer_size || 0) + '/' + (meta.buffer_capacity || 300) + ' pings';
    }

    function updateSessionStats(stats) {
        ['pm1', 'pm25', 'pm10'].forEach(function (key) {
            const s = stats && stats[key];
            document.getElementById(key + '-min').textContent = s ? s.min : '--';
            document.getElementById(key + '-avg').textContent = s ? s.avg : '--';
            document.getElementById(key + '-max').textContent = s ? s.max : '--';
        });
    }

    function renderData(data) {
        lastServerData = data;
        const meta = data.meta || {};
        const hasData = Boolean(meta.has_data);

        if (hasData && meta.seconds_since_update !== null && meta.seconds_since_update !== undefined) {
            lastReceivedClientMs = Date.now() - meta.seconds_since_update * 1000;
        } else {
            lastReceivedClientMs = null;
        }

        if (data.live) {
            document.getElementById('update-time').textContent = hasData
                ? 'Last reading: ' + data.live.time_full
                : 'Last reading: Waiting for Pico...';
            document.getElementById('pm1-val').textContent = hasData ? data.live.pm1 : '--';
            document.getElementById('pm25-val').textContent = hasData ? data.live.pm25 : '--';
            document.getElementById('pm10-val').textContent = hasData ? data.live.pm10 : '--';
        }

        updateAqiBanner(data.live, hasData);
        updateStatusUI(meta);
        updateSessionStats(data.session_stats);

        if (data.live_chart && data.live_chart.length > 0) {
            airChart.data.labels = data.live_chart.map(function (row) { return row.time_short; });
            airChart.data.datasets[0].data = data.live_chart.map(function (row) { return row.pm1; });
            airChart.data.datasets[1].data = data.live_chart.map(function (row) { return row.pm25; });
            airChart.data.datasets[2].data = data.live_chart.map(function (row) { return row.pm10; });

            const maxVal = Math.max(
                30,
                ...airChart.data.datasets[2].data,
                ...airChart.data.datasets[1].data
            );
            // Make sure the 50 µg/m³ SINCA line is visible when values rise near it
            airChart.options.scales.y.suggestedMax = maxVal >= 40 ? Math.max(60, Math.ceil(maxVal * 1.15)) : 30;
            airChart.update();
        }
    }

    function renderRolling24h(stats) {
        lastRollingStats = stats;
        const badge = document.getElementById('rolling-badge');
        const subtitle = document.getElementById('rolling-subtitle');
        const p1 = document.getElementById('r24-pm1');
        const p25 = document.getElementById('r24-pm25');
        const p25Range = document.getElementById('r24-pm25-range');
        const p10 = document.getElementById('r24-pm10');
        const p10Range = document.getElementById('r24-pm10-range');
        const peak = document.getElementById('r24-peak');
        const samples = document.getElementById('r24-samples');
        if (!badge || !p25) return;

        if (!stats || !stats.samples) {
            badge.className = 'table-badge level-unknown';
            badge.textContent = 'No 24h Data';
            if (subtitle) subtitle.textContent = 'No readings recorded in TiDB in the last 24 hours';
            p1.innerHTML = '-- <small>&micro;g/m&sup3;</small>';
            p25.innerHTML = '-- <small>&micro;g/m&sup3;</small>';
            p25Range.textContent = 'Min -- · Max --';
            p10.innerHTML = '-- <small>&micro;g/m&sup3;</small>';
            p10Range.textContent = 'Min -- · Max --';
            peak.textContent = '--';
            samples.textContent = '0 readings';
            return;
        }

        const evalRes = window.AirQualityIndex.evaluate(currentScale, stats.avg_pm25 || 0, stats.avg_pm10 || 0);
        badge.className = 'table-badge level-' + evalRes.level;
        badge.textContent = evalRes.displayValue + ' · ' + evalRes.category;
        if (subtitle) subtitle.textContent = 'Official 24h rolling window since ' + (stats.since || '') + ' (cached 5m)';

        p1.innerHTML = (stats.avg_pm1 !== null ? stats.avg_pm1 : '--') + ' <small>&micro;g/m&sup3;</small>';
        p25.innerHTML = (stats.avg_pm25 !== null ? stats.avg_pm25 : '--') + ' <small>&micro;g/m&sup3;</small>';
        p25Range.textContent = 'Min ' + (stats.min_pm25 ?? '--') + ' · Max ' + (stats.max_pm25 ?? '--') + ' µg/m³';
        p10.innerHTML = (stats.avg_pm10 !== null ? stats.avg_pm10 : '--') + ' <small>&micro;g/m&sup3;</small>';
        p10Range.textContent = 'Min ' + (stats.min_pm10 ?? '--') + ' · Max ' + (stats.max_pm10 ?? '--') + ' µg/m³';
        peak.textContent = stats.peak_hour ? stats.peak_hour + ' (' + stats.peak_hour_pm25 + ' µg/m³)' : '--';
        samples.textContent = stats.samples.toLocaleString() + ' readings';
    }

    function fetchRollingStats() {
        fetch('/api/stats?t=' + Date.now())
            .then(function (r) { return r.json(); })
            .then(renderRolling24h)
            .catch(function () {});
    }

    function fetchData() {
        fetch('/api/data?t=' + Date.now())
            .then(function (response) { return response.json(); })
            .then(renderData)
            .catch(function (err) {
                console.error('Error fetching dashboard data:', err);
            });
    }

    function startPolling() {
        stopPolling();
        fetchData();
        fetchRollingStats();
        pollTimer = setInterval(fetchData, POLL_INTERVAL_MS);
        statsTimer = setInterval(fetchRollingStats, STATS_POLL_INTERVAL_MS);
        const info = document.getElementById('footer-poll-info');
        if (info) info.textContent = 'Live updates every 5s';
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
        if (statsTimer) {
            clearInterval(statsTimer);
            statsTimer = null;
        }
    }

    // Pause polling when tab is hidden, resume immediately when visible
    document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
            stopPolling();
            const info = document.getElementById('footer-poll-info');
            if (info) info.textContent = 'Polling paused (tab hidden)';
        } else {
            startPolling();
        }
    });

    // Wire up scale selector & threshold toggle
    const scaleSelect = document.getElementById('scale-select');
    if (scaleSelect) {
        scaleSelect.value = currentScale;
        scaleSelect.addEventListener('change', function () {
            currentScale = scaleSelect.value;
            try { localStorage.setItem(SCALE_STORAGE_KEY, currentScale); } catch (e) {}
            if (lastServerData) {
                updateAqiBanner(lastServerData.live, Boolean(lastServerData.meta && lastServerData.meta.has_data));
            }
            if (lastRollingStats) {
                renderRolling24h(lastRollingStats);
            }
        });
    }

    const threshToggle = document.getElementById('toggle-thresholds');
    const threshLegend = document.getElementById('threshold-legend');
    if (threshToggle) {
        threshToggle.checked = showThresholds;
        if (threshLegend) threshLegend.classList.toggle('hidden', !showThresholds);
        threshToggle.addEventListener('change', function () {
            showThresholds = threshToggle.checked;
            try { localStorage.setItem(THRESHOLD_STORAGE_KEY, String(showThresholds)); } catch (e) {}
            if (threshLegend) threshLegend.classList.toggle('hidden', !showThresholds);
            airChart.update('none');
        });
    }

    window.addEventListener('themechange', updateChartTheme);

    // Smoothly tick the "Seen Xs ago" counter every second between 5s server polls
    relativeTimer = setInterval(function () {
        if (lastServerData && lastServerData.meta) {
            updateStatusUI(lastServerData.meta);
        }
    }, 1000);

    // Start live polling if tab is visible
    if (!document.hidden) {
        startPolling();
    }
})();
