from PyQt6.QtCore import Qt, QObject, QRect, QEvent
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QCursor

class ResizeEventFilter(QObject):
    """
    Reliable application-wide event filter to handle frameless window resizing.
    Intercepts mouse events before they reach child widgets if they occur in the margin.
    """
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.resize_edges = None
        self.drag_pos = None
        self.start_geo = None
        self.BORDER = 8

    def edge_at(self, global_pos):
        if self.window.isMaximized():
            return Qt.Edge(0)
            
        local = self.window.mapFromGlobal(global_pos)
        edges = Qt.Edge(0)
        
        if local.x() <= self.BORDER:
            edges |= Qt.Edge.LeftEdge
        elif local.x() >= self.window.width() - self.BORDER:
            edges |= Qt.Edge.RightEdge

        if local.y() <= self.BORDER:
            edges |= Qt.Edge.TopEdge
        elif local.y() >= self.window.height() - self.BORDER:
            edges |= Qt.Edge.BottomEdge
            
        return edges

    def get_cursor_shape(self, edges):
        if not edges:
            return None

        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)

        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        elif (left and bottom) or (right and top):
            return Qt.CursorShape.SizeBDiagCursor
        elif left or right:
            return Qt.CursorShape.SizeHorCursor
        elif top or bottom:
            return Qt.CursorShape.SizeVerCursor
            
        return None

    def update_cursor(self, edges):
        shape = self.get_cursor_shape(edges)
        current = QApplication.overrideCursor()
        
        if shape is None:
            if current is not None:
                QApplication.restoreOverrideCursor()
        else:
            if current is None:
                QApplication.setOverrideCursor(QCursor(shape))
            elif current.shape() != shape:
                QApplication.changeOverrideCursor(QCursor(shape))

    def eventFilter(self, obj, event):
        is_our_widget = (obj is self.window) or (isinstance(obj, QWidget) and self.window.isAncestorOf(obj))
        
        if not is_our_widget:
            return False

        # Track hover moves to ensure cursor updates even when no button is pressed
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            if self.resize_edges is None:
                global_pos = QCursor.pos()
                edges = self.edge_at(global_pos)
                self.update_cursor(edges)
            elif event.type() == QEvent.Type.MouseMove:
                # Actively dragging
                global_pos = event.globalPosition().toPoint()
                self.manual_resize(global_pos)
                return True

        elif event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                global_pos = event.globalPosition().toPoint()
                edges = self.edge_at(global_pos)
                if edges:
                    self.resize_edges = edges
                    self.drag_pos = global_pos
                    self.start_geo = self.window.geometry()
                    return True # Consume the event

        elif event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                if self.resize_edges is not None:
                    self.resize_edges = None
                    self.drag_pos = None
                    self.start_geo = None
                    
                    global_pos = event.globalPosition().toPoint()
                    self.update_cursor(self.edge_at(global_pos))
                    return True # Consume the event

        elif event.type() == QEvent.Type.Leave:
            # Reset cursor if leaving the window while not dragging
            if self.resize_edges is None:
                if QApplication.overrideCursor() is not None:
                    QApplication.restoreOverrideCursor()

        return False

    def manual_resize(self, global_pos):
        delta = global_pos - self.drag_pos
        geo = QRect(self.start_geo)

        min_w = max(self.window.minimumWidth(), 220)
        min_h = max(self.window.minimumHeight(), 180)

        if self.resize_edges & Qt.Edge.RightEdge:
            geo.setWidth(max(min_w, self.start_geo.width() + delta.x()))

        if self.resize_edges & Qt.Edge.BottomEdge:
            geo.setHeight(max(min_h, self.start_geo.height() + delta.y()))

        if self.resize_edges & Qt.Edge.LeftEdge:
            new_w = max(min_w, self.start_geo.width() - delta.x())
            geo.setLeft(self.start_geo.left() + (self.start_geo.width() - new_w))
            geo.setWidth(new_w)

        if self.resize_edges & Qt.Edge.TopEdge:
            new_h = max(min_h, self.start_geo.height() - delta.y())
            geo.setTop(self.start_geo.top() + (self.start_geo.height() - new_h))
            geo.setHeight(new_h)

        self.window.setGeometry(geo)