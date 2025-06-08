# __init__.py

import sys
import os
import platform
import subprocess
from qgis.core import Qgis

# A dummy class to safely handle the case where dependencies are missing.
class DummyPlugin:
    def __init__(self, iface):
        pass
    def initGui(self):
        pass
    def unload(self):
        pass

def check_and_install_dependencies(iface):
    """
    Checks for dependencies. If on Windows, attempts to install them using a .bat file.
    On other OS, provides manual instructions.
    Returns True if dependencies are met, False otherwise.
    """
    try:
        import websockets
        return True
    except ImportError:
        # Dependency is not met. Handle based on the operating system.
        if platform.system() == "Windows":
            return install_for_windows(iface)
        else:
            return show_manual_instructions(iface, "Unsupported OS")

def install_for_windows(iface):
    """
    Generates and runs a .bat file to install dependencies from requirements.txt
    using the correct QGIS OSGeo4W environment.
    """
    try:
        plugin_dir = os.path.dirname(os.path.realpath(__file__))
        requirements_path = os.path.join(plugin_dir, 'requirements.txt')
        
        if not os.path.exists(requirements_path):
            iface.messageBar().pushMessage(
                "Vessel Tracker Error",
                f"requirements.txt not found in {plugin_dir}",
                level=Qgis.Critical,
                duration=10
            )
            return False

        # sys.executable is inside the 'bin' folder. o4w_env.bat is in the parent folder.
        qgis_env_path = os.path.dirname(sys.executable)

        # Content for the .bat file
        bat_content = f"""
@ECHO OFF
ECHO Installing dependencies for Vessel Tracker...
CALL "{qgis_env_path}\\o4w_env.bat"
CALL py3_env
ECHO Installing from: {requirements_path}
python -m pip install -r "{requirements_path}"
ECHO Installation complete. Please restart QGIS or reload the plugin.
PAUSE
EXIT
"""
        
        bat_path = os.path.join(plugin_dir, "install_dependencies.bat")
        with open(bat_path, "w") as f:
            f.write(bat_content)
            
        # Inform the user they need to run the .bat file.
        # We cannot reliably run it with the correct permissions from here.
        message = f"""
        Vessel Tracker - Dependencies Missing:
        <br><br>
        A batch file has been created to install the required 'websockets' library.
        <br><br>
        <b>Please follow these steps:</b>
        <br>
        1. Navigate to the plugin directory: <b>{plugin_dir}</b>
        <br>
        2. Right-click on <b>install_dependencies.bat</b> and select 'Run as administrator'.
        <br>
        3. After the installation finishes, reload this plugin in the QGIS Plugin Manager.
        """
        iface.messageBar().pushMessage(
            "Vessel Tracker Action Required",
            message,
            level=Qgis.Critical,
            duration=0
        )

    except Exception as e:
        show_manual_instructions(iface, f"Failed to create installer: {e}")
        
    return False # Always return False so the plugin doesn't load until reloaded.

def show_manual_instructions(iface, reason=""):
    """Displays a message asking the user to install dependencies manually."""
    message = f"""
    Vessel Tracker - Dependency Error: The 'websockets' library is missing. ({reason})
    <br><br>
    Please install it manually by following these steps:
    <br>
    1. Open the 'OSGeo4W Shell' from your Start Menu.
    <br>
    2. Type the command: <b>pip install websockets</b>
    <br>
    3. Press Enter and wait for the installation to complete.
    <br>
    4. Restart QGIS or reload the plugin in the Plugin Manager.
    """
    iface.messageBar().pushMessage(
        "Vessel Tracker Error",
        message,
        level=Qgis.Critical,
        duration=0  # Make the message persistent
    )
    return False

def classFactory(iface):
    """Called by QGIS to get a new instance of your plugin."""
    if not check_and_install_dependencies(iface):
        return DummyPlugin(iface)

    try:
        from .VesselTracker import VesselTracker
        return VesselTracker(iface)
    except ImportError as e:
        print(f"Vessel Tracker: Failed to import VesselTracker class. Error: {e}")
        return DummyPlugin(iface)
