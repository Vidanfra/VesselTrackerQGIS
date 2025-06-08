# __init__.py

import sys
import traceback
from qgis.core import Qgis
from qgis.core import QgsMessageLog

# A dummy class to safely handle the case where dependencies are missing.
# This prevents QGIS from crashing when it tries to call initGui() on a None object.
class DummyPlugin:
    def __init__(self, iface):
        # The dependency checker already showed the necessary messages.
        pass
    def initGui(self):
        # This method is required by QGIS. It does nothing.
        pass
    def unload(self):
        # This method is required by QGIS. It does nothing.
        pass

def check_dependencies(iface):
    """
    Checks if the 'websockets' package is installed. If not, displays clear
    manual installation instructions.
    Returns True if dependency is met, False otherwise.
    """
    try:
        # If this import works, the dependency is met.
        import websockets
        return True
    except ImportError:
        # If the import fails, build and show a clear, persistent message.
        message = (
            "Vessel Tracker: Dependency 'websockets' is not installed.\n"
            "The required Python library 'websockets' is not installed.\n"
            "Please install it manually by following these steps:\n"
            "- Open the 'OSGeo4W Shell' from your Windows Start Menu.\n"
            "- In the shell, type the following command and press Enter:\n"
            "- 'pip install websockets'\n"
            "- Wait for the installation to complete.\n"
            "- Restart QGIS or reload the plugin in the Plugin Manager.\n"
        )
        iface.messageBar().pushMessage(
            "Vessel Tracker Error",
            "Missing required library: websockets. Run 'pip install websockets' in OSGeo4W Shell. Check the documentation for more install instructions.",
            level=Qgis.Critical,
            duration=20
        )
        # Also log the message to the QGIS Log Messages panel for developers/debugging.

        QgsMessageLog.logMessage(message, 'Vessel Tracker', Qgis.Critical)
        
        return False

def classFactory(iface):
    """
    Called by QGIS to get a new instance of your plugin.
    This function is required by all QGIS plugins.
    """
    # First, perform the dependency check.
    if not check_dependencies(iface):
        # If dependencies are not met, return a dummy plugin instance
        # to prevent QGIS from crashing.
        return DummyPlugin(iface)

    # If dependencies are met, proceed with the normal import and instantiation.
    try:
        from .VesselTracker import VesselTracker
        return VesselTracker(iface)
    except Exception as e:
        iface.messageBar().pushMessage(
            "Vessel Tracker Error",
            f"Plugin failed to load: {e}",
            level=Qgis.Critical,
            duration=10
        )
        Qgis.messageLog().logMessage(
            f"Vessel Tracker: Exception during import:\n{traceback.format_exc()}",
            'Vessel Tracker',
            Qgis.Critical
        )
        return DummyPlugin(iface)