clear; close all;

addpath("data\")
files = dir("data\");

figure(1); hold on
colors = {'g', 'b', 'r'};
markersize = 6;

% ---- Definitions for PM 2.5/ PM 10 ratio ------
combustion_zone = 0.6;  % > 0.6 means combustion
dust_zone = 0.4; % < 0.4 means dust

% In between means it is a mixture of combustion and dust

allData = table();
dates_of_interest = [zeros(length(files))];
for i = 8:length(files)
    % Process each file (e.g., load data, analyze, etc.)
    if contains(files(i).name, '.csv')
        filename = files(i).name;
    else
        continue        
    end
    % Add further processing steps here

    data = readtable(filename,"ReadVariableNames",true,"FileType","text"); % Load the data from the current file
    % Perform analysis on the loaded data
    
    if isempty(data)
        continue
    else
        disp("Processing file: " + filename)
        dt = datetime(data.date, "Format", "dd/MM/uuuu HH:mm:ss");
        
        x = dateshift(dt, 'start', 'day');
        y = timeofday(dt);
        
        pm_data = [data.pm1, data.pm25, data.pm10];
        
        % Ensure times are sorted and remove duplicate timestamps (keep first occurrence)
        [dtSorted, sortIdx] = sort(dt);
        dupMask = [true; diff(dtSorted) ~= 0];        % true for first of each unique time
        keepIdx = sortIdx(dupMask);

        dt = dtSorted(dupMask);
        x = x(keepIdx);
        y = y(keepIdx);
        
        pm_data = double([data.pm1, data.pm25, data.pm10]);
        pm_data = pm_data(keepIdx,:);
        
        % Spike removal using a 4-second duration window
        win = seconds(4);
        pm_med = movmedian(pm_data, win, 'SamplePoints', dt);
        is_spike = isoutlier(pm_data, 'movmedian', win, 'SamplePoints', dt, 'ThresholdFactor', 3);
        for c = 1:size(pm_data,2)
            pm_data(is_spike(:,c), c) = pm_med(is_spike(:,c), c);
        end
        
        % Store the cleaned measurements for subsequent analysis
        cleanDailyTable = table(dt, pm_data(:,1), pm_data(:,2), pm_data(:,3), 'VariableNames', {'date', 'pm1', 'pm25', 'pm10'});

        allData = [allData; cleanDailyTable];

        pm_ratio = pm_data(:,2) ./ pm_data(:,3);

        name(i) = data.date(1);
        name(i) = string(year(name(i))) + '-' + string(month(name(i))) + '-' + string(day(name(i)));
        
        for k = 1:3
            plot3(x, y, pm_data(:,k), "Color", colors{k}, "MarkerSize", markersize);
        end
        
        view(3)
        title("Material Particulado " + string(name(1)) + '-' + string(name(end)))
        xlabel('Date');
        ylabel('Time of day');
        zlabel('Concentration (µg/m³)')
        legend('PM1', 'PM2.5', 'PM10');
        grid on;
        axis tight

        zlim([0 250])
        
    end
end
hold off

%%


allData.date = datetime(allData.date);

% Extract the hour
allData.HourOfDay = hour(allData.date);

% Group all matching hours together and calculate mean
circadianData = groupsummary(allData, 'HourOfDay', 'mean', {'pm1', 'pm25', 'pm10'});

figure;
hold on;

% Plot PM10 and PM2.5 on a 24-hour axis
plot(circadianData.HourOfDay, circadianData.mean_pm1, '-o', 'LineWidth', 2, 'DisplayName', 'PM1 (Microscopic)');
plot(circadianData.HourOfDay, circadianData.mean_pm25, '-o', 'LineWidth', 2, 'DisplayName', 'PM2.5 (Fine)');
plot(circadianData.HourOfDay, circadianData.mean_pm10, '-o', 'LineWidth', 2, 'DisplayName', 'PM10 (Coarse)');

title('24-Hour Circadian Rhythm of Air Quality');
xlabel('Hour of Day (0 = Midnight, 23 = 11 PM)');
ylabel('Average PM Concentration (\mug/m^3)');

% Force the X-axis to show every single hour clearly
xticks(0:23);
xlim([0 23]);

legend;
grid on;

%%

TT = table2timetable(allData, 'RowTimes', 'date');

minuteTT = retime(TT, 'minutely', 'max');

minuteTT.pm25_Spike = [0; diff(minuteTT.pm25)];

minuteTT = rmmissing(minuteTT, 'DataVariables', {'pm1', 'pm25', 'pm10', 'pm25_Spike'});

sortedSpikes = sortrows(minuteTT, 'pm25_Spike', 'descend');

top10Spikes = sortedSpikes(1:min(10, height(sortedSpikes)), :);

disp('Top 10 Sudden Air Quality Degradation Events:');
disp(top10Spikes(:, {'pm25', 'pm25_Spike'}));

figure;
subplot(2, 1, 1);
plot(minuteTT.date, minuteTT.pm25, 'k-');
ylabel('PM2.5 (\mug/m^3)');
title('Raw 1-Minute Max PM2.5');
grid on;

subplot(2, 1, 2);
plot(minuteTT.date, minuteTT.pm25_Spike, 'r-');
ylabel('\Delta PM2.5 / min');
xlabel('Time');
title('1-Minute Sudden Spikes (\Delta PM2.5)')
grid on;

%%

% Calculate the raw ratio
allData.Ratio = allData.pm25 ./ allData.pm10;

% Clean up any divide-by-zero errors
allData.Ratio(isinf(allData.Ratio)) = NaN;

allData.Source = repmat("Clean / Unknown", height(allData), 1);

% Apply the ratio filters
allData.Source(allData.Ratio >= 0.6) = "Combustion (Smoke/Cooking)";
allData.Source(allData.Ratio <= 0.4) = "Mechanical (Dust/Dander)";
allData.Source(allData.Ratio > 0.4 & allData.Ratio < 0.6) = "Mixed / Boundary";

% Convert to categorical (this makes MATLAB plotting much easier)
allData.Source = categorical(allData.Source);

% Find high-pollution combustion events (PM2.5 > 35 ug/m^3)
is_severe_smoke = (allData.Source == "Combustion (Smoke/Cooking)") & (allData.pm25 > 35);

% Extract just those rows
smokeEvents = allData(is_severe_smoke, :);

% Sort by worst PM2.5 first
smokeEvents = sortrows(smokeEvents, 'pm25', 'descend');

disp('Worst Combustion / Smoke Events:');
disp(smokeEvents(1:min(10, height(smokeEvents)), {'date', 'pm25', 'pm10', 'Ratio'}));

figure;
hold on;

% Get max PM2.5 value to set the height of the shading
y_max = max(allData.pm25) * 1.1;

% Create 1s and 0s for each event type
is_smoke = (allData.Source == "Combustion (Smoke/Cooking)");
is_dust = (allData.Source == "Mechanical (Dust/Dander)");

% Plot the red smoke zones
area(allData.date, is_smoke .* y_max, ...
    'FaceColor', 'r', 'FaceAlpha', 0.2, 'EdgeColor', 'none', ...
    'DisplayName', 'Combustion Event')

% Plot the yellow dust zones
area(allData.date, is_dust .* y_max, ...
    'FaceColor', 'y', 'FaceAlpha', 0.2, 'EdgeColor', 'none', ...
    'DisplayName', 'Dust/Mechanical Event');

% Plot the raw data in black so it stands out agains the colors
plot(allData.date, allData.pm25, 'k.', 'LineWidth', 1, 'DisplayName', 'PM2.5 (\mug/m^3)')

% Lock the Y-axis so the shading touches the very top of the graph
ylim([0, y_max]);

title('PM2.5 Air Quality with Source Fingerprinting')
xlabel('Time')
ylabel('Concentration')
legend('Location', 'best')
grid on;

%% 

% Create a default column of "Weekday" strings
allData.DayType = repmat("Weekday", height(allData), 1);

% Find all weekends (Saturdays and Sundays) and overwrite the label
allData.DayType(isweekend(allData.date)) = "Weekend";

% Convert to categorical for easy grouping
allData.DayType = categorical(allData.DayType);

% Ensure you have the Hour column ready
allData.HourOfDay = hour(allData.date);

% Group by Hour and DayType
circadianSplit = groupsummary(allData, {'HourOfDay', 'DayType'}, 'mean', {'pm1', 'pm25', 'pm10'});

% Extract the two datasets
weekdays = circadianSplit(circadianSplit.DayType == 'Weekday', :);
weekends = circadianSplit(circadianSplit.DayType == 'Weekend', :);

figure;
hold on;

% Plot PM2.5 for both groups
plot(weekdays.HourOfDay, weekdays.mean_pm25, '-b', 'LineWidth', 2, 'DisplayName', 'Weekdays (Mon-Fri)');
plot(weekends.HourOfDay, weekends.mean_pm25, '-r', 'LineWidth', 2, 'DisplayName', 'Weekends (Sat-Sun)');

title('Circadian Rhythm: Weekday vs Weekend (PM2.5)');
xlabel('HourOfDay (0 = Midnight)');
ylabel('Average PM2.5 (\mug/m^3)');

% Format axes
xticks(0:23);
xlim([0 23]);
legend('Location', 'best');
grid on;