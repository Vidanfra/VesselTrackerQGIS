import os
from PyQt5.QtWidgets import QAction
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QThread
from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsField,
    QgsProject
)
from qgis.PyQt.QtCore import QVariant

from .ais_worker import AISWorker

plugin_dir = os.path.dirname(__file__)

class VesselTracker:
    def __init__(self, iface):
        self.iface = iface
        self.layer = None
        self.vessel_features = {}
        self.ais_thread = None
        self.ais_worker = None

    def initGui(self):
        icon = os.path.join(plugin_dir, 'icon.png')
        self.action = QAction(QIcon(icon), 'Vessel Tracker', self.iface.mainWindow())
        self.iface.addToolBarIcon(self.action)
        self.action.triggered.connect(self.run)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        del self.action

        if self.ais_worker:
            self.ais_worker.stop()
        if self.ais_thread:
            self.ais_thread.quit()
            self.ais_thread.wait()

        if self.layer:
            QgsProject.instance().removeMapLayer(self.layer.id())

    def run(self):
        self.iface.messageBar().pushMessage("Vessel Tracker", "AIS tracking started...", level=0)

        # Initialize vector layer
        if not self.layer:
            self.init_layer()

        # Set up AIS data thread
        self.ais_worker = AISWorker()
        self.ais_thread = QThread()
        self.ais_worker.moveToThread(self.ais_thread)
        self.ais_thread.started.connect(self.ais_worker.run)
        self.ais_worker.vessel_received.connect(self.update_position)
        self.ais_thread.start()

    def init_layer(self):
        self.layer = QgsVectorLayer("Point?crs=EPSG:4326", "AIS Vessels", "memory")
        pr = self.layer.dataProvider()
        pr.addAttributes([QgsField("MMSI", QVariant.String)])
        self.layer.updateFields()
        QgsProject.instance().addMapLayer(self.layer)
        self.vessel_features = {}

    def update_position(self, mmsi, lat, lon):
        pr = self.layer.dataProvider()
        point = QgsPointXY(lon, lat)
        geometry = QgsGeometry.fromPointXY(point)

        if mmsi in self.vessel_features:
            fid = self.vessel_features[mmsi]
            pr.changeGeometryValues({fid: geometry})
        else:
            feature = QgsFeature(self.layer.fields())
            feature.setGeometry(geometry)
            feature.setAttributes([mmsi])
            pr.addFeatures([feature])
            self.layer.updateExtents()
            self.vessel_features[mmsi] = feature.id()

        self.layer.triggerRepaint()
