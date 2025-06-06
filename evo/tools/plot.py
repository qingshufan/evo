# -*- coding: UTF8 -*-
"""
some plotting functionality for different tasks
author: Michael Grupp

This file is part of evo (github.com/MichaelGrupp/evo).

evo is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

evo is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with evo.  If not, see <http://www.gnu.org/licenses/>.
"""

import copy
import os
import collections
import collections.abc
import itertools
import logging
import pickle
import typing
from enum import Enum, unique
from pathlib import Path

import numpy as np
import matplotlib as mpl
import matplotlib.cm as cm
import matplotlib.pyplot as plt
import mpl_toolkits.mplot3d.art3d as art3d
import seaborn as sns
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.backend_bases import FigureCanvasBase
from matplotlib.collections import LineCollection
from matplotlib.ticker import FuncFormatter
from matplotlib.transforms import Affine2D, Bbox

from evo import EvoException
from evo.tools import user
from evo.tools._typing import PathStr
from evo.tools.settings import SETTINGS, SettingsContainer
from evo.core import trajectory
from evo.core.units import Unit, LENGTH_UNITS, METER_SCALE_FACTORS

logger = logging.getLogger(__name__)

ListOrArray = typing.Union[typing.Sequence[float], np.ndarray]


def apply_settings(settings: SettingsContainer = SETTINGS):
    """
    Configure matplotlib and seaborn according to package settings.
    """
    mpl.use(settings.plot_backend)

    if settings.plot_seaborn_enabled:
        # TODO: 'color_codes=False' to work around this bug:
        # https://github.com/mwaskom/seaborn/issues/1546
        sns.set(style=settings.plot_seaborn_style,
                font=settings.plot_fontfamily,
                font_scale=settings.plot_fontscale, color_codes=False,
                palette=settings.plot_seaborn_palette)

    mpl.rcParams.update({
        "legend.loc": settings.plot_legend_loc,
        "lines.linewidth": settings.plot_linewidth,
        "text.usetex": settings.plot_usetex,
        # NOTE: don't call tight_layout manually anymore. See warning here:
        # https://matplotlib.org/stable/users/explain/axes/constrainedlayout_guide.html
        "figure.constrained_layout.use": True,
        "font.family": settings.plot_fontfamily,
        "pgf.texsystem": settings.plot_texsystem,
        "savefig.bbox": "tight",
    })
    if "xkcd" in settings:
        plt.xkcd()


apply_settings(SETTINGS)


class PlotException(EvoException):
    pass


@unique
class PlotMode(Enum):
    xy = "xy"
    xz = "xz"
    yx = "yx"
    yz = "yz"
    zx = "zx"
    zy = "zy"
    xyz = "xyz"


@unique
class Viewport(Enum):
    update = "update"
    keep_unchanged = "keep_unchanged"
    zoom_to_map = "zoom_to_map"


class PlotCollection:
    def __init__(self, title: str = "",
                 deserialize: typing.Optional[PathStr] = None):
        self.title = " ".join(title.splitlines())  # one line title
        self.figures = collections.OrderedDict()  # remember placement order
        # hack to avoid premature garbage collection when serializing with Qt
        # initialized later in tabbed_{qt, tk}_window
        self.root_window: typing.Optional[typing.Any] = None
        if deserialize is not None:
            logger.debug("Deserializing PlotCollection from %s ...",
                         deserialize)
            self.figures = pickle.load(open(deserialize, 'rb'))

    def __str__(self) -> str:
        return self.title + " (" + str(len(self.figures)) + " figure(s))"

    def add_figure(self, name: str, fig: Figure) -> None:
        self.figures[name] = fig

    @staticmethod
    def _bind_mouse_events_to_canvas(axes: Axes3D, canvas: FigureCanvasBase):
        axes.mouse_init()
        # Event binding was possible through mouse_init() up to matplotlib 3.2.
        # In 3.3.0 this was moved, so we are forced to do it here.
        if mpl.__version__ >= "3.3.0":
            canvas.mpl_connect("button_press_event", axes._button_press)
            canvas.mpl_connect("button_release_event", axes._button_release)
            canvas.mpl_connect("motion_notify_event", axes._on_move)

    def tabbed_qt5_window(self) -> None:
        from PyQt5 import QtGui, QtWidgets
        from matplotlib.backends.backend_qt5agg import (FigureCanvasQTAgg,
                                                        NavigationToolbar2QT)
        # mpl backend can already create instance
        # https://stackoverflow.com/a/40031190
        app = QtGui.QGuiApplication.instance()
        if app is None:
            app = QtWidgets.QApplication([self.title])
        self.root_window = QtWidgets.QTabWidget()
        self.root_window.setWindowTitle(self.title)
        sizes = [(0, 0)]
        for name, fig in self.figures.items():
            tab = QtWidgets.QWidget(self.root_window)
            tab.canvas = FigureCanvasQTAgg(fig)
            vbox = QtWidgets.QVBoxLayout(tab)
            vbox.addWidget(tab.canvas)
            toolbar = NavigationToolbar2QT(tab.canvas, tab)
            vbox.addWidget(toolbar)
            tab.setLayout(vbox)
            for axes in fig.get_axes():
                if isinstance(axes, Axes3D):
                    # must explicitly allow mouse dragging for 3D plots
                    self._bind_mouse_events_to_canvas(axes, tab.canvas)
            self.root_window.addTab(tab, name)
            sizes.append(tab.canvas.get_width_height())
        # Resize window to avoid clipped axes.
        self.root_window.resize(*max(sizes))
        self.root_window.show()
        app.exec_()

    def tabbed_tk_window(self) -> None:
        from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg,
                                                       NavigationToolbar2Tk)
        import tkinter
        from tkinter import ttk
        self.root_window = tkinter.Tk()
        self.root_window.title(self.title)
        # quit if the window is deleted
        self.root_window.protocol("WM_DELETE_WINDOW", self.root_window.quit)
        nb = ttk.Notebook(self.root_window)
        nb.grid(row=1, column=0, sticky='NESW')
        for name, fig in self.figures.items():
            tab = ttk.Frame(nb)
            canvas = FigureCanvasTkAgg(self.figures[name], master=tab)
            canvas.draw()
            canvas.get_tk_widget().pack(side=tkinter.TOP, fill=tkinter.BOTH,
                                        expand=True)
            toolbar = NavigationToolbar2Tk(canvas, tab)
            toolbar.update()
            canvas._tkcanvas.pack(side=tkinter.TOP, fill=tkinter.BOTH,
                                  expand=True)
            for axes in fig.get_axes():
                if isinstance(axes, Axes3D):
                    # must explicitly allow mouse dragging for 3D plots
                    self._bind_mouse_events_to_canvas(axes, canvas)
            nb.add(tab, text=name)
        nb.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=True)
        self.root_window.mainloop()
        self.root_window.destroy()

    def show(self) -> None:
        if len(self.figures.keys()) == 0:
            return
        if not SETTINGS.plot_split:
            if SETTINGS.plot_backend.lower() == "qt5agg":
                self.tabbed_qt5_window()
            elif SETTINGS.plot_backend.lower() == "tkagg":
                self.tabbed_tk_window()
            else:
                plt.show()
        else:
            plt.show()

    def close(self) -> None:
        for name, fig in self.figures.items():
            plt.close(fig)

    def serialize(self, dest: str, confirm_overwrite: bool = True) -> None:
        logger.debug("Serializing PlotCollection to " + dest + "...")
        if confirm_overwrite and not user.check_and_confirm_overwrite(dest):
            return
        else:
            pickle.dump(self.figures, open(dest, 'wb'))

    def export(self, file_path: str, confirm_overwrite: bool = True) -> None:
        base, ext = os.path.splitext(file_path)
        if ext == ".pdf" and not SETTINGS.plot_split:
            if confirm_overwrite and not user.check_and_confirm_overwrite(
                    file_path):
                return
            import matplotlib.backends.backend_pdf
            pdf = matplotlib.backends.backend_pdf.PdfPages(file_path)
            for name, fig in self.figures.items():
                pdf.savefig(fig)
            pdf.close()
            logger.info("Plots saved to " + file_path)
        else:
            for name, fig in self.figures.items():
                dest = base + '_' + name + ext
                if confirm_overwrite and not user.check_and_confirm_overwrite(
                        dest):
                    return
                fig.savefig(dest)
                logger.info("Plot saved to " + dest)


def set_aspect_equal(ax: Axes) -> None:
    """
    kudos to https://stackoverflow.com/a/35126679
    :param ax: matplotlib 3D axes object
    """
    if not isinstance(ax, Axes3D):
        ax.set_aspect("equal")
        return

    xlim = ax.get_xlim3d()
    ylim = ax.get_ylim3d()
    zlim = ax.get_zlim3d()

    from numpy import mean
    xmean = mean(xlim)
    ymean = mean(ylim)
    zmean = mean(zlim)

    plot_radius = max([
        abs(lim - mean_)
        for lims, mean_ in ((xlim, xmean), (ylim, ymean), (zlim, zmean))
        for lim in lims
    ])

    ax.set_xlim3d([xmean - plot_radius, xmean + plot_radius])
    ax.set_ylim3d([ymean - plot_radius, ymean + plot_radius])
    ax.set_zlim3d([zmean - plot_radius, zmean + plot_radius])


def _get_length_formatter(length_unit: Unit) -> FuncFormatter:
    def formatter(x, _):
        return "{0:g}".format(x / METER_SCALE_FACTORS[length_unit])

    return FuncFormatter(formatter)


def prepare_axis(fig: Figure, plot_mode: PlotMode = PlotMode.xy,
                 subplot_arg: int = 111,
                 length_unit: Unit = Unit.meters) -> Axes:
    """
    prepares an axis according to the plot mode (for trajectory plotting)
    :param fig: matplotlib figure object
    :param plot_mode: PlotMode
    :param subplot_arg: optional if using subplots - the subplot id (e.g. '122')
    :param length_unit: Set to another length unit than meters to scale plots.
                        Note that trajectory data is still expected in meters.
    :return: the matplotlib axis
    """
    if length_unit not in LENGTH_UNITS:
        raise PlotException(f"{length_unit} is not a length unit")

    if plot_mode == PlotMode.xyz:
        ax: Axes3D = fig.add_subplot(subplot_arg, projection="3d")
        # Zoom can help against clipping labels. See issue #718.
        ax.set_box_aspect(None, zoom=SETTINGS.plot_3d_zoom)
    else:
        ax = fig.add_subplot(subplot_arg)
    if plot_mode in {PlotMode.xy, PlotMode.xz, PlotMode.xyz}:
        xlabel = f"$x$ [{length_unit.value}]"
    elif plot_mode in {PlotMode.yz, PlotMode.yx}:
        xlabel = f"$y$ [{length_unit.value}]"
    else:
        xlabel = f"$z$ [{length_unit.value}]"
    if plot_mode in {PlotMode.xy, PlotMode.zy, PlotMode.xyz}:
        ylabel = f"$y$ [{length_unit.value}]"
    elif plot_mode in {PlotMode.zx, PlotMode.yx}:
        ylabel = f"$x$ [{length_unit.value}]"
    else:
        ylabel = f"$z$ [{length_unit.value}]"
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if plot_mode == PlotMode.xyz and isinstance(ax, Axes3D):
        ax.set_zlabel(f'$z$ [{length_unit.value}]')
    if SETTINGS.plot_invert_xaxis:
        plt.gca().invert_xaxis()
    if SETTINGS.plot_invert_yaxis:
        plt.gca().invert_yaxis()
    if not SETTINGS.plot_show_axis:
        ax.set_axis_off()

    if length_unit is not Unit.meters:
        formatter = _get_length_formatter(length_unit)
        ax.xaxis.set_major_formatter(formatter)
        ax.yaxis.set_major_formatter(formatter)
        if plot_mode == PlotMode.xyz and isinstance(ax, Axes3D):
            ax.zaxis.set_major_formatter(formatter)

    return ax


def plot_mode_to_idx(
        plot_mode: PlotMode) -> typing.Tuple[int, int, typing.Optional[int]]:
    if plot_mode == PlotMode.xy or plot_mode == PlotMode.xyz:
        x_idx = 0
        y_idx = 1
    elif plot_mode == PlotMode.xz:
        x_idx = 0
        y_idx = 2
    elif plot_mode == PlotMode.yx:
        x_idx = 1
        y_idx = 0
    elif plot_mode == PlotMode.yz:
        x_idx = 1
        y_idx = 2
    elif plot_mode == PlotMode.zx:
        x_idx = 2
        y_idx = 0
    elif plot_mode == PlotMode.zy:
        x_idx = 2
        y_idx = 1
    z_idx = 2 if plot_mode == PlotMode.xyz else None
    return x_idx, y_idx, z_idx


def add_start_end_markers(ax: Axes, plot_mode: PlotMode,
                          traj: trajectory.PosePath3D, start_symbol: str = "o",
                          start_color="black", end_symbol: str = "x",
                          end_color="black", alpha: float = 1.0,
                          traj_name: typing.Optional[str] = None):
    if traj.num_poses == 0:
        return
    start = traj.positions_xyz[0]
    end = traj.positions_xyz[-1]
    x_idx, y_idx, z_idx = plot_mode_to_idx(plot_mode)
    start_coords = [start[x_idx], start[y_idx]]
    end_coords = [end[x_idx], end[y_idx]]
    if plot_mode == PlotMode.xyz:
        start_coords.append(start[z_idx])
        end_coords.append(end[z_idx])
    start_label = f"Start of {traj_name}" if traj_name else None
    end_label = f"End of {traj_name}" if traj_name else None
    # TODO: mypy doesn't deal well with * unpack here for some reason.
    ax.scatter(*start_coords, marker=start_symbol, color=start_color,
               alpha=alpha, label=start_label)  # type: ignore[misc]
    ax.scatter(*end_coords, marker=end_symbol, color=end_color, alpha=alpha,
               label=end_label)  # type: ignore[misc]


def traj(ax: Axes, plot_mode: PlotMode, traj: trajectory.PosePath3D,
         style: str = '-', color='black', label: str = "", alpha: float = 1.0,
         plot_start_end_markers: bool = False) -> None:
    """
    plot a path/trajectory based on xyz coordinates into an axis
    :param ax: the matplotlib axis
    :param plot_mode: PlotMode
    :param traj: trajectory.PosePath3D or trajectory.PoseTrajectory3D object
    :param style: matplotlib line style
    :param color: matplotlib color
    :param label: label (for legend)
    :param alpha: alpha value for transparency
    :param plot_start_end_markers: Mark the start and end of a trajectory
                                   with a symbol.
    """
    x_idx, y_idx, z_idx = plot_mode_to_idx(plot_mode)
    x = traj.positions_xyz[:, x_idx]
    y = traj.positions_xyz[:, y_idx]
    if plot_mode == PlotMode.xyz:
        z = traj.positions_xyz[:, z_idx]
        ax.plot(x, y, z, style, color=color, label=label, alpha=alpha)
    else:
        ax.plot(x, y, style, color=color, label=label, alpha=alpha)
    if SETTINGS.plot_xyz_realistic:
        set_aspect_equal(ax)
    if label and SETTINGS.plot_show_legend:
        ax.legend(frameon=True)
    if plot_start_end_markers:
        add_start_end_markers(ax, plot_mode, traj, start_color=color,
                              end_color=color, alpha=alpha)


def colored_line_collection(
    xyz: np.ndarray, colors, plot_mode: PlotMode = PlotMode.xy,
    linestyles: str = "solid", step: int = 1, alpha: float = 1.
) -> typing.Union[LineCollection, art3d.LineCollection]:
    if step > 1 and len(xyz) / step != len(colors):
        raise PlotException(
            "color values don't have correct length: %d vs. %d" %
            (len(xyz) / step, len(colors)))
    x_idx, y_idx, z_idx = plot_mode_to_idx(plot_mode)
    xs = [[x_1, x_2]
          for x_1, x_2 in zip(xyz[:-1:step, x_idx], xyz[1::step, x_idx])]
    ys = [[x_1, x_2]
          for x_1, x_2 in zip(xyz[:-1:step, y_idx], xyz[1::step, y_idx])]
    if plot_mode == PlotMode.xyz:
        zs = [[x_1, x_2]
              for x_1, x_2 in zip(xyz[:-1:step, z_idx], xyz[1::step, z_idx])]
        segs_3d = [list(zip(x, y, z)) for x, y, z in zip(xs, ys, zs)]
        line_collection = art3d.Line3DCollection(segs_3d, colors=colors,
                                                 alpha=alpha,
                                                 linestyles=linestyles)
    else:
        segs_2d = [list(zip(x, y)) for x, y in zip(xs, ys)]
        line_collection = LineCollection(segs_2d, colors=colors, alpha=alpha,
                                         linestyle=linestyles)
    return line_collection


def traj_colormap(ax: Axes, traj: trajectory.PosePath3D, array: ListOrArray,
                  plot_mode: PlotMode, min_map: float, max_map: float,
                  title: str = "",
                  fig: typing.Optional[mpl.figure.Figure] = None,
                  plot_start_end_markers: bool = False) -> None:
    """
    color map a path/trajectory in xyz coordinates according to
    an array of values
    :param ax: plot axis
    :param traj: trajectory.PosePath3D or trajectory.PoseTrajectory3D object
    :param array: Nx1 array of values used for color mapping
    :param plot_mode: PlotMode
    :param min_map: lower bound value for color mapping
    :param max_map: upper bound value for color mapping
    :param title: plot title
    :param fig: plot figure. Obtained with plt.gcf() if none is specified
    :param plot_start_end_markers: Mark the start and end of a trajectory
                                   with a symbol.
    """
    pos = traj.positions_xyz
    norm = mpl.colors.Normalize(vmin=min_map, vmax=max_map, clip=True)
    mapper = cm.ScalarMappable(
        norm=norm,
        cmap=SETTINGS.plot_trajectory_cmap)  # cm.*_r is reversed cmap
    mapper.set_array(array)
    # TODO: why does mypy complain about 'a' here, float is fine?
    colors = [mapper.to_rgba(a) for a in array]  # type: ignore[arg-type]
    line_collection = colored_line_collection(pos, colors, plot_mode)
    ax.add_collection(line_collection)
    ax.autoscale_view(True, True, True)
    if plot_mode == PlotMode.xyz and isinstance(ax, Axes3D):
        min_z = np.amin(traj.positions_xyz[:, 2])
        max_z = np.amax(traj.positions_xyz[:, 2])
        # Only adjust limits if there are z values to suppress mpl warning.
        if min_z != max_z:
            ax.set_zlim(min_z, max_z)
    if SETTINGS.plot_xyz_realistic:
        set_aspect_equal(ax)
    if fig is None:
        fig = plt.gcf()
    cbar = fig.colorbar(
        mapper, ticks=[min_map, (max_map - (max_map - min_map) / 2), max_map],
        ax=ax)
    cbar.ax.set_yticklabels([
        "{0:0.3f}".format(min_map),
        "{0:0.3f}".format(max_map - (max_map - min_map) / 2),
        "{0:0.3f}".format(max_map)
    ])
    if title:
        ax.set_title(title)
    if SETTINGS.plot_show_legend:
        ax.legend(frameon=True)
    if plot_start_end_markers:
        add_start_end_markers(ax, plot_mode, traj, start_color=colors[0],
                              end_color=colors[-1])


def draw_coordinate_axes(ax: Axes, traj: trajectory.PosePath3D,
                         plot_mode: PlotMode, marker_scale: float = 0.1,
                         x_color="r", y_color="g", z_color="b") -> None:
    """
    Draws a coordinate frame axis for each pose of a trajectory.
    :param ax: plot axis
    :param traj: trajectory.PosePath3D or trajectory.PoseTrajectory3D object
    :param plot_mode: PlotMode value
    :param marker_scale: affects the size of the marker (1. * marker_scale)
    :param x_color: color of the x-axis
    :param y_color: color of the y-axis
    :param z_color: color of the z-axis
    """
    if marker_scale <= 0:
        return

    unit_x = np.array([1 * marker_scale, 0, 0, 1])
    unit_y = np.array([0, 1 * marker_scale, 0, 1])
    unit_z = np.array([0, 0, 1 * marker_scale, 1])

    # Transform start/end vertices of each axis to global frame.
    x_vertices = np.array([[p[:3, 3], p.dot(unit_x)[:3]]
                           for p in traj.poses_se3])
    y_vertices = np.array([[p[:3, 3], p.dot(unit_y)[:3]]
                           for p in traj.poses_se3])
    z_vertices = np.array([[p[:3, 3], p.dot(unit_z)[:3]]
                           for p in traj.poses_se3])

    n = traj.num_poses
    # Concatenate all line segment vertices in order x, y, z.
    vertices = np.concatenate((x_vertices, y_vertices, z_vertices)).reshape(
        (n * 2 * 3, 3))
    # Concatenate all colors per line segment in order x, y, z.
    colors = np.array(n * [x_color] + n * [y_color] + n * [z_color])

    markers = colored_line_collection(vertices, colors, plot_mode, step=2)
    ax.add_collection(markers)


def draw_correspondence_edges(ax: Axes, traj_1: trajectory.PosePath3D,
                              traj_2: trajectory.PosePath3D,
                              plot_mode: PlotMode, style: str = '-',
                              color="black", alpha: float = 1.) -> None:
    """
    Draw edges between corresponding poses of two trajectories.
    Trajectories must be synced, i.e. having the same number of poses.
    :param ax: plot axis
    :param traj_{1,2}: trajectory.PosePath3D or trajectory.PoseTrajectory3D
    :param plot_mode: PlotMode value
    :param style: matplotlib line style
    :param color: matplotlib color
    :param alpha: alpha value for transparency
    """
    if not traj_1.num_poses == traj_2.num_poses:
        raise PlotException(
            "trajectories must have same length to draw pose correspondences"
            " - try to synchronize them first")
    n = traj_1.num_poses
    interweaved_positions = np.empty((n * 2, 3))
    interweaved_positions[0::2, :] = traj_1.positions_xyz
    interweaved_positions[1::2, :] = traj_2.positions_xyz
    color="red"
    colors = np.array(n * [color])
    markers = colored_line_collection(interweaved_positions, colors, plot_mode,
                                      step=2, alpha=alpha, linestyles=style)
    markers.set_label("difference")
    ax.add_collection(markers)
    ax.legend(frameon=True)


def traj_xyz(axarr: np.ndarray, traj: trajectory.PosePath3D, style: str = '-',
             color='black', label: str = "", alpha: float = 1.0,
             start_timestamp: typing.Optional[float] = None,
             length_unit: Unit = Unit.meters) -> None:
    """
    plot a path/trajectory based on xyz coordinates into an axis
    :param axarr: an axis array (for x, y & z)
                  e.g. from 'fig, axarr = plt.subplots(3)'
    :param traj: trajectory.PosePath3D or trajectory.PoseTrajectory3D object
    :param style: matplotlib line style
    :param color: matplotlib color
    :param label: label (for legend)
    :param alpha: alpha value for transparency
    :param start_timestamp: optional start time of the reference
                            (for x-axis alignment)
    :param length_unit: Set to another length unit than meters to scale plots.
                        Note that trajectory data is still expected in meters.
    """
    if len(axarr) != 3:
        raise PlotException("expected an axis array with 3 subplots - got " +
                            str(len(axarr)))
    if length_unit not in LENGTH_UNITS:
        raise PlotException(f"{length_unit} is not a length unit")

    if isinstance(traj, trajectory.PoseTrajectory3D):
        if start_timestamp:
            x = traj.timestamps - start_timestamp
        else:
            x = traj.timestamps
        xlabel = "$t$ (s)"
    else:
        x = np.arange(0., len(traj.positions_xyz), dtype=float)
        xlabel = "index"
    ylabels = [
        f"$x$ ({length_unit.value})", f"$y$ ({length_unit.value})",
        f"$z$ ({length_unit.value})"
    ]
    for i in range(0, 3):
        if length_unit is not Unit.meters:
            formatter = _get_length_formatter(length_unit)
            axarr[i].yaxis.set_major_formatter(formatter)
        axarr[i].plot(x, traj.positions_xyz[:, i], style, color=color,
                      label=label, alpha=alpha)
        axarr[i].set_ylabel(ylabels[i])
    axarr[2].set_xlabel(xlabel)
    if label and SETTINGS.plot_show_legend:
        axarr[0].legend(frameon=True)


def traj_rpy(axarr: np.ndarray, traj: trajectory.PosePath3D, style: str = '-',
             color='black', label: str = "", alpha: float = 1.0,
             start_timestamp: typing.Optional[float] = None) -> None:
    """
    plot a path/trajectory's Euler RPY angles into an axis
    :param axarr: an axis array (for R, P & Y)
                  e.g. from 'fig, axarr = plt.subplots(3)'
    :param traj: trajectory.PosePath3D or trajectory.PoseTrajectory3D object
    :param style: matplotlib line style
    :param color: matplotlib color
    :param label: label (for legend)
    :param alpha: alpha value for transparency
    :param start_timestamp: optional start time of the reference
                            (for x-axis alignment)
    """
    if len(axarr) != 3:
        raise PlotException("expected an axis array with 3 subplots - got " +
                            str(len(axarr)))
    angles = traj.get_orientations_euler(SETTINGS.euler_angle_sequence)
    if isinstance(traj, trajectory.PoseTrajectory3D):
        if start_timestamp:
            x = traj.timestamps - start_timestamp
        else:
            x = traj.timestamps
        xlabel = "$t$ (s)"
    else:
        x = np.arange(0., len(angles), dtype=float)
        xlabel = "index"
    ylabels = ["$roll$ (deg)", "$pitch$ (deg)", "$yaw$ (deg)"]
    for i in range(0, 3):
        axarr[i].plot(x, np.rad2deg(angles[:, i]), style, color=color,
                      label=label, alpha=alpha)
        axarr[i].set_ylabel(ylabels[i])
    axarr[2].set_xlabel(xlabel)
    if label and SETTINGS.plot_show_legend:
        axarr[0].legend(frameon=True)


def speeds(ax: Axes, traj: trajectory.PoseTrajectory3D, style: str = '-',
           color="black", label: str = "", alpha: float = 1.,
           start_timestamp: typing.Optional[float] = None):
    """
    Plots the speed between poses of a trajectory.
    Note that a speed value is shown at the timestamp of the newer pose.
    :param ax: matplotlib axis
    :param traj: trajectory.PoseTrajectory3D object
    :param style: matplotlib line style
    :param color: matplotlib color
    :param label: label (for legend)
    :param alpha: alpha value for transparency
    :param start_timestamp: optional start time of the reference
                            (for x-axis alignment)
    """
    if not isinstance(traj, trajectory.PoseTrajectory3D):
        raise PlotException("speeds can only be plotted with trajectories")
    if start_timestamp:
        timestamps = traj.timestamps - start_timestamp
    else:
        timestamps = traj.timestamps
    ax.plot(timestamps[1:], traj.speeds, style, color=color, alpha=alpha,
            label=label)
    ax.set_xlabel("$t$ (s)")
    ax.set_ylabel("$v$ (m/s)")
    if label and SETTINGS.plot_show_legend:
        ax.legend(frameon=True)


def trajectories(fig_or_ax: typing.Union[Figure, Axes],
                 trajectories: typing.Union[
                     trajectory.PosePath3D,
                     typing.Sequence[trajectory.PosePath3D],
                     typing.Dict[str, trajectory.PosePath3D]],
                 plot_mode=PlotMode.xy, title: str = "",
                 subplot_arg: int = 111, plot_start_end_markers: bool = False,
                 length_unit: Unit = Unit.meters) -> None:
    """
    high-level function for plotting multiple trajectories
    :param fig: matplotlib figure, or maptplotlib axes
    :param trajectories: instance or container of PosePath3D or derived
    - if it's a dictionary, the keys (names) will be used as labels
    :param plot_mode: e.g. plot.PlotMode.xy
    :param title: optional plot title
    :param subplot_arg: optional matplotlib subplot ID if used as subplot
    :param plot_start_end_markers: Mark the start and end of a trajectory
                                   with a symbol.
    :param length_unit: Set to another length unit than meters to scale plots.
                        Note that trajectory data is still expected in meters.
    """
    if isinstance(fig_or_ax, Axes):
        ax = fig_or_ax
    else:
        ax = prepare_axis(fig_or_ax, plot_mode, subplot_arg, length_unit)
    if title:
        ax.set_title(title)

    cmap_colors = None
    if SETTINGS.plot_multi_cmap.lower() != "none" and isinstance(
            trajectories, collections.abc.Iterable):
        cmap = getattr(cm, SETTINGS.plot_multi_cmap)
        cmap_colors = iter(cmap(np.linspace(0, 1, len(trajectories))))

    color_palette = itertools.cycle(sns.color_palette())

    # helper function
    def draw(t, name=""):
        if cmap_colors is None:
            color = next(color_palette)
        else:
            color = next(cmap_colors)
        if SETTINGS.plot_usetex:
            name = name.replace("_", "\\_")
        traj(ax, plot_mode, t, '-', color, name,
             plot_start_end_markers=plot_start_end_markers)

    if isinstance(trajectories, trajectory.PosePath3D):
        draw(trajectories)
    elif isinstance(trajectories, dict):
        for name, t in trajectories.items():
            draw(t, name)
    else:
        for t in trajectories:
            draw(t)


def error_array(ax: Axes, err_array: ListOrArray,
                x_array: typing.Optional[ListOrArray] = None,
                statistics: typing.Optional[typing.Dict[str, float]] = None,
                threshold: typing.Optional[float] = None,
                cumulative: bool = False, color='grey', name: str = "error",
                title: str = "", xlabel: str = "index",
                ylabel: typing.Optional[str] = None, subplot_arg: int = 111,
                linestyle: str = "-", marker: typing.Optional[str] = None):
    """
    high-level function for plotting raw error values of a metric
    :param fig: matplotlib axes
    :param err_array: an nx1 array of values
    :param x_array: an nx1 array of x-axis values
    :param statistics: optional dictionary of {metrics.StatisticsType.value: value}
    :param threshold: optional value for horizontal threshold line
    :param cumulative: set to True for cumulative plot
    :param name: optional name of the value array
    :param title: optional plot title
    :param xlabel: optional x-axis label
    :param ylabel: optional y-axis label
    :param subplot_arg: optional matplotlib subplot ID if used as subplot
    :param linestyle: matplotlib linestyle
    :param marker: optional matplotlib marker style for points
    """
    if cumulative:
        if x_array is not None:
            ax.plot(x_array, np.cumsum(err_array), linestyle=linestyle,
                    marker=marker, color=color, label=name)
        else:
            ax.plot(np.cumsum(err_array), linestyle=linestyle, marker=marker,
                    color=color, label=name)
    else:
        if x_array is not None:
            ax.plot(x_array, err_array, linestyle=linestyle, marker=marker,
                    color=color, label=name)
        else:
            ax.plot(err_array, linestyle=linestyle, marker=marker, color=color,
                    label=name)
    color_pallete = itertools.cycle(sns.color_palette())
    if statistics is not None:
        for stat_name, value in statistics.items():
            color = next(color_pallete)
            if stat_name == "std" and "mean" in statistics:
                mean, std = statistics["mean"], statistics["std"]
                ax.axhspan(mean - std / 2, mean + std / 2, color=color,
                           alpha=0.5, label=stat_name)
            else:
                ax.axhline(y=value, color=color, linewidth=2.0,
                           label=stat_name)
    if threshold is not None:
        ax.axhline(y=threshold, color='red', linestyle='dashed', linewidth=2.0,
                   label="threshold")
    plt.ylabel(ylabel if ylabel else name)
    plt.xlabel(xlabel)
    plt.title(title)
    if SETTINGS.plot_show_legend:
        plt.legend(frameon=True)


def ros_map(
    ax: Axes, yaml_path: PathStr, plot_mode: PlotMode,
    cmap: str = SETTINGS.ros_map_cmap,
    mask_unknown_value: typing.Optional[int] = (
        SETTINGS.ros_map_unknown_cell_value if SETTINGS.ros_map_enable_masking
        else None), alpha: float = SETTINGS.ros_map_alpha_value,
    viewport: Viewport = Viewport(SETTINGS.ros_map_viewport)
) -> None:
    """
    Inserts an image of an 2D ROS map into the plot axis.
    See: http://wiki.ros.org/map_server#Map_format
    :param ax: 2D matplotlib axes
    :param plot_mode: a 2D PlotMode
    :param yaml_path: yaml file that contains the metadata of the map image
    :param cmap: color map used to map scalar data to colors
                 (only for single channel image)
    :param mask_unknown_value: uint8 value that represents unknown cells.
                               If specified, these cells will be masked out.
                               If set to None or False, nothing will be masked.
    :param viewport: Viewport defining how the axis limits will be changed
    """
    import yaml

    if isinstance(ax, Axes3D):
        raise PlotException("ros_map can't be drawn into a 3D axis")
    if plot_mode in {PlotMode.xz, PlotMode.yz, PlotMode.zx, PlotMode.zy}:
        # Image lies in xy / yx plane, nothing to see here.
        return
    x_idx, y_idx, _ = plot_mode_to_idx(plot_mode)

    yaml_path = Path(yaml_path)
    with open(yaml_path) as f:
        metadata = yaml.safe_load(f)

    # Load map image, mask unknown cells if desired.
    image_path = Path(metadata["image"])
    if not image_path.is_absolute():
        image_path = yaml_path.parent / image_path
    image = plt.imread(image_path)

    if mask_unknown_value:
        # Support masking with single channel or RGB images, 8bit or normalized
        # float. For RGB all channels must be equal to mask_unknown_value.
        n_channels = image.shape[2] if len(image.shape) > 2 else 1
        if image.dtype == np.uint8:
            mask_unknown_value_rgb = np.array([mask_unknown_value] * 3,
                                              dtype=np.uint8)
        elif image.dtype == np.float32:
            mask_unknown_value_rgb = np.array([mask_unknown_value / 255.0] * 3,
                                              dtype=np.float32)
        if n_channels == 1:
            image = np.ma.masked_where(image == mask_unknown_value_rgb[0],
                                       image)
        elif n_channels == 3:
            # imshow ignores masked RGB regions for some reason,
            # add an alpha channel instead.
            # https://stackoverflow.com/questions/60561680
            mask = np.all(image == mask_unknown_value_rgb, 2)
            max_alpha = 255 if image.dtype == np.uint8 else 1.
            image = np.dstack((image, (~mask).astype(image.dtype) * max_alpha))
        else:
            # E.g. if there's already an alpha channel it doesn't make sense.
            logger.warning("masking unknown map cells is not supported "
                           "with {}-channel {} pixels".format(
                               n_channels, image.dtype))

    original_bbox = copy.deepcopy(ax.dataLim)

    # Squeeze extent to reflect metric coordinates.
    resolution = metadata["resolution"]
    n_rows, n_cols = image.shape[x_idx], image.shape[y_idx]
    metric_width = n_cols * resolution
    metric_height = n_rows * resolution
    extent = (0, metric_width, 0, metric_height)
    if plot_mode == PlotMode.yx:
        image = np.rot90(image)
        image = np.fliplr(image)
    ax_image = ax.imshow(image, origin="upper", cmap=cmap, extent=extent,
                         zorder=-1, alpha=alpha)

    # Transform map frame to plot axis origin.
    map_to_pixel_origin = Affine2D()
    map_to_pixel_origin.translate(metadata["origin"][x_idx],
                                  metadata["origin"][y_idx])
    angle = metadata["origin"][2]
    if plot_mode == PlotMode.yx:
        # Rotation axis (z) points downwards.
        angle *= -1
    map_to_pixel_origin.rotate(angle)
    ax_image.set_transform(map_to_pixel_origin + ax.transData)

    if viewport in (viewport.update, viewport.zoom_to_map):
        bbox = map_to_pixel_origin.transform_bbox(
            Bbox(np.array([[0, 0], [metric_width, metric_height]])))
        if viewport == viewport.update:
            # Data limits aren't updated properly after the transformation by
            # ax.relim() / ax.autoscale_view(), so we have to do it manually...
            # Not ideal, but it allows to avoid a clipping viewport.
            # TODO: check if this is a bug in matplotlib.
            ax.dataLim = Bbox.union([original_bbox, bbox])
        elif viewport == viewport.zoom_to_map:
            ax.dataLim = bbox
    elif viewport == viewport.keep_unchanged:
        ax.dataLim = original_bbox
    ax.autoscale_view()

    # Initially flipped axes are lost for mysterious reasons...
    if SETTINGS.plot_invert_xaxis:
        ax.invert_xaxis()
    if SETTINGS.plot_invert_yaxis:
        ax.invert_yaxis()


def map_tile(ax: Axes, crs: str, provider: str = SETTINGS.map_tile_provider):
    """
    Downloads and inserts a map tile into the plot axis.
    Note: requires the optional contextily package to be installed.
    :param ax: matplotlib axes
    :param crs: coordinate reference system (e.g. "EPSG:4326")
    :param provider: tile provider, either as str (e.g. "OpenStreetMap.Mapnik")
                     or directly as a TileProvider object
    """
    if isinstance(ax, Axes3D):
        raise PlotException("map_tile can't be drawn into a 3D axis")

    try:
        import contextily as cx
        from evo.tools import contextily_helper
    except ImportError as error:
        raise PlotException(
            f"contextily package is required for plotting map tiles: {error}")

    if isinstance(provider, str):
        provider = contextily_helper.get_provider(provider_str=provider)
    cx.add_basemap(ax, crs=crs, source=provider)
