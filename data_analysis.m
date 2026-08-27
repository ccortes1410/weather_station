clear; close all;

addpath("data\")
files = dir("data\");

for i = 1:length(files)
    % Process each file (e.g., load data, analyze, etc.)
    filename = files(i).name;
    % Add further processing steps here
end

data = readtable(filename,"ReadVariableNames",true,"FileType","text"); % Load the data from the current file
% Perform analysis on the loaded data

fig = figure(name="2026-08-26");
figure(fig)

hold on
plot(data.date, data.pm1, "g", "MarkerSize", 3);
plot(data.date, data.pm25, "b", "MarkerSize", 3);
plot(data.date, data.pm10, "r", "MarkerSize", 3);

title("Material Particulado 2026-08-26")
xlabel('Date');
ylabel('Concentration (µg/m³)');
legend('PM1', 'PM2.5', 'PM10');
grid on;
axis tight


