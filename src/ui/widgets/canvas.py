from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

class MatplotlibCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, dpi=100):
        self.fig = Figure(figsize=(5, 4), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        super(MatplotlibCanvas, self).__init__(self.fig)
        self.fig.tight_layout()