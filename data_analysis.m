clear; close all;

addpath("data\")
files = dir("data\");

for i = 1:length(files)
    % Process each file (e.g., load data, analyze, etc.)
    if contains(files(i).name, '.csv')
        filename = files(i).name;
    else
        continue        
    end
    % Add further processing steps here


    data = readtable(filename,"ReadVariableNames",true,"FileType","text"); % Load the data from the current file
    % Perform analysis on the loaded data
    
    name = data.date(1);
    name = string(year(name)) + '-' + string(month(name)) + '-' + string(day(name));
    
    fig = figure(name=name);
    figure(fig)
    
    hold on
    plot(data.date, data.pm1, "g", "MarkerSize", 3);
    plot(data.date, data.pm25, "b", "MarkerSize", 3);
    plot(data.date, data.pm10, "r", "MarkerSize", 3);
    
    title("Material Particulado " + name)
    xlabel('Date');
    ylabel('Concentration (µg/m³)');
    legend('PM1', 'PM2.5', 'PM10');
    grid on;
    axis tight
end
