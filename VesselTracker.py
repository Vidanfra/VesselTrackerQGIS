import os
import json
from PyQt5.QtWidgets import QAction, QDialog, QTableWidgetItem
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QThread
from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsField,
    QgsProject,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    edit,
)
from qgis.PyQt.QtCore import QVariant

from .ais_worker import AISWorker
from .vessel_input_dialog import Ui_VesselInputDialog

plugin_dir = os.path.dirname(__file__)


class VesselTracker:
    def __init__(self, iface):
        self.iface = iface
        self.layer = None
        self.mmsi_name_map = {}
        self.vessel_features = {}
        self.ais_thread = None
        self.ais_worker = None
        # NEW: State flag to prevent starting a new thread while one is closing
        self.is_shutting_down = False

    def initGui(self):
        icon = os.path.join(plugin_dir, "icon.png")
        self.action = QAction(QIcon(icon), "Vessel Tracker", self.iface.mainWindow())
        self.iface.addToolBarIcon(self.action)
        self.action.triggered.connect(self.run)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        del self.action
        self._stop_tracking()
        if self.layer:
            # Prevent crash on closing QGIS if thread is still shutting down
            if self.is_shutting_down:
                QThread.msleep(100) # Give a brief moment for cleanup
            QgsProject.instance().removeMapLayer(self.layer.id())

    def run(self):
        """
        Main logic to run the tracker.
        - Stops any previous tracking session.
        - Loads vessels from JSON and shows a dialog.
        - If accepted, saves the list and starts tracking.
        """
        self._stop_tracking()

        dlg = QDialog(self.iface.mainWindow())
        ui = Ui_VesselInputDialog()
        ui.setupUi(dlg)

        self.mmsi_name_map = self._load_vessels_from_json()
        self._populate_table(ui, self.mmsi_name_map)

        ui.btnAdd.clicked.connect(lambda: self._on_add_row(ui))
        ui.btnRemove.clicked.connect(lambda: self._on_remove_selected_rows(ui))
        ui.buttonBox.accepted.connect(dlg.accept)
        ui.buttonBox.rejected.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            return
            
        # --- CRITICAL FIX ---
        # Check if the previous thread is still in the process of shutting down.
        if self.is_shutting_down:
            self.iface.messageBar().pushMessage(
                "Vessel Tracker",
                "A previous session is still closing. Please try again in a moment.",
                level=1, # Warning level
                duration=5
            )
            return
        # --- END FIX ---

        self.mmsi_name_map = self._read_table(ui)
        self._save_vessels_to_json(self.mmsi_name_map)

        if not self.mmsi_name_map:
            return

        self.iface.messageBar().pushMessage(
            "Vessel Tracker", f"Tracking {len(self.mmsi_name_map)} vessel(s)…", level=0
        )

        if not self.layer:
            self._init_layer()

        self.ais_worker = AISWorker(list(self.mmsi_name_map.keys()))
        self.ais_thread = QThread()
        self.ais_worker.moveToThread(self.ais_thread)
        self.ais_worker.vessel_received.connect(self.update_position)
        self.ais_thread.started.connect(self.ais_worker.run)
        self.ais_thread.finished.connect(self._on_thread_finished)
        self.ais_thread.start()

    def _stop_tracking(self):
        """
        NON-BLOCKING shutdown of the tracking thread.
        """
        if self.ais_thread and self.ais_thread.isRunning():
            # Set the flag to indicate a shutdown is in progress
            self.is_shutting_down = True
            if self.ais_worker:
                try:
                    self.ais_worker.vessel_received.disconnect(self.update_position)
                except TypeError:
                    pass
                self.ais_worker.stop()
            self.ais_thread.quit()

    def _on_thread_finished(self):
        """
        Cleanup slot that is called ONLY when the thread has safely stopped.
        """
        self.iface.messageBar().pushMessage("Vessel Tracker", "Tracking session stopped.", level=0)
        self.ais_worker = None
        self.ais_thread = None
        # Clear the flag, allowing a new session to be started
        self.is_shutting_down = False

    def _vessels_file_path(self):
        return os.path.join(plugin_dir, 'tracked_vessels.json')

    def _load_vessels_from_json(self):
        file_path = self._vessels_file_path()
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            self.iface.messageBar().pushMessage(
                "Vessel Tracker", f"Could not load vessel file: {e}", level=2
            )
        return {}

    def _save_vessels_to_json(self, vessels_map):
        file_path = self._vessels_file_path()
        try:
            with open(file_path, 'w') as f:
                json.dump(vessels_map, f, indent=4)
        except IOError as e:
            self.iface.messageBar().pushMessage(
                "Vessel Tracker", f"Could not save vessel file: {e}", level=2
            )

    def _populate_table(self, ui, vessels_map):
        table = ui.tableVessels
        table.setRowCount(0)
        for mmsi, name in vessels_map.items():
            row_count = table.rowCount()
            table.insertRow(row_count)
            table.setItem(row_count, 0, QTableWidgetItem(mmsi))
            table.setItem(row_count, 1, QTableWidgetItem(name))

    def _on_add_row(self, ui):
        table = ui.tableVessels
        row_count = table.rowCount()
        table.insertRow(row_count)

    def _on_remove_selected_rows(self, ui):
        table = ui.tableVessels
        selected = table.selectionModel().selectedRows()
        for index in sorted(selected, key=lambda x: x.row(), reverse=True):
            table.removeRow(index.row())

    def _read_table(self, ui):
        mapping = {}
        table = ui.tableVessels
        for row in range(table.rowCount()):
            mmsi_item = table.item(row, 0)
            name_item = table.item(row, 1)
            if not mmsi_item or not name_item:
                continue
            mmsi_text = mmsi_item.text().strip()
            name_text = name_item.text().strip()
            if mmsi_text and name_text:
                mapping[mmsi_text] = name_text
        return mapping

    def _init_layer(self):
        uri = "Point?crs=EPSG:4326&field=MMSI:string&field=Name:string"
        self.layer = QgsVectorLayer(uri, "AIS Tracked Vessels", "memory")
        QgsProject.instance().addMapLayer(self.layer)
        labeling = QgsPalLayerSettings()
        labeling.fieldName = "Name"
        labeling.placement = QgsPalLayerSettings.OverPoint
        self.layer.setLabelsEnabled(True)
        self.layer.setLabeling(QgsVectorLayerSimpleLabeling(labeling))
        self.layer.triggerRepaint()
        self.vessel_features = {}

    def update_position(self, mmsi, lat, lon):
        if not self.layer: return
        vessel_name = self.mmsi_name_map.get(mmsi, mmsi)
        point = QgsPointXY(lon, lat)
        geom = QgsGeometry.fromPointXY(point)
        with edit(self.layer):
            if mmsi in self.vessel_features:
                fid = self.vessel_features[mmsi]
                self.layer.changeGeometry(fid, geom)
            else:
                feat = QgsFeature(self.layer.fields())
                feat.setGeometry(geom)
                feat.setAttributes([mmsi, vessel_name])
                pr = self.layer.dataProvider()
                success, added_features = pr.addFeatures([feat])
                if success and added_features:
                    new_id = added_features[0].id()
                    self.vessel_features[mmsi] = new_id
                    self.layer.updateExtents()

        msg = f"New AIS update - Vessel: {vessel_name}, LAT: {lat}, LON: {lon}, MMSI: {mmsi}"
        self.iface.messageBar().pushMessage(
            "Vessel Tracker", msg, level=0
        )
