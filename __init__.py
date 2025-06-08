# __init__.py

import sys
import subprocess
from qgis.core import Qgis

def check_and_install_dependencies(iface):
    """
    Checks if the 'websockets' package is installed. If not, attempts to install it.
    Returns True if dependency is met, False otherwise.
    This check runs when the plugin is first loaded by QGIS.
    """
    try:
        # If this import works, the dependency is met.
        import websockets
        return True
    except ImportError:
        # If the import fails, try to install the package.
        iface.messageBar().pushMessage(
            "Vessel Tracker",
            "Dependency 'websockets' not found. Attempting to install...",
            level=Qgis.Warning,
            duration=5
        )

        python_executable = sys.executable
        if not python_executable:
            iface.messageBar().pushMessage(
                "Vessel Tracker",
                "Could not determine QGIS Python path. Please install 'websockets' manually.",
                level=Qgis.Critical,
                duration=10
            )
            return False

        try:
            # --- FIX: Run the command as a single string with shell=True ---
            # This is more robust and avoids QGIS misinterpreting the arguments.
            # We wrap the python_executable in quotes to handle potential spaces in the path.
            command = f'"{python_executable}" -m pip install websockets'
            
            subprocess.run(
                command,
                shell=True, # Use the system shell to execute the command
                capture_output=True,
                text=True,
                check=True
            )
            # --- END FIX ---

            iface.messageBar().pushMessage(
                "Vessel Tracker",
                "'websockets' installed successfully. Please reload the plugin (e.g., by restarting QGIS or reloading it in the Plugin Manager).",
                level=Qgis.Info,
                duration=10
            )
            return False # Return False so the plugin doesn't fully load this time.
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            iface.messageBar().pushMessage(
                "Vessel Tracker",
                f"Failed to install 'websockets'. Please install it manually using the OSGeo4W shell. Error: {e}",
                level=Qgis.Critical,
                duration=10
            )
            return False

def classFactory(iface):
    """
    Called by QGIS to get a new instance of your plugin.
    This function is required by all QGIS plugins.
    """
    # First, perform the dependency check.
    if not check_and_install_dependencies(iface):
        # If dependencies are not met, return None. This tells QGIS not to
        # load the plugin, which prevents the ModuleNotFoundError.
        return None

    # If dependencies are met, proceed with the normal import and instantiation.
    try:
        from .VesselTracker import VesselTracker
        return VesselTracker(iface)
    except ImportError as e:
        print(f"Vessel Tracker: Failed to import VesselTracker class. Error: {e}")
        return None
