import pandas as pd
import requests
from datetime import datetime


airports = ['LEMD', 'LEBL', 'LEMG']

base_url = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

params = {
    'station': airports,
    'data': 'all',  # todas las variables
    'year1': '2021',
    'month1': '12',
    'day1': '1',
    'year2': '2021',
    'month2': '12',
    'day2': '31',
    'tz': 'Etc/UTC',
    'format': 'onlycomma',  # CSV
    'latlon': 'yes',
    'elev': 'yes',
    'missing': 'null',
    'trace': '0.0001',
    'direct': 'no',
    'report_type': [1,2]  # METAR y SPECI
}

# Descargar datos
response = requests.get(base_url, params=params)

# Guardar CSV
with open('weather_data_2021.csv', 'wb') as f:
    f.write(response.content)

# Cargar en pandas
df = pd.read_csv('weather_data_2021.csv')
print(f"Datos descargados: {len(df)} observaciones")
print(df.head())