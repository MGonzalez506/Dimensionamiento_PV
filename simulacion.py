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
from pvlib import temperature
from rdtools import get_clearsky_tamb

fig_size = plt.rcParams["figure.figsize"]
fig_size[0]=12
fig_size[1]=8
plt.rcParams["figure.figsize"] = fig_size

site_tz='America/Costa_Rica'
site_lat = 9.84950
site_lon = -83.91289
site_name = 'Moren Centro de acondicionamiento Físico'
site_alt = 1425

glosario = {
      'sapm':'Sandia PV Array Performance Model',
      'sam':'System Advisor Model',
      'tmy':'Typical Meteorological Year Data',
      'ghi':'Radiación global Horizontal', 
      'dni':'Radiación directa', 
      'dhi':'Radiación difusa', 
      'IR(h)':'Índice de claridad', 
      'aoi':'Ángulo de incidencia', 
      'dni_extra':'Porcentaje de radiación extra',
      'POA':'Plane of Array'
      }

THIS_FOLDER = os.path.dirname(os.path.abspath(__file__))
output_file_addr = THIS_FOLDER + '/pvgis_tmy_backup/'
output_file_addr += site_name + '.csv'

"""
site=location.Location(site_lat,site_lon,tz=site_tz)

def get_irradiance(site_location, start, end, tilt, surface_azimuth):
  times = pd.date_range(start, end, freq='1min', tz=site_location.site_tz)
  clearsky = site_location.get_clearsky(times)
  solar_position = site_location.get_solarposition(times)
  POA_irradiance = irradiance.get_total_irradiance(
    surface_tilt = tilt,
    surface_azimuth = surface_azimuth,
    dni = clearsky['dni'],
    ghi = clearsky['ghi'],
    dhi = clearsky['dhi'],
    solar_zenith = solar_position['apparent_zenith'],
    solar_azimuth = solar_position['azimuth'])
  return pd.DataFrame({
    'DNI':clearsky['dni'],
    'DHI':clearsky['dhi'],
    'GHI':clearsky['ghi'],
    'POA':POA_irradiance['poa_global']
    })

site_irrandiance = get_irradiance(site,'2022-12-10', '2022-12-22', 10, 0)

fig, ax = plt.subplots()
site_irrandiance['GHI'].plot(ax=ax, label='GHI')
site_irrandiance['POA'].plot(ax=ax, label='POA')
ax.set_xlabel('Timestamp [min]')
ax.set_ylabel('Irradiance [$W/m^2$]')
ax.set_title('GHI to POA transposition')
ax.legend()
plt.show()

tus = location.Location(site_lat, site_lon, site_tz, site_alt, site_name)
"""

#Get modules & inverters
sandia_modules = pvlib.pvsystem.retrieve_sam('SandiaMod')
sapm_inverters = pvlib.pvsystem.retrieve_sam('CECInverter')


module = (sandia_modules['Canadian_Solar_CS5P_220M___2009_'])
inverter = sapm_inverters['ABB__MICRO_0_25_I_OUTD_US_208__208V_']
temperature_model_parameters = pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS['sapm']['open_rack_glass_glass']

tmys = []

coordinates = [
               (site_lat,site_lon,site_name,site_alt,site_tz)
]

def get_pvgis_tmy_from_coordinates(coordinates):
  tmys = []
  months = []
  for location in coordinates:
    latitude, longitude, name, altitude, timezone = location
    data_frame = pvlib.iotools.get_pvgis_tmy(latitude,longitude,map_variables=True)
    weather = data_frame[0]
    weather.index.name = 'utc_time'
    tmys.append(weather)
    months = data_frame[1]
  return tmys, months
tmys,selected_months = get_pvgis_tmy_from_coordinates(coordinates)

#Para realizar el cálculo del ángulo de inclinación óptima
system = {'module':module, 'inversor':inverter, 'surface_azimuth':180}
azimuth_testing = [0,90,180,270]
tilt_testing = [5,10,15]
energies = {}
monthly_energy = {}
last_ac = pd.DataFrame()
for tilt_angle in tilt_testing:
  for azimuth_angle in azimuth_testing:
    for weather in tmys:
        location = coordinates[0]
        latitude, longitude, name, altitude, timezone = location
        system['surface_tilt']=tilt_angle
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
        last_ac = ac
        annual_energy = ac.sum()
        label = str(tilt_angle) + "º & " + str(azimuth_angle) + "Azi"
        monthly_energy[label] = ac
        energies[label] = annual_energy

#print(last_ac.keys())
print("###################")
date_min = datetime.strptime("2005-01-01 00:00:00+00:00","%Y-%m-%d %H:%M:%S%z")
date_max = datetime.strptime("2005-01-30 00:00:00+00:00","%Y-%m-%d %H:%M:%S%z")
#x = last_ac.where(last_ac.keys() < "2005-01-30 00:00:00+00:00")
#x = last_ac.between_time('00:00', '01:00') #Works but not to much
#x = last_ac.loc['2005-01-01':'2005-01-02'] #Working perfectly <--------------------
estudio_por_mes = {}
for i in selected_months:
  this_year = i['year']
  this_month = i['month']
  mes = str(this_year) + '-' + str(this_month) + '-01'
  x = last_ac.loc[mes:mes]
  sumatoria = x.sum()
  estudio_por_mes[mes] = float(sumatoria)

estudio_por_mes = pd.Series(estudio_por_mes)
estudio_por_mes.plot(kind='bar', rot=0)
plt.ylabel('Energía KWh para un ángulo de inclinación y azimuth determinado')
plt.xlabel('Mes escogido por el sistema para el estudio')
plt.show()