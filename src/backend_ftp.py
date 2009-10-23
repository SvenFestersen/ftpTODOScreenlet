#!/usr/bin/env python
#
#       backend_ftp.py
#       
#       Copyright 2009 Sven Festersen <sven@sven-festersen.de>
#       
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#       
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#       
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.
import ftplib
import hashlib
import os
import Queue
import threading
import time
from xml.dom.minidom import parse

import backend


def getText(nodelist):
    """
    From minidom example at
    http://docs.python.org/library/xml.dom.minidom.html
    """
    rc = ""
    for node in nodelist:
        if node.nodeType == node.TEXT_NODE:
            rc = rc + node.data
    return rc
    
    
def load_tasks_from_file(filename):
    tasks = {}
    dom = parse(filename)
    node_tasklist = dom.getElementsByTagName("tasklist")[0]
    for node_task in node_tasklist.getElementsByTagName("task"):
        id = node_task.getAttribute("id")
        done = (node_task.getAttribute("done") == "1")
        date = int(node_task.getAttribute("date"))
        title = getText(node_task.getElementsByTagName("title")[0].childNodes).strip()
        comment = getText(node_task.getElementsByTagName("comment")[0].childNodes).strip()
        tasks[id] = (title, done, date, comment)
    return tasks
    
    
class FTPLoader(threading.Thread):
    
    def __init__(self, localfile, hostname, hostdir, hostfilename, username, password, cb_tasks_loaded, cb_error):
        threading.Thread.__init__(self)
        self._localfile = localfile
        self._hostname = hostname
        self._hostdir = hostdir
        self._hostfilename = hostfilename
        self._username = username
        self._password = password
        self._cb_tl = cb_tasks_loaded
        self._cb_te = cb_error
        
        self._command_queue = Queue.Queue()
        self.start()
        
    def run(self):
        try:
            ftp = ftplib.FTP(self._hostname, self._username, self._password)
        except:
            self._cb_te("Error connecting to server.")
            return
            
        try:
            ftp.cwd(self._hostdir)
        except:
            self._cb_te("The direectory '%s' does not exists on the server." % self._hostdir)
            ftp.quit()
            return
            
        while True:
            command = self._command_queue.get()
            if command == "quit":
                break
            elif command == "upload":
                ftp.storbinary("STOR %s" % self._hostfilename, open(self._localfile, "rb"))
            elif command == "download" and self._hostfilename in ftp.nlst():
                f = open(self._localfile, "w")
                f.write("")
                f.close()
                ftp.retrbinary("RETR %s" % self._hostfilename, self._cb_retr_bin)
                self._cb_tl(load_tasks_from_file(self._localfile))
            elif command == "download" and not self._hostfilename in ftp.nlst():
                f = open(self._localfile, "w")
                f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<tasklist>\n</tasklist>')
                f.close()
                self._cb_tl(load_tasks_from_file(self._localfile))
                
        ftp.quit()
        
    def _cb_retr_bin(self, data):
        f = open(self._localfile, "ab")
        f.write(data)
        f.close()
        
    def download(self):
        self._command_queue.put("download")
        
    def upload(self):
        self._command_queue.put("upload")
        
    def quit(self):
        self._command_queue.put("quit")
        
        
class UploadChecker(threading.Thread):
    
    _interval = 3
    
    def __init__(self, backend, loader):
        threading.Thread.__init__(self)
        self._backend = backend
        self._loader = loader
        self._quit = threading.Event()
        self.start()
        
    def run(self):
        while not self._quit.isSet():
            time.sleep(self._interval)
            if self._backend.get_needs_upload().isSet():
                self._loader.upload()
                self._backend.get_needs_upload().clear()
                
    def quit(self):
        self._quit.set()
    

class FTPTaskBackend(backend.TaskBackend):
    
    supported_features = (backend.FEATURE_COMMENT, backend.FEATURE_DUE_DATE)
    
    def __init__(self, tempfilename, hostname, hostdir, username, password, cb_tasks_loaded, cb_task_added, cb_task_removed, cb_task_updated, cb_task_error):
        backend.TaskBackend.__init__(self, cb_tasks_loaded, cb_task_added, cb_task_removed, cb_task_updated, cb_task_error)
        self._tempfilename = tempfilename
        self._tasks = {}
        self._needs_upload = threading.Event()
        self._loader = FTPLoader(tempfilename, hostname, hostdir, "tasks.xml", username, password, self._cb_tasks_loaded, self._cb_te)
        self._checker = UploadChecker(self, self._loader)
            
    def _cb_tasks_loaded(self, tasks):
        self._tasks = tasks
        self._cb_tl(tasks)
        
    def load_tasks(self):
        self._loader.download()
    
    def add_task(self, title):
        id = hashlib.md5(str(time.time())).hexdigest()
        self._tasks[id] = (title, False, -1, "")
        self.save_tasks()
        self._cb_ta(id, title)
        
    def remove_task(self, id):
        del self._tasks[id]
        self.save_tasks()
        self._cb_tr(id)
        
    def update_task(self, id, title, done, date, comment):
        self._tasks[id] = (title, done, date, comment)
        self.save_tasks()
        self._cb_tu(id, title, done, date, comment)
    
    def save_tasks(self):
        xmldata = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<tasklist>\n'
        for id, t in self._tasks.iteritems():
            title, done, date, comment = t
            if done:
                done = "1"
            else:
                done = "0"
            taskdata = '\t<task id="%s" done="%s" date="%s">\n' % (id, done, date)
            taskdata += '\t\t<title>%s</title>\n' % title
            taskdata += '\t\t<comment>\n%s\n\t\t</comment>\n' % comment
            taskdata += '\t</task>\n'
            xmldata += taskdata
        xmldata += '</tasklist>'
        f = open(self._tempfilename, "w")
        f.write(xmldata)
        f.close()
        self._needs_upload.set()
        
    def get_needs_upload(self):
        return self._needs_upload
        
    def close(self):
        self.save_tasks()
        self._loader.upload()
        self._needs_upload.clear()
        self._checker.quit()
        self._loader.quit()
