# SPDX-FileCopyrightText: 2026 Ramon Kalski
# SPDX-License-Identifier: GPL-2.0-or-later
# Written with help from Claude (Anthropic); see README.md, "How this code was made".
"""Toolbar button and menu entry that open the Pockmark Stats Finder box."""
import os
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication
try:
    from qgis.PyQt.QtGui import QAction           # newer QGIS
except ImportError:
    from qgis.PyQt.QtWidgets import QAction       # older QGIS
from .provider import PockmarkProvider

MENU = "&Pockmark Stats Finder"


class PockmarkStatsPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None

    def initProcessing(self):
        # add the tool to the Processing Toolbox
        self.provider = PockmarkProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        # toolbar button and menu entry
        self.initProcessing()
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.png"))
        self.action = QAction(icon, "Pockmark Stats Finder", self.iface.mainWindow())
        self.action.setToolTip("Measure pockmarks from your outlines")
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(MENU, self.action)

    def unload(self):
        # remove the button, menu entry and tool when the plugin is turned off
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu(MENU, self.action)

    def run(self):
        # open the tool's box
        import processing
        processing.execAlgorithmDialog("pockmarkstats:pockmarkstats", {})
