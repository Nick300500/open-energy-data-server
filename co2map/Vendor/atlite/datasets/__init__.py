# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2016 - 2023 The Atlite Authors
#
# SPDX-License-Identifier: MIT

from Vendor.atlite.datasets import dwd, era5, gebco, meteo, meteo_hist
from Vendor.atlite.datasets import sarah

modules = {"era5": era5, "sarah": sarah, "gebco": gebco, "meteo": meteo, "meteo_hist": meteo_hist, "dwd": dwd}
