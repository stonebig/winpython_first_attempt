# -*- coding: utf-8 -*-
"""
WinPython Package Manager GUI

Created on Mon Aug 13 11:40:01 2012
"""

import os.path as osp
import os
import sys

from spyderlib.qt.QtGui import (QApplication, QMainWindow, QWidget, QLineEdit,
                                QHBoxLayout, QDockWidget, QFont, QVBoxLayout,
                                QColor, QAbstractItemView, QProgressDialog,
                                QTableView, QMessageBox, QPushButton, QLabel,
                                QTextOption)
from spyderlib.qt.QtCore import (Qt, QAbstractTableModel, QModelIndex, SIGNAL,
                                 QThread)
from spyderlib.qt.compat import (to_qvariant, getopenfilenames,
                                 getexistingdirectory)

from spyderlib.widgets.internalshell import InternalShell
from spyderlib.widgets.texteditor import TextEditor
from spyderlib.utils.qthelpers import (add_actions, create_action, keybinding,
                                       get_std_icon, action2button,
                                       mimedata2url)

# Local imports
from winpython import wppm
from spyderlib.config import add_image_path, get_module_data_path, get_icon
add_image_path(get_module_data_path('winpython', relpath='images'))


COLUMNS = CHECK, NAME, VERSION, ACTION = range(4)

INSTALL_ACTION = 'Install'
REPAIR_ACTION = 'Repair (reinstall)'
UPGRADE_ACTION = 'Upgrade from v'
NONE_ACTION = 'None (Already installed)'

class PackagesModel(QAbstractTableModel):
    def __init__(self):
        QAbstractTableModel.__init__(self)
        self.packages = []
        self.checked = set()
        self.actions = {}

    def sortByName(self):
        self.packages = sorted(self.packages, key=lambda x: x.name)
        self.reset()

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsEnabled
        column = index.column()
        if column in (NAME, VERSION, ACTION):
            return Qt.ItemFlags(QAbstractTableModel.flags(self, index))
        else:
            return Qt.ItemFlags(QAbstractTableModel.flags(self, index)|
                                Qt.ItemIsUserCheckable|Qt.ItemIsEditable)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.packages)):
            return to_qvariant()
        package = self.packages[index.row()]
        column = index.column()
        if role == Qt.CheckStateRole and column == CHECK:
            return to_qvariant(package in self.checked)
        elif role == Qt.DisplayRole:
            if column == NAME:
                return to_qvariant(package.name)
            elif column == VERSION:
                return to_qvariant(package.version)
            elif column == ACTION:
                try:
                    action = self.actions[package]
                except KeyError:
                    print package.name, package
                    action = '???'
                return to_qvariant(action)
        elif role == Qt.TextAlignmentRole:
            return to_qvariant(int(Qt.AlignLeft|Qt.AlignVCenter))
        elif role == Qt.BackgroundColorRole:
            if package in self.checked:
                color = QColor(Qt.darkGreen)
                color.setAlphaF(.1)
                return to_qvariant(color)
            else:
                color = QColor(Qt.lightGray)
                color.setAlphaF(.3)
                return to_qvariant(color)
        return to_qvariant()

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.TextAlignmentRole:
            if orientation == Qt.Horizontal:
                return to_qvariant(int(Qt.AlignHCenter|Qt.AlignVCenter))
            return to_qvariant(int(Qt.AlignRight|Qt.AlignVCenter))
        if role != Qt.DisplayRole:
            return to_qvariant()
        if orientation == Qt.Horizontal:
            if section == NAME:
                return to_qvariant("Name")
            elif section == VERSION:
                return to_qvariant("Version")
            elif section == ACTION:
                return to_qvariant("Action")
        return to_qvariant()

    def rowCount(self, index=QModelIndex()):
        return len(self.packages)

    def columnCount(self, index=QModelIndex()):
        return len(COLUMNS)
    
    def setData(self, index, value, role=Qt.EditRole):
        if index.isValid() and 0 <= index.row() < len(self.packages)\
           and role == Qt.CheckStateRole:
            package = self.packages[index.row()]
            if package in self.checked:
                self.checked.remove(package)
            else:
                self.checked.add(package)
            self.emit(SIGNAL("dataChanged(QModelIndex,QModelIndex)"),
                      index, index)
            return True
        return False


class PackagesTable(QTableView):
    def __init__(self, parent=None):
        QTableView.__init__(self, parent)
        self.model = PackagesModel()
        self.setModel(self.model)
        self.repair = False
        self.resizeColumnToContents(0)
        self.setAcceptDrops(True)
        self.distribution = None
    
    def reset_model(self):
        self.model.reset()
        self.resizeColumnToContents(0)
#        self.resizeRowsToContents()
        self.horizontalHeader().setStretchLastSection(True)
    
    def add_package(self, package):
        for pack in self.model.packages:
            if pack.name == package.name:
                return
        self.model.packages.append(package)
        self.model.packages.sort(key=lambda x: x.name)
        self.model.checked.add(package)
        self.reset_model()
    
    def remove_package(self, package):
        self.model.packages = [pack for pack in self.model.packages
                               if pack.fname != package.fname]
        if package in self.model.checked:
            self.model.checked.remove(package)
        if package in self.model.actions:
            self.model.actions.pop(package)
        self.reset_model()
    
    def refresh_distribution(self, dist):
        self.distribution = dist
        for package in self.model.packages:
            pack = dist.find_package(package.name)
            if pack is None:
                action = INSTALL_ACTION
            elif pack.version == package.version:
                if self.repair:
                    action = REPAIR_ACTION
                else:
                    action = NONE_ACTION
            else:
                action = UPGRADE_ACTION + pack.version
            self.model.actions[package] = action
        self.model.reset()
    
    def select_all(self):
        allpk = set(self.model.packages)
        if self.model.checked == allpk:
            self.model.checked = set()
        else:
            self.model.checked = allpk
        self.model.reset()

    def dragMoveEvent(self, event):
        """Reimplement Qt method, just to avoid default drag'n drop 
        implementation of QTableView to handle events"""
        event.acceptProposedAction()

    def dragEnterEvent(self, event):
        """Reimplement Qt method
        Inform Qt about the types of data that the widget accepts"""
        source = event.mimeData()
        if source.hasUrls() and mimedata2url(source):
            event.acceptProposedAction()
            
    def dropEvent(self, event):
        """Reimplement Qt method
        Unpack dropped data and handle it"""
        source = event.mimeData()
        for path in mimedata2url(source):
            if osp.isfile(path):
                try:
                    package = wppm.Package(path)
                    if package.is_compatible_with(self.distribution):
                        self.add_package(package)
                except NotImplementedError:
                    pass
        self.emit(SIGNAL('package_added()'))
        event.acceptProposedAction()


def is_python_distribution(path):
    """Return True if path is a Python distribution"""
    return osp.isfile(osp.join(path, 'python.exe'))\
           and osp.isdir(osp.join(path, 'Lib', 'site-packages'))


class DistributionSelector(QWidget):
    """Python distribution selector widget"""
    TITLE = 'Select a Python distribution path'
    def __init__(self, parent):
        super(DistributionSelector, self).__init__(parent)
        self.browse_btn = None
        self.label = None
        self.line_edit = None
        self.console = None
        self.setup_widget()
        
    def set_distribution(self, path):
        """Set distribution directory"""
        self.line_edit.setText(path)
        
    def setup_widget(self):
        """Setup workspace selector widget"""
        self.label = QLabel()
        self.line_edit = QLineEdit()
        self.line_edit.setAlignment(Qt.AlignRight)
        self.line_edit.setReadOnly(True)
        #self.line_edit.setDisabled(True)
        self.browse_btn = QPushButton(get_std_icon('DirOpenIcon'), "", self)
        self.browse_btn.setToolTip(self.TITLE)
        self.connect(self.browse_btn, SIGNAL("clicked()"),
                     self.select_directory)
        layout = QHBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.line_edit)
        layout.addWidget(self.browse_btn)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
    
    def select_directory(self):
        """Select directory"""
        basedir = unicode(self.line_edit.text())
        if not osp.isdir(basedir):
            basedir = os.getcwdu()
        while True:
            self.console.emit(SIGNAL('redirect_stdio(bool)'), False)
            directory = getexistingdirectory(self, self.TITLE, basedir)
            self.console.emit(SIGNAL('redirect_stdio(bool)'), True)
            if not directory:
                break
            if not is_python_distribution(directory):
                QMessageBox.warning(self, self.TITLE,
                    "The following directory is not a Python distribution.",
                    QMessageBox.Ok)
                basedir = directory
                continue
            directory = osp.abspath(osp.normpath(directory))
            self.set_distribution(directory)
            self.emit(SIGNAL('selected_distribution(QString)'), directory)
            break


class InstallationThread(QThread):
    """Installation thread"""
    def __init__(self, parent):
        QThread.__init__(self, parent)
        self.distribution = None
        self.package = None
    
    def run(self):
        self.distribution.install(self.package)

class PMWindow(QMainWindow):
    NAME = 'WPPM'
    def __init__(self):
        QMainWindow.__init__(self)

        self.thread = InstallationThread(self)
        self.packages = None
        
        self.selector = None
        self.table = None
        self.console = None
        
        self.basedir = None
        
        self.install_action = None
        self.remove_action = None
        self.packages_icon = get_std_icon('FileDialogContentsView')
        
        self.setup_window()
            
    def setup_window(self):
        """Setup main window"""
        self.setWindowTitle(self.NAME)
        self.setWindowIcon(get_icon('winpython.svg'))
        
        self.selector = DistributionSelector(self)
        self.connect(self.selector, SIGNAL('selected_distribution(QString)'),
                     self.distribution_changed)

        self.table = PackagesTable()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.connect(self.table, SIGNAL('package_added()'),
                     self.refresh_install_button)

        self.selector.set_distribution(sys.prefix)
        self.distribution_changed(sys.prefix)

        widget = QWidget()
        vlayout = QVBoxLayout()
        vlayout.addWidget(self.selector)
        vlayout.addWidget(self.table)
        btn_layout = QHBoxLayout()
        vlayout.addLayout(btn_layout)
        widget.setLayout(vlayout)
        self.setCentralWidget(widget)
        
        # Create the console widget
        font = QFont("Courier new")
        font.setPointSize(8)
        self.console = self.selector.console = cons = InternalShell(self)
        #self.console.interpreter.restore_stds()
        
        # Setup the console widget
        cons.set_font(font)
        cons.set_codecompletion_auto(True)
        cons.set_calltips(True)
        cons.setup_calltips(size=600, font=font)
        cons.setup_completion(size=(300, 180), font=font)
        console_dock = QDockWidget("Console", self)
        console_dock.setWidget(cons)
        console_dock.hide()
        self.connect(cons, SIGNAL('traceback_available()'),
                     console_dock.show)
        
        # Add the console widget to window as a dockwidget
        self.addDockWidget(Qt.BottomDockWidgetArea, console_dock)
        
        # Packages menu
        add_action = create_action(self, "&Add packages...",
                                   icon=get_std_icon('DialogOpenButton'),
                                   triggered=self.add_packages)
        self.remove_action = create_action(self, "Remove",
                                           shortcut=keybinding('Delete'),
                                           icon=get_std_icon('TrashIcon'),
                                           triggered=self.remove_packages)
        self.remove_action.setEnabled(False)
        select_all_action = create_action(self, "(Un)Select all",
                                   shortcut=keybinding('SelectAll'),
                                   icon=get_std_icon('DialogYesButton'),
                                   triggered=self.table.select_all)
        self.install_action = create_action(self, "&Install packages",
                                       icon=get_std_icon('DialogApplyButton'),
                                       triggered=self.install_packages)
        self.install_action.setEnabled(False)
        show_packages_action = create_action(self, "Show installed packages",
                                       icon=self.packages_icon,
                                       triggered=self.show_installed_packages)
        quit_action = create_action(self, "&Quit",
                                    icon=get_std_icon('DialogCloseButton'),
                                    triggered=self.close)
        packages_menu = self.menuBar().addMenu("&Packages")
        add_actions(packages_menu, [add_action, self.remove_action,
                                    self.install_action,
                                    None, show_packages_action,
                                    None, quit_action])
        
        # Option menu
        option_menu = self.menuBar().addMenu("&Options")
        repair_action = create_action(self, "Repair packages",
                      tip="Reinstall packages even if version is unchanged",
                      toggled=self.toggle_repair)
        add_actions(option_menu, (repair_action,))

        # View menu
        view_menu = self.menuBar().addMenu("&View")
        popmenu = self.createPopupMenu()
        add_actions(view_menu, popmenu.actions())
        
        # Help menu
        about_action = create_action(self, "About %s..." % self.NAME,
                                icon=get_std_icon('MessageBoxInformation'),
                                triggered=self.about)
        help_menu = self.menuBar().addMenu("?")
        add_actions(help_menu, [about_action])

        # Status bar
        status = self.statusBar()
        status.setObjectName("StatusBar")
        status.showMessage("Welcome to %s!" % self.NAME, 5000)
        
        # Button layout
        for act in (add_action, self.remove_action, None,
                    select_all_action, self.install_action):
            if act is None:
                btn_layout.addStretch()
            else:
                btn_layout.addWidget(action2button(act, autoraise=False,
                                                   text_beside_icon=True))
        
        self.resize(400, 500)
    
    def refresh_install_button(self):
        """Refresh install button enable state"""
        self.table.refresh_distribution(self.thread.distribution)
        self.install_action.setEnabled(\
            len(self.get_packages_to_be_installed()) > 0)
        self.remove_action.setEnabled(len(self.get_selected_packages()) > 0)
    
    def toggle_repair(self, state):
        """Toggle repair mode"""
        self.table.repair = state
        self.refresh_install_button()
    
    def distribution_changed(self, path):
        """Distribution path has just changed"""
        dist = wppm.Distribution(unicode(path))
        self.table.refresh_distribution(dist)
        assert not self.thread.isRunning()
        self.thread.distribution = dist
        self.selector.label.setText('Python %s %dbit:'
                                    % (dist.version, dist.architecture))
    
    def add_packages(self):
        """Add packages"""
        basedir = self.basedir if self.basedir is not None else ''
        fnames, _selfilter = getopenfilenames(parent=self, basedir=basedir,
                      caption='Add packages', filters='*.exe *.zip *.tar.gz')
        if fnames:
            self.basedir = osp.dirname(fnames[0])
            notsupported = []
            notcompatible = []
            dist = self.thread.distribution
            for fname in fnames:
                bname = osp.basename(fname)
                try:
                    package = wppm.Package(fname)
                    if package.is_compatible_with(dist):
                        self.table.add_package(package)
                    else:
                        notcompatible.append(bname)
                except NotImplementedError:
                    notsupported.append(bname)
            self.refresh_install_button()
            if notsupported:
                QMessageBox.warning(self, "Warning",
                                    "The following packages are <b>not (yet) "
                                    "supported</b> by %s:\n\n%s"
                                    % (self.NAME, "<br>".join(notsupported)),
                                    QMessageBox.Ok)
            if notcompatible:
                QMessageBox.warning(self, "Warning", "The following packages "
                                    "are <b>not compatible</b> with "
                                    "Python <u>%s %dbit</u>:\n\n%s"
                                    % (dist.version, dist.architecture,
                                       "<br>".join(notcompatible)),
                                    QMessageBox.Ok)

    def get_selected_packages(self):
        """Return selected packages"""
        return [pack for pack in self.table.model.packages
                if pack in self.table.model.checked]

    def get_packages_to_be_installed(self):
        """Return packages to be installed"""
        return [pack for pack in self.get_selected_packages()
                if self.table.model.actions[pack] != NONE_ACTION]
    
    def remove_packages(self):
        """Remove selected packages"""
        for package in self.get_selected_packages():
            self.table.remove_package(package)

    def install_packages(self):
        """Install packages"""
        packages = self.get_packages_to_be_installed()
        if not packages:
            return
        for widget in self.children():
            if isinstance(widget, QWidget):
                widget.setEnabled(False)
        status = self.statusBar()
        progress = QProgressDialog(self, Qt.FramelessWindowHint)
        progress.setMaximum(len(packages)-1)
        for index, package in enumerate(packages):
            progress.setValue(index)
            progress.setLabelText("Installing %s %s..."
                                  % (package.name, package.version))
            if progress.wasCanceled():
                break
            if package in self.table.model.actions:
                try:
                    self.thread.package = package
                    self.thread.start()
                    while self.thread.isRunning():
                        QApplication.processEvents()
                        if progress.wasCanceled():
                            status.setEnabled(True)
                            status.showMessage("Cancelling operation...")
                    self.table.remove_package(package)
                except Exception, error:
                    pstr = package.name + ' ' + package.version
                    QMessageBox.critical(self, "Error",
                                         "<b>Unable to install <i>%s</i></b>"
                                         "<br><br>Error message:<br>%s"
                                         % (pstr, unicode(error)))
        progress.setValue(progress.maximum())
        status.clearMessage()
        for widget in self.children():
            if isinstance(widget, QWidget):
                widget.setEnabled(True)
    
    def show_installed_packages(self):
        """Show installed packages"""
        dist = self.thread.distribution
        if dist is None:
            return
        packagelist = ["%s %s" % (pack.name, pack.version)
                       for pack in dist.get_installed_packages()]
        text = """Python distribution:
-------------------
Python %s %dbit
%s

List of installed packages: (with wppm)
--------------------------
%s
""" % (dist.version, dist.architecture, dist.target, "\n".join(packagelist))
        font = QFont("Courier new")
        font.setPointSize(8)
        widget = TextEditor(text, parent=self, readonly=True, font=font,
                            size=(500, 350))
        widget.setWindowTitle('Installed packages')
        widget.setWindowIcon(self.packages_icon)
        widget.edit.setWordWrapMode(QTextOption.WrapAnywhere)
        widget.exec_()

    def about(self):
        """About WPpm"""
        import platform
        from winpython import __version__, __project_url__, __forum_url__
        import spyderlib.qt.QtCore
        QMessageBox.about(self,
            "About %s" % self.NAME,
            """<b>%s %s</b>
            <br>WinPython Package Manager
            <p>Copyright &copy; 2012 Pierre Raybaut
            <br>Licensed under the terms of the MIT License
            <p>Created, developed and maintained by Pierre Raybaut
            <p>WinPython's community:
            <ul><li>Bug reports and feature requests: 
            <a href="%s">Google Code</a>
            </li><li>Discussions around the project: 
            <a href="%s">Google Group</a>
            </li></ul>
            <p>Python %s, Qt %s, %s %s on %s"""
            % (self.NAME, __version__, __project_url__, __forum_url__,
               platform.python_version(), spyderlib.qt.QtCore.__version__,
               spyderlib.qt.API_NAME, spyderlib.qt.__version__,
               platform.system()) )
        
    def closeEvent(self, event):
        self.console.exit_interpreter()
        event.accept()

        
def main():
    app = QApplication([])
    win = PMWindow()
    win.show()
    win.basedir = osp.join(osp.dirname(__file__),
                           os.pardir, os.pardir, os.pardir, 'sandbox')
    win.table.add_package(wppm.Package(r'D:\Pierre\installers\Cython-0.16.win-amd64-py2.7.exe'))
    win.refresh_install_button()
    app.exec_()


if __name__ == "__main__":
    main()
