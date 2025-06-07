import os
from PyQt5.QtWidgets import QAction, QDialog, QTableWidgetItem
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QThread, pyqtSlot
# Near the other qgis.core imports in VesselTracker.py
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
    Qgis,
)
from qgis.PyQt.QtCore import QVariant

from .ais_worker import AISWorker
from .vessel_input_dialog import Ui_VesselInputDialog

plugin_dir = os.path.dirname(__file__)


class VesselTracker:
    def __init__(self, iface):
        self.iface = iface

        # In‐memory layer reference
        self.layer = None

        # { mmsi_str: vessel_name }
        self.mmsi_name_map = {}

        # { mmsi_str: feature_id }
        self.vessel_features = {}

        # AIS thread & worker
        self.ais_thread = None
        self.ais_worker = None

    def initGui(self):
        icon = os.path.join(plugin_dir, "icon.png")
        self.action = QAction(QIcon(icon), "Vessel Tracker", self.iface.mainWindow())
        self.iface.addToolBarIcon(self.action)
        self.action.triggered.connect(self.run)

    def unload(self):
        # Stop any running AIS worker
        self._stop_ais_worker()

        # Remove the toolbar icon
        self.iface.removeToolBarIcon(self.action)
        del self.action

        # Remove the layer (if exists) from the project
        if self.layer and self.layer.isValid():
            QgsProject.instance().removeMapLayer(self.layer.id())
            self.layer = None

    def run(self):
        """
        1) Stop existing AISWorker (if any), clear the old layer.
        2) Pop up VesselInputDialog to let user enter MMSI / Name rows.
        3) Build mmsi_name_map, create a fresh layer, and start AISWorker.
        """

        # 1) If there is an existing AIS thread, stop it now:
        self._stop_ais_worker()

        # If there’s an old layer, remove it from the project so we can rebuild
        if self.layer and self.layer.isValid():
            QgsProject.instance().removeMapLayer(self.layer.id())
            self.layer = None
            self.vessel_features.clear()

        # 2) Show the vessel‐input dialog
        dlg = QDialog(self.iface.mainWindow())
        ui = Ui_VesselInputDialog()
        ui.setupUi(dlg)

        # Connect “Add” / “Remove” buttons
        ui.btnAdd.clicked.connect(lambda: self._on_add_row(ui))
        ui.btnRemove.clicked.connect(lambda: self._on_remove_selected_rows(ui))

        # OK / Cancel
        ui.buttonBox.accepted.connect(dlg.accept)
        ui.buttonBox.rejected.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            # User canceled — do nothing
            return

        # Build {mmsi: name} dict
        self.mmsi_name_map = self._read_table(ui)

        if not self.mmsi_name_map:
            self.iface.messageBar().pushMessage(
                "Vessel Tracker", "No MMSI/Name pairs entered – aborting.", level=1
            )
            return

        # 3) Create a brand‐new layer
        self._init_layer()

        # 4) Start AISWorker in its own QThread
        mmsi_list = list(self.mmsi_name_map.keys())
        self.ais_worker = AISWorker(mmsi_list)
        self.ais_thread = QThread()
        self.ais_worker.moveToThread(self.ais_thread)

        # Connect the signals BEFORE starting the thread
        self.ais_worker.vessel_received.connect(self.update_position)
        # (If you want, you can add finish/error signals here, but not strictly needed.)

        # When the thread starts, call the worker’s run()
        self.ais_thread.started.connect(self.ais_worker.run)

        self.ais_thread.start()

        self.iface.messageBar().pushMessage(
            "Vessel Tracker", f"Tracking {len(mmsi_list)} vessel(s)…", level=0, duration=3
        )

    def _on_add_row(self, ui):
        """Add a blank row to the QTableWidget."""
        table = ui.tableVessels
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(""))
        table.setItem(row, 1, QTableWidgetItem(""))

    def _on_remove_selected_rows(self, ui):
        """Remove all selected rows from the QTableWidget."""
        table = ui.tableVessels
        selected = table.selectionModel().selectedRows()
        for index in sorted(selected, key=lambda x: x.row(), reverse=True):
            table.removeRow(index.row())

    def _read_table(self, ui):
        """
        Read each row from ui.tableVessels and return {mmsi_str: name_str}.
        Skip any row where MMSI or Name is blank.
        """
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
        """
        Create an empty memory layer with fields: “MMSI” and “Name”.
        Enable labeling on the “Name” field.
        """
        uri = "Point?crs=EPSG:4326"
        self.layer = QgsVectorLayer(uri, "AIS Tracked Vessels", "memory")
        pr = self.layer.dataProvider()
        pr.addAttributes(
            [QgsField("MMSI", QVariant.String), QgsField("Name", QVariant.String)]
        )
        self.layer.updateFields()
        QgsProject.instance().addMapLayer(self.layer)

        # Enable labeling using “Name” attribute
        label_settings = QgsPalLayerSettings()
        label_settings.fieldName = "Name"
        label_settings.placement = Qgis.LabelPlacement.OverPoint
        label_settings.enabled = True

        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        self.layer.setLabeling(labeling)
        self.layer.setLabelsEnabled(True)
        self.layer.triggerRepaint()

        # Reset vessel_features map
        self.vessel_features = {}

    def update_position(self, mmsi, lat, lon):
        """
        Called whenever AISWorker emits a new (mmsi, lat, lon).
        We look up vessel_name = self.mmsi_name_map[mmsi], create or update
        a feature whose attributes are [mmsi, vessel_name].
        """
        vessel_name = self.mmsi_name_map.get(mmsi, mmsi)  # fallback to MMSI if no name
        point = QgsPointXY(lon, lat)
        geom = QgsGeometry.fromPointXY(point)

        # Use an editing transaction for all layer modifications
        with edit(self.layer):
            # Check if we are already tracking this vessel
            if mmsi in self.vessel_features:
                fid = self.vessel_features[mmsi]
                self.layer.changeGeometry(fid, geom)
            
            # This is the first time we've seen this vessel
            else:
                # 1. Create a new feature object
                feat = QgsFeature(self.layer.fields())
                feat.setGeometry(geom)
                feat.setAttributes([mmsi, vessel_name])

                # 2. Add the feature via the data provider
                pr = self.layer.dataProvider()
                success, added_features = pr.addFeatures([feat])

                # 3. CRITICAL: Check if adding succeeded and capture the REAL feature ID
                if success and added_features:
                    new_id = added_features[0].id()
                    self.vessel_features[mmsi] = new_id
                    self.layer.updateExtents() # Zoom to the new feature

        # The 'with edit' block handles all refreshes.
        
        msg = f"New AIS update - Vessel: {vessel_name}, LAT: {lat}, LON: {lon}, MMSI: {mmsi}"
        self.iface.messageBar().pushMessage(
            "Vessel Tracker", msg, level=0
        )

    def _stop_ais_worker(self):
        """
        If AISWorker + QThread exist, stop the worker, quit the thread, wait, and clean up.
        """
        if self.ais_worker:
            # Ask the worker to stop its loop
            try:
                self.ais_worker.stop()
            except Exception:
                pass

            # Disconnect its signal(s)
            try:
                self.ais_worker.vessel_received.disconnect(self.update_position)
            except Exception:
                pass

            self.ais_worker = None

        if self.ais_thread:
            self.ais_thread.quit()
            self.ais_thread.wait()
            self.ais_thread = None

