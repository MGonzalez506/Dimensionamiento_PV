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
import itertools

import pytz
import csv
import pvlib
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.style
import matplotlib.patches as mpatches
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.axes_grid1 import host_subplot
import mpl_toolkits.axisartist as AA

from time import sleep
from datetime import datetime
from io import StringIO
from pvlib import solarposition
from pvlib import pvsystem
from pvlib import location
from pvlib import clearsky, atmosphere, solarposition
from pvlib.location import Location
from pvlib import irradiance
from rdtools import get_clearsky_tamb

fig_size = plt.rcParams["figure.figsize"]
fig_size[0]=12
fig_size[1]=8
plt.rcParams["figure.figsize"] = fig_size

tz='America/Costa_Rica'
lat = 9.84950
lon = -83.91289
place_name = 'Moren Centro de acondicionamiento Físico'
altitude = 1360

glosario = {'ghi':'Radiación global Horizontal', 'dni':'Radiación directa', 'dhi':'Radiación difusa', 'IR(h)':'Índice de claridad', 'aoi':'Ángulo de incidencia', 'dni_extra':'Porcentaje de radiación extra'}

site=location.Location(lat,lon,tz=tz)

def get_irradiance(site_location, start, end, tilt, surface_azimuth):
  times = pd.date_range(start, end, freq='1min', tz=site_location.tz)
  clearsky = site_location.getclearsky(times)

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
for azimuth_angle in possible_azimuth:
  for weather in tmys:
      location = coordinates[0]
      latitude, longitude, name, altitude, timezone = location
      system['surface_tilt']=latitude
      system['surface_azimuth']=azimuth_angle
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
      energies[azimuth_angle] = annual_energy

energies = pd.Series(energies)

print(energies)
energies.plot(kind='bar',rot=0)
plt.ylabel('Rendimiento energético Anual(Wh)')
plt.xlabel('Ángulo Acimutal')
plt.show()







