#!/usr/bin/env python
#
#       backend_xml.py
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

def load_tasks(filename):
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
    

def save_tasks(filename, tasks):
    xmldata = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<tasklist>\n'
    for id, t in tasks.iteritems():
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
    f = open(filename, "w")
    f.write(xmldata)
    f.close()


class ThreadLoad(threading.Thread):
    
    def __init__(self, tempfilename, hostname, hostdir, username, password, cb_tasks_loaded, cb_error):
        threading.Thread.__init__(self)
        self._tempfilename = tempfilename
        self._hostname = hostname
        self._hostdir = hostdir
        self._username = username
        self._password = password
        self._cb_tl = cb_tasks_loaded
        self._cb_te = cb_error
        
    def run(self):
        try:
            ftp = ftplib.FTP(self._hostname, self._username, self._password)
            ftp.cwd(self._hostdir)
            
            os.unlink(self._tempfilename)
            
            if "tasks.xml" in ftp.nlst():
                ftp.retrbinary("RETR tasks.xml", self._cb_retrline)
                ftp.quit()
            else:
                f = open(self._tempfilename, "w")
                f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<tasklist>\n</tasklist>')
                f.close()
            
            tasks = {}
            dom = parse(self._tempfilename)
            node_tasklist = dom.getElementsByTagName("tasklist")[0]
            for node_task in node_tasklist.getElementsByTagName("task"):
                id = node_task.getAttribute("id")
                done = (node_task.getAttribute("done") == "1")
                date = int(node_task.getAttribute("date"))
                title = getText(node_task.getElementsByTagName("title")[0].childNodes).strip()
                comment = getText(node_task.getElementsByTagName("comment")[0].childNodes).strip()
                tasks[id] = (title, done, date, comment)
            self._cb_tl(tasks)
        except:
            self._cb_te("Error connecting to server.")
        
    def _cb_retrline(self, data):
        f = open(self._tempfilename, "ab")
        f.write(data)
        f.close()
        
        
class ThreadAdd(threading.Thread):
    
    def __init__(self, tempfilename, hostname, hostdir, username, password, cb_task_added, cb_error, title):
        threading.Thread.__init__(self)
        self._tempfilename = tempfilename
        self._hostname = hostname
        self._hostdir = hostdir
        self._username = username
        self._password = password
        self._cb_ta = cb_task_added
        self._cb_te = cb_error
        self._title = title
        
    def run(self):
        try:
            tasks = load_tasks(self._tempfilename)
                
            id = hashlib.md5(str(time.time())).hexdigest()
            tasks[id] = (self._title, False, -1, "")
            
            save_tasks(self._tempfilename, tasks)
            
            ftp = ftplib.FTP(self._hostname, self._username, self._password)
            ftp.cwd(self._hostdir)
            ftp.storbinary("STOR tasks.xml", open(self._tempfilename, "rb"))
            ftp.quit()
            
            self._cb_ta(id, self._title)
        except:
            self._cb_te("Error connecting to server.")
        
        
class ThreadRemove(threading.Thread):
    
    def __init__(self, tempfilename, hostname, hostdir, username, password, cb_task_removed, cb_error, id):
        threading.Thread.__init__(self)
        self._tempfilename = tempfilename
        self._hostname = hostname
        self._hostdir = hostdir
        self._username = username
        self._password = password
        self._cb_tr = cb_task_removed
        self._cb_te = cb_error
        self._id = id
        
    def run(self):
        try:
            tasks = load_tasks(self._tempfilename)
                
            del tasks[self._id]
            
            save_tasks(self._tempfilename, tasks)
            
            ftp = ftplib.FTP(self._hostname, self._username, self._password)
            ftp.cwd(self._hostdir)
            ftp.storbinary("STOR tasks.xml", open(self._tempfilename, "rb"))
            ftp.quit()
            
            self._cb_tr(self._id)
        except:
            self._cb_te("Error connecting to server.")
        
        
class ThreadUpdate(threading.Thread):
    
    def __init__(self, tempfilename, hostname, hostdir, username, password, cb_task_updated, cb_error, id, title, done, date, comment):
        threading.Thread.__init__(self)
        self._tempfilename = tempfilename
        self._hostname = hostname
        self._hostdir = hostdir
        self._username = username
        self._password = password
        self._cb_tu = cb_task_updated
        self._cb_te = cb_error
        self._id = id
        self._title = title
        self._done = done
        self._date = date
        self._comment = comment
        
    def run(self):
        try:
            tasks = load_tasks(self._tempfilename)
                
            tasks[self._id] = (self._title, self._done, self._date, self._comment)
            
            save_tasks(self._tempfilename, tasks)
            
            ftp = ftplib.FTP(self._hostname, self._username, self._password)
            ftp.cwd(self._hostdir)
            ftp.storbinary("STOR tasks.xml", open(self._tempfilename, "rb"))
            ftp.quit()
            
            self._cb_tu(self._id, self._title, self._done, self._date, self._comment)
        except:
            self._cb_te("Error connecting to server.")
    

class FTPTaskBackend(backend.TaskBackend):
    
    supported_features = (backend.FEATURE_COMMENT, backend.FEATURE_DUE_DATE)
    
    def __init__(self, tempfilename, hostname, hostdir, username, password, cb_tasks_loaded, cb_task_added, cb_task_removed, cb_task_updated, cb_task_error):
        backend.TaskBackend.__init__(self, cb_tasks_loaded, cb_task_added, cb_task_removed, cb_task_updated, cb_task_error)
        self._tempfilename = tempfilename
        self._hostname = hostname
        self._hostdir = hostdir
        self._username = username
        self._password = password
        
    def load_tasks(self):
        t = ThreadLoad(self._tempfilename, self._hostname, self._hostdir, self._username, self._password, self._cb_tl, self._cb_te)
        t.start()
    
    def add_task(self, title):
        t = ThreadAdd(self._tempfilename, self._hostname, self._hostdir, self._username, self._password, self._cb_ta, self._cb_te, title)
        t.start()
        
    def remove_task(self, id):
        t = ThreadRemove(self._tempfilename, self._hostname, self._hostdir, self._username, self._password, self._cb_tr, self._cb_te, id)
        t.start()
        
    def update_task(self, id, title, done, date, comment):
        t = ThreadUpdate(self._tempfilename, self._hostname, self._hostdir, self._username, self._password, self._cb_tu, self._cb_te, id, title, done, date, comment)
        t.start()
