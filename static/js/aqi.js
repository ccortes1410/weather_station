/**
 * Air Quality Index calculation engine supporting:
 * 1. Chile ICAP / SINCA (Default — D.S. N° 12/2011 for MP2.5 & D.S. N° 59/1998 for MP10)
 * 2. US EPA AQI (2024 PM2.5 & PM10 breakpoints)
 * 3. WHO 2021 24-hour Guidelines & Interim Targets
 */
(function (global) {
    function linearPiecewise(value, breakpoints) {
        if (value <= 0) return 0;
        for (let i = 0; i < breakpoints.length; i++) {
            const [cLow, cHigh, iLow, iHigh] = breakpoints[i];
            if (value <= cHigh) {
                if (cHigh === cLow) return iHigh;
                return Math.round(((iHigh - iLow) / (cHigh - cLow)) * (value - cLow) + iLow);
            }
        }
        const last = breakpoints[breakpoints.length - 1];
        const [cLow, cHigh, iLow, iHigh] = last;
        const slope = (iHigh - iLow) / Math.max(1, cHigh - cLow);
        return Math.round(iHigh + (value - cHigh) * slope);
    }

    // --- 1. CHILE ICAP / SINCA ---
    const SINCA_PM25_BP = [
        [0, 50, 0, 100],
        [50, 80, 100, 200],
        [80, 110, 200, 300],
        [110, 170, 300, 500]
    ];

    const SINCA_PM10_BP = [
        [0, 150, 0, 100],
        [150, 195, 100, 200],
        [195, 240, 200, 300],
        [240, 330, 300, 500]
    ];

    function evalSinca(pm25, pm10) {
        const icap25 = linearPiecewise(pm25, SINCA_PM25_BP);
        const icap10 = linearPiecewise(pm10, SINCA_PM10_BP);
        const icap = Math.max(icap25, icap10);
        const driver = icap25 >= icap10 ? 'MP2.5' : 'MP10';

        let category, level, advice;
        if (pm25 >= 170 || pm10 >= 330) {
            category = 'Emergencia';
            level = 'emergency';
            advice = 'Nivel de emergencia ambiental. Evite toda actividad física al aire libre y mantenga puertas y ventanas cerradas.';
        } else if (pm25 >= 110 || pm10 >= 240) {
            category = 'Preemergencia';
            level = 'preemergency';
            advice = 'Riesgo sanitario elevado. Suspenda ejercicio al aire libre; grupos sensibles deben permanecer en interiores.';
        } else if (pm25 >= 80 || pm10 >= 195) {
            category = 'Alerta';
            level = 'alert';
            advice = 'Episodio de alerta ambiental. Reduzca actividad física intensa al aire libre y evite calefacción a leña.';
        } else if (pm25 >= 50 || pm10 >= 150) {
            category = 'Regular';
            level = 'regular';
            advice = 'Calidad del aire regular. Grupos sensibles (niños, adultos mayores, asmáticos) pueden notar molestias leves.';
        } else {
            category = 'Bueno';
            level = 'good';
            advice = 'Calidad del aire buena y segura para actividades al aire libre.';
        }

        return {
            scaleLabel: 'Chile ICAP / SINCA',
            displayValue: 'ICAP ' + icap,
            category: category,
            level: level,
            driverText: 'Instantaneous equivalence · Driver: ' + driver + ' (' + (driver === 'MP2.5' ? pm25 : pm10) + ' µg/m³)',
            advice: advice
        };
    }

    // --- 2. US EPA AQI (2024 PM2.5 updated breakpoints) ---
    const EPA_PM25_BP = [
        [0.0, 9.0, 0, 50],
        [9.1, 35.4, 51, 100],
        [35.5, 55.4, 101, 150],
        [55.5, 125.4, 151, 200],
        [125.5, 225.4, 201, 300],
        [225.5, 325.4, 301, 500]
    ];

    const EPA_PM10_BP = [
        [0, 54, 0, 50],
        [55, 154, 51, 100],
        [155, 254, 101, 150],
        [255, 354, 151, 200],
        [355, 424, 201, 300],
        [425, 604, 301, 500]
    ];

    function evalEpa(pm25, pm10) {
        const aqi25 = Math.min(500, linearPiecewise(pm25, EPA_PM25_BP));
        const aqi10 = Math.min(500, linearPiecewise(pm10, EPA_PM10_BP));
        const aqi = Math.max(aqi25, aqi10);
        const driver = aqi25 >= aqi10 ? 'PM2.5' : 'PM10';

        let category, level, advice;
        if (aqi > 300) {
            category = 'Hazardous';
            level = 'emergency';
            advice = 'Health warning of emergency conditions. Everyone should avoid outdoor exertion.';
        } else if (aqi > 200) {
            category = 'Very Unhealthy';
            level = 'emergency';
            advice = 'Health alert: increased risk of health effects for everyone. Stay indoors if possible.';
        } else if (aqi > 150) {
            category = 'Unhealthy';
            level = 'preemergency';
            advice = 'Everyone may begin to experience health effects; sensitive groups should avoid outdoor exertion.';
        } else if (aqi > 100) {
            category = 'Unhealthy (Sensitive)';
            level = 'alert';
            advice = 'Members of sensitive groups may experience health effects. Consider reducing prolonged outdoor activity.';
        } else if (aqi > 50) {
            category = 'Moderate';
            level = 'regular';
            advice = 'Acceptable air quality; unusually sensitive people should consider limiting prolonged outdoor exertion.';
        } else {
            category = 'Good';
            level = 'good';
            advice = 'Air quality is satisfactory and air pollution poses little or no risk.';
        }

        return {
            scaleLabel: 'US EPA AQI (2024)',
            displayValue: 'AQI ' + aqi,
            category: category,
            level: level,
            driverText: 'Instantaneous equivalence · Driver: ' + driver + ' (' + (driver === 'PM2.5' ? pm25 : pm10) + ' µg/m³)',
            advice: advice
        };
    }

    // --- 3. WHO 2021 24-HOUR GUIDELINES ---
    function whoTierPm25(v) {
        if (v <= 15) return 0;
        if (v <= 25) return 1;
        if (v <= 37.5) return 2;
        if (v <= 50) return 3;
        if (v <= 75) return 4;
        return 5;
    }

    function whoTierPm10(v) {
        if (v <= 45) return 0;
        if (v <= 50) return 1;
        if (v <= 75) return 2;
        if (v <= 100) return 3;
        if (v <= 150) return 4;
        return 5;
    }

    const WHO_TIERS = [
        {
            short: 'AQG',
            category: 'Meets WHO Guideline',
            level: 'good',
            advice: 'Within WHO 2021 24-hour guideline limits (PM2.5 <= 15 µg/m³, PM10 <= 45 µg/m³).'
        },
        {
            short: 'IT-4',
            category: 'Interim Target 4',
            level: 'regular',
            advice: 'Above WHO guideline but within Interim Target 4 (PM2.5 <= 25 µg/m³, PM10 <= 50 µg/m³).'
        },
        {
            short: 'IT-3',
            category: 'Interim Target 3',
            level: 'regular',
            advice: 'Elevated particulate matter (WHO Interim Target 3: PM2.5 <= 37.5 µg/m³).'
        },
        {
            short: 'IT-2',
            category: 'Interim Target 2',
            level: 'alert',
            advice: 'High particulate matter (WHO Interim Target 2: PM2.5 <= 50 µg/m³). Limit prolonged outdoor exposure.'
        },
        {
            short: 'IT-1',
            category: 'Interim Target 1',
            level: 'preemergency',
            advice: 'Very high particulate matter (WHO Interim Target 1: PM2.5 <= 75 µg/m³). Reduce outdoor activity.'
        },
        {
            short: '>IT-1',
            category: 'Exceeds All Targets',
            level: 'emergency',
            advice: 'Exceeds all WHO 24-hour interim targets. Minimize outdoor exposure and keep indoor air filtered.'
        }
    ];

    function evalWho(pm25, pm10) {
        const t25 = whoTierPm25(pm25);
        const t10 = whoTierPm10(pm10);
        const tierIdx = Math.max(t25, t10);
        const driver = t25 >= t10 ? 'PM2.5' : 'PM10';
        const info = WHO_TIERS[tierIdx];

        return {
            scaleLabel: 'WHO 2021 24h Guidelines',
            displayValue: info.short,
            category: info.category,
            level: info.level,
            driverText: 'Instantaneous equivalence · Driver: ' + driver + ' (' + (driver === 'PM2.5' ? pm25 : pm10) + ' µg/m³)',
            advice: info.advice
        };
    }

    function evaluate(scale, pm25, pm10) {
        if (scale === 'epa') return evalEpa(pm25, pm10);
        if (scale === 'who') return evalWho(pm25, pm10);
        return evalSinca(pm25, pm10);
    }

    global.AirQualityIndex = { evaluate: evaluate };
})(window);
