# SPDX-FileCopyrightText: 2026 Ramon Kalski
# SPDX-License-Identifier: GPL-2.0-or-later
# Written with help from Claude (Anthropic); see README.md, "How this code was made".
# QGIS calls this to start the plugin
def classFactory(iface):
    from .plugin import PockmarkStatsPlugin
    return PockmarkStatsPlugin(iface)
