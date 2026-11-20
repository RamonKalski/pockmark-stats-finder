# SPDX-FileCopyrightText: 2026 Ramon Kalski
# SPDX-License-Identifier: GPL-2.0-or-later
# Written with help from Claude (Anthropic); see README.md, "How this code was made".
"""Adds Pockmark Stats Finder to the QGIS Processing Toolbox."""
import os
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProcessingProvider
from .algorithm import PockmarkStatsAlgorithm


class PockmarkProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(PockmarkStatsAlgorithm())

    def id(self):
        return "pockmarkstats"

    def name(self):
        return "Pockmark Stats Finder"

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.png"))
