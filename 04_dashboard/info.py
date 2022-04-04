info_text = """
# Energy Demand Dashboard
Michael Harty

[Project Repo](https://github.com/mharty3/energy_data_capstone)

I made this dashboard as part of my Data Engineering Zoomcamp Capstone Project. 

It displays data from the data pipeline I created that extracts and transforms data from various sources including the EIA, NOAA, and Open Weather Map API.

Actual energy demand and weather data is updated hourly, and the EIA energy demand forecast is updated each morning whenever the EIA releases their forecast for that day (usually around 8am MDT).

The data is stored in a data warehouse using Google Big Query with the idea that a data scientist (future me) will be able to use it to train a new forecast model and compare it to the EIA's forecast.

"""


note ="""
Historical weather data prior to April 2nd is being pulled from the NOAA Integrated Surface Database. 
It has hourly weather observation data dating back to 1901, however it is usually updated on a few days delay. When their database is updated with recent data, 
the missing data on the dashboard will be backfilled. 

From April 2nd onward, weather data is being pulled from a different, live updating source and should be kept up to date.
"""