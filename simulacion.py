#!/usr/bin/python
# -*- coding: UTF-8 -*-
import sys
import os
import serial
import threading
import traceback
import time
import signal
import fcntl
import string
import re

import pytz
import csv
from time import sleep
from datetime import datetime
from io import StringIO

# Importación de bibliotecas
import pvlib
import pandas as pd
import matplotlib.pyplot as plt

glosario = {'ghi':'Radiación global Horizontal', 'dni':'Radiación directa', 'dhi':'Radiación difusa', 'IR(h)':'Índice de claridad', 'aoi':'Ángulo de incidencia', 'dni_extra':'Porcentaje de radiación extra'}

# Latitude, Longitude, Name, Altitude, Timezone
#Costa Rica = America/Costa_Rica
coordinates = [
               (9.84950,-83.91289,'Moren Centro de acondicionamiento Físico',1360,'America/Costa_Rica')
]

#Get modules & inverters
sandia_modules = pvlib.pvsystem.retrieve_sam('SandiaMod')
sapm_inverters = pvlib.pvsystem.retrieve_sam('CECInverter')
"""
new_panel = pd.DataFrame(
    'Technology':'Mono-c-Si',
    'Bifacial':1,
    'STC':540,

    )
"""
module = (sandia_modules['Canadian_Solar_CS5P_220M___2009_'])
inverter = sapm_inverters['ABB__MICRO_0_25_I_OUTD_US_208__208V_']
temperature_model_parameters = pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS['sapm']['open_rack_glass_glass']

tmys = []

for location in coordinates:
  latitude, longitude, name, altitude, timezone = location
  weather = pvlib.iotools.get_pvgis_tmy(latitude,longitude,map_variables=True)[0]
  weather.index.name = 'utc_time'
  tmys.append(weather)

#Para realizar el cálculo del ángulo de inclinación óptima
system = {'module':module, 'inversor':inverter, 'surface_azimuth':180}
possible_azimuth = [5,180,130,310]
energies = {}
for orientation in possible_azimuth:
    print("Orientación: " + str(orientation))
    for weather in tmys:
        location = coordinates[0]
        latitude, longitude, name, altitude, timezone = location
        system['surface_azimuth'] = orientation
        system['surface_tilt']=latitude
        solpos = pvlib.solarposition.get_solarposition(
            time=weather.index,
            latitude=latitude,
            longitude=longitude,
            altitude=altitude,
            temperature=weather['temp_air'],
            pressure=pvlib.atmosphere.alt2pres(altitude)
        )
        dni_extra = pvlib.irradiance.get_extra_radiation(weather.index)
        airmass = pvlib.atmosphere.get_relative_airmass(solpos['apparent_zenith'])
        pressure = pvlib.atmosphere.alt2pres(altitude)
        am_abs = pvlib.atmosphere.get_absolute_airmass(airmass,pressure)
        aoi = pvlib.irradiance.aoi(
            system['surface_tilt'],
            system['surface_azimuth'],
            solpos['apparent_zenith'],
            solpos['azimuth']
        )
        #Irradiación total general
        total_irradiance = pvlib.irradiance.get_total_irradiance(
          system['surface_tilt'],
          system['surface_azimuth'],
          solpos['apparent_zenith'],
          solpos['azimuth'],
          weather['dni'],
          weather['ghi'],
          weather['dhi'],
          dni_extra=dni_extra,
          model='haydavies'
        )
        cell_temperature = pvlib.temperature.sapm_cell(
          total_irradiance['poa_global'],
          weather['temp_air'],
          weather['wind_speed'],
          **temperature_model_parameters     
        )
        #Irradiación efectiva
        effective_irradiance = pvlib.pvsystem.sapm_effective_irradiance(
          total_irradiance['poa_direct'],
          total_irradiance['poa_diffuse'],
          am_abs,
          aoi,
          module
        )  
        dc=pvlib.pvsystem.sapm(effective_irradiance,cell_temperature,module)
        ac=pvlib.inverter.sandia(dc['v_mp'],dc['p_mp'],inverter)
        annual_energy = ac.sum()
        energies[name] = annual_energy

energies = pd.Series(energies)










