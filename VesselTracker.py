import os
from PyQt5.QtWidgets import QAction, QDialog, QTableWidgetItem
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QThread
from qgis.core import (
    Qgis,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsField,
    QgsProject,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QVariant

from .ais_worker import AISWorker
from .vessel_input_dialog import Ui_VesselInputDialog

plugin_dir = os.path.dirname(__file__)


class VesselTracker:
    def __init__(self, iface):
        self.iface = iface

        # will hold the in‐memory layer
        self.layer = None

        # mapping: { mmsi_string: vessel_name_string }
        self.mmsi_name_map = {}

        # keep track of feature IDs by MMSI
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
        self.iface.removeToolBarIcon(self.action)
        del self.action

        # Stop AIS thread if it’s running
        if self.ais_worker:
            self.ais_worker.stop()
        if self.ais_thread:
            self.ais_thread.quit()
            self.ais_thread.wait()

        # Remove the layer from the project
        if self.layer:
            QgsProject.instance().removeMapLayer(self.layer.id())

    def run(self):
        """
        1) Pop up the VesselInputDialog to let the user type MMSI/Name rows.
        2) If OK clicked, store self.mmsi_name_map and start AISWorker.
        """
        # 1) Show dialog
        dlg = QDialog(self.iface.mainWindow())
        ui = Ui_VesselInputDialog()
        ui.setupUi(dlg)

        # Hook up the Add / Remove buttons
        ui.btnAdd.clicked.connect(lambda: self._on_add_row(ui))
        ui.btnRemove.clicked.connect(lambda: self._on_remove_selected_rows(ui))

        # When user clicks OK or Cancel
        ui.buttonBox.accepted.connect(dlg.accept)
        ui.buttonBox.rejected.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            return  # user cancelled

        # 2) Build the mmsi→name dictionary from the table
        self.mmsi_name_map = self._read_table(ui)

        if not self.mmsi_name_map:
            self.iface.messageBar().pushMessage(
                "Vessel Tracker",
                "No MMSI/Name pairs entered – aborting.",
                level=1,
            )
            return

        self.iface.messageBar().pushMessage(
            "Vessel Tracker", "Starting AIS tracking…", level=0
        )

        # 3) Initialize (or reuse) the memory layer
        if not self.layer:
            self._init_layer()

        # 4) Set up AISWorker in its own thread, passing the mmsi_name_map
        self.ais_worker = AISWorker(list(self.mmsi_name_map.keys())) # AIS worker needs a vector of the mmsi codes (str format)
        self.ais_thread = QThread()
        self.ais_worker.moveToThread(self.ais_thread)
        self.ais_thread.started.connect(self.ais_worker.run)

        self.iface.messageBar().pushMessage(
            "Vessel Tracker", "Waiting AIS update... (it can take several minutes)", level=0
        )

        # AISWorker will emit (mmsi_str, lat, lon) whenever a PositionReport arrives.
        # We then look up the vessel name in self.mmsi_name_map.
        self.ais_worker.vessel_received.connect(self.update_position)
        self.ais_thread.start()

    def _on_add_row(self, ui):
        """Add an empty row to the QTableWidget."""
        table = ui.tableVessels
        row_count = table.rowCount()
        table.insertRow(row_count)
        # Optionally set placeholder cells
        table.setItem(row_count, 0, QTableWidgetItem(""))
        table.setItem(row_count, 1, QTableWidgetItem(""))

    def _on_remove_selected_rows(self, ui):
        """Remove each selected row from the QTableWidget."""
        table = ui.tableVessels
        selected = table.selectionModel().selectedRows()
        # Remove from bottom to top so indices don’t shift
        for index in sorted(selected, key=lambda x: x.row(), reverse=True):
            table.removeRow(index.row())

    def _read_table(self, ui):
        """
        Reads every row of ui.tableVessels and returns a dict:
            { mmsi_str: name_str, … }.

        Skips any row where MMSI or Name is empty.
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
        Create a memory layer with two fields: MMSI (string) and Name (string).
        Enable labeling on the 'Name' field.
        """
        uri = "Point?crs=EPSG:4326"
        self.layer = QgsVectorLayer(uri, "AIS Tracked Vessels", "memory")
        pr = self.layer.dataProvider()
        pr.addAttributes(
            [QgsField("MMSI", QVariant.String), QgsField("Name", QVariant.String)]
        )
        self.layer.updateFields()
        QgsProject.instance().addMapLayer(self.layer)

        # Enable labeling by the "Name" field
        labeling = QgsPalLayerSettings()
        labeling.fieldName = "Name"
        labeling.placement = Qgis.LabelPlacement.OverPoint  # Updated placement mode
        labeling.enabled = True
        self.layer.setLabelsEnabled(True)
        self.layer.setLabeling(QgsVectorLayerSimpleLabeling(labeling))
        self.layer.triggerRepaint()

        self.vessel_features = {}

    def update_position(self, mmsi, lat, lon):
        """
        Called whenever AISWorker emits a new (mmsi, lat, lon).
        We look up vessel_name = self.mmsi_name_map[mmsi], create or update
        a feature whose attributes are [mmsi, vessel_name].
        """
        vessel_name = self.mmsi_name_map.get(mmsi, mmsi)  # fallback to MMSI if no name

        pr = self.layer.dataProvider()
        point = QgsPointXY(lon, lat)
        geom = QgsGeometry.fromPointXY(point)

        if mmsi in self.vessel_features:
            fid = self.vessel_features[mmsi]
            # Only geometry needs updating if the name never changes
            pr.changeGeometryValues({fid: geom})
        else:
            feat = QgsFeature(self.layer.fields())
            feat.setGeometry(geom)
            feat.setAttributes([mmsi, vessel_name])
            pr.addFeatures([feat])
            self.layer.updateExtents()
            self.vessel_features[mmsi] = feat.id()

        msg = f"New AIS update - Vessel: {vessel_name}, LAT: {lat}, LON: {lon}, MMSI: {mmsi}"
        self.iface.messageBar().pushMessage(
            "Vessel Tracker", msg, level=0
        )
        self.layer.triggerRepaint()
