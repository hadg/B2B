#!/usr/bin/env python
# -*- coding: gbk -*-
# Copyright (c) 2013 clowwindy
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# @2013.08.22 by felix021
# This file is modified fron local.py from shadowsocks 1.3.3 to act as a pure
# socks5 proxy.
# usage:
#    python ssocks5.py          #listens on 7070
#    python ssocks5.py 1080     #listens on 1080

from __future__ import with_statement
import sys

try:
    import gevent
    import gevent.monkey
    gevent.monkey.patch_all(dns=gevent.version_info[0] >= 1)
except ImportError:
    gevent = None
    print >>sys.stderr, 'warning: gevent not found, using threading instead'

import socket
import select
import SocketServer
import struct
import os
import logging
import hashlib
import re
import urllib2
from StringIO import StringIO
import gzip
import b2bserver
import sys
import resources


class VideoCache(object):
    def __init__(self, Resource_Handle):
        # av_dict = {"av":{"cid":["1":["url1","url2"], "2":["url1", "url2"]}]}
        self.av_dict = {}
        self.cache_queue = {}
        self.Resource_Handle = Resource_Handle

    def _url_extract(self, header):
        url_path_s = header.find(' ')
        url_path_e = header.find(' ', url_path_s + 1)
        url_path = header[url_path_s + 1:url_path_e]
        header = header.split("\r\n")
        url_host = ''
        for h in header:
            if "Host: " in h:
                url_host = h[len("Host: "):]
                break
        result = url_host + url_path
        return url_host + url_path

    def _get_av(self, request_header):
        url = self._url_extract(request_header)
        result = re.findall(r"bilibili.com/video/av(\d+)(/index_(\d+))?", url)
        if result[0][0]:
            av = result[0][0]
            if result[0][2] and int(result[0][2]) > 1:
                av = av + "_" + result[0][2]
            return av
        else:
            return None

    def _get_cid(self, response):
        result = re.search(r"cid=(\d+)", response)
        if result:
            cid = result.group(1)
            return cid
        else:
            return None

    def _get_av_from_cid(self, cid):
        for k, v in self.av_dict.items():
            if v[0] == cid:
                return k
        return None

    def _url_clear(self, url):
        a = url.find("?")
        if a == -1:
            return url
        else:
            return url[:a]

    def _video_url_extract(self, xml_data):
        result = {}
        durl1 = -1
        durl2 = -1
        i = 1
        while True:
            durl1 = xml_data.find("<durl>", durl1 + 1)
            durl2 = xml_data.find("</durl>", durl2 + 1)
            if durl1 == -1 or durl2 == -1:
                break
            date_temp = xml_data[durl1:durl2]
            re_temp = re.findall(r"<url><!\[CDATA\[(\S+)\]\]></url>", date_temp)
            if re_temp:
                re_temp = map(self._url_clear, re_temp)
                result[str(i)] = re_temp
                i += 1
        return result

    def bilibili_save_video(self, data, end, av, section, type):
        if av not in self.cache_queue.keys():
            file_name = av + "_" + section + type
            video_file = open(file_name, "wb")
            self.cache_queue[av] = video_file
            self.cache_queue[av].write(data)
        else:
            self.cache_queue[av].write(data)
        if end:
            for cid in self.av_dict[av]:
                print "section"
                print section
                if len(cid) == section:
                    print "save video complete"
                    self.Resource_Handle.add_cache(av)
            self.cache_queue[av].close()
            self.cache_queue.pop(av)
            self.av_dict[av][1][section] = ["", ]

    def bilibili_del_video(self, av):
        if av in self.cache_queue.keys():
            self.cache_queue[av].close()
            self.cache_queue.pop(av)
            # TODO remoe_cache

    def bilibili_get_info_from_url(self, url):
        if "127.0.0.1" in url:
            return None
        url = self._url_clear(url)
        print url
        type = url[-4:]
        for k1, v1 in self.av_dict.items():
            for k2, v2 in v1[1].items():
                for v3 in v2:
                    if url == v3:
                        return [k1, k2, type] # av, section, type
        return None

    def bilibili_url_relate(self, cid, xml_data):
        av = self._get_av_from_cid(cid)
        if av:
            urls = self._video_url_extract(xml_data)
            self.av_dict[av][1] = urls
            print self.av_dict
            return True
        else:
            return False

    def bilibili_av_relate(self, request_header, response):
        av = self._get_av(request_header)
        cid = self._get_cid(response)
        if av and cid:
            self.av_dict[av] = [cid, {}]
            return True
        else:
            return False


class TrafficAnalysis(object):
    def __init__(self, Resource_Handle):
        self.origin_handle_queue = {}
        self.request_handle_queue = {}
        self.response_handle_queue = {}
        self.bilibili_handle_queue = {}
        self.redirection_dict = {}
        self.redirection_data_temp = ""
        self.rev_data_queue = {}
        self.Resource_Handle = Resource_Handle
        self.Cache_Handler = VideoCache(Resource_Handle)

    def http_in(self, l_sock, r_sock, data, method):
        http_header = False
        key = self._sock2str(l_sock)
        r_key = self._sock2str(r_sock)
        if "127.0.0.1" in r_key:
            return data
        key = key + r_key
        if method == 0:
            if key in self.response_handle_queue.keys():
                self.request_handle_queue.pop(key)
                self.response_handle_queue.pop(key)
                if key in self.rev_data_queue:
                    self.rev_data_queue.pop(key)
                if key in self.bilibili_handle_queue:
                    print "cache bvideo fail1?"
                    # TODO bilibili_del
                    self.bilibili_handle_queue.pop(key)
            if key in self.request_handle_queue.keys():
                if len(data) > 4:
                    if data[:3] == "GET":
                        http_header = True
                    elif data[:4] == "HEAD":
                        http_header = True
                    elif data[:4] == "POST":
                        http_header = True
                    if http_header:
                        self.request_handle_queue[key] = ['', None, False, "", False]
                return self.handle_request_data(key, data)
            else:
                if len(data) < 4:
                    return data
                if data[:3] == "GET":
                    http_header = True
                elif data[:4] == "HEAD":
                    http_header = True
                elif data[:4] == "POST":
                    http_header = True
                if http_header:
                    self.request_handle_queue[key] = ['', None, False, "", False] # header, data, end, md5, intercept
                    return self.handle_request_data(key, data)
                else:
                    return data
        if method == 1:
            if key in self.response_handle_queue.keys():
                self.handle_receive_data(key, data)
            else:
                if len(data) < 10:
                    return data
                if data[9:10] == "3" and data[:7] == "HTTP/1.":
                    self.handle_redirection_data(key, data)
                    return data
                if data[9:10] == "2" and data[:7] == "HTTP/1.":
                    http_header = True
                if http_header:
                    self.response_handle_queue[key] = ['', None, 0, ""] # header_temp, header, len_data, md5
                    self.handle_receive_data(key, data)
            return data

    def _do_get(self, header):
        url = self._url_extract(header)
        header_list = re.findall(r'(\S*):\s(.*)\r\n', header)
        headers = dict(header_list)
        req = urllib2.Request(url,headers=headers)
        response = urllib2.urlopen(req)
        if response.info().get('Content-Encoding') == 'gzip':
            buf = StringIO( response.read())
            f = gzip.GzipFile(fileobj=buf)
            response_data = f.read()
        else:
            response_data = response.read()
        response_header = str(response.info()) # include:\r\n
        response_header = "HTTP/1.1 200 OK" + "\r\n" + response_header
        response_header = self._replace_contend_len(response_header, len(response_data))
        #response = response_header + response_data
        return [response_header, response_data]

    # def _get_raw(self):
    #     CRLF = "\r\n"
    #     request = [
    #         "GET /playurl.xml HTTP/1.1",
    #         "Host: 127.0.0.1",
    #         "Connection: Close",
    #         "",
    #         "",
    #     ]
    #     s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #     s.connect(('127.0.0.1', 8020))
    #     s.send(CRLF.join(request))
    #     response = ''
    #     buffer = s.recv(4096)
    #     while buffer:
    #         response += buffer
    #         buffer = s.recv(4096)
    #     print response
    #     return response

    def _sock2str(self, sock):
        l = sock.getsockname()
        l = l[0] + ":" + str(l[1]) + "|"
        r = sock.getpeername()
        r = r[0] + ":" + str(r[1])
        return l + r

    def _http_header_extract(self, data):
        data_temp = str(data)
        # end = True
        # post_s = False
        # if data_temp[:4] == "POST":
        #     post_s = True
        #     end = False
        # elif data_temp[9:10] == "2" and data_temp[:7] == "HTTP/1.":
        #     end = False
        if "\r\n\r\n" in data_temp:
            data_arr = data_temp.split("\r\n\r\n")
            d_temp = data_arr[0] + "\r\n\r\n"
            # if post_s:
            #     end = self._content_data_extract(self._get_md5(d_temp), d_temp, len(data) - len(d_temp))
            #     return [d_temp, data[len(d_temp):], end]
            return [d_temp, data[len(d_temp):]]
        else:
            return None

    def _url_extract(self, header):
        url_path_s = header.find(' ')
        url_path_e = header.find(' ', url_path_s + 1)
        url_path = header[url_path_s + 1:url_path_e]
        header = header.split("\r\n")
        url_host = ''
        for h in header:
            if "Host: " in h:
                url_host = h[len("Host: "):]
                break
        result = "http://" + url_host + url_path
        for v in self.redirection_dict.values():
            if v[1] == result:
                result = v[0]
        return result

    def _get_md5(self, data):
        d_md5 = hashlib.md5()
        d_md5.update(data)
        return d_md5.hexdigest()

    def _url_clear(self, url):
        a = url.find("?")
        if a == -1:
            return [url, ""]
        else:
            return [url[:a], url[a:]]

    def _replace_contend_len(self, header, new_len):
        new_contend = "Content-Length: " + str(new_len)
        if "Transfer-Encoding: " in header:
            header = re.sub(r"Transfer-Encoding: .*\r\n", "", header)
        if "Content-Encoding: " in header:
            header = re.sub(r"Content-Encoding: .*\r\n", "", header)
        if "Content-Length: " in header:
            header = re.sub("Content-Length: \S*", new_contend, header)
        else:
            header = header.rstrip("\r\n\r\n")
            header = header + "\r\n" + new_contend + "\r\n\r\n"
        #print header
        return header

    def _content_data_extract(self, r_hash, r_header, len_data):
        # TODO HASH
        if r_hash not in self.rev_data_queue.keys():
            self.rev_data_queue[r_hash] = [0, 0]
            header = r_header.split("\r\n")
            for h_temp in header:
                if "Content-Length: " in h_temp:
                    content_len = int(h_temp[len("Content-Length: "):])
                    self.rev_data_queue[r_hash][0] = content_len
                    break
        if self.rev_data_queue[r_hash][0] > 0:
            self.rev_data_queue[r_hash][1] = len_data
            if self.rev_data_queue[r_hash][1] == self.rev_data_queue[r_hash][0]:
                self.rev_data_queue.pop(r_hash)
                return True
            else:
                return False
        else:
            return False

    def _is_img(self, response_header):
        header_temp = response_header.split("\r\n")
        for h in header_temp:
            if "image/png" in h:
                return True
        return False

    def _img_save(self, r_hash, data, end):
        with open("d:\\pytest\\" + r_hash + ".png", "ab") as image_file:
            image_file.write(data)
        if end:
            print "done!"
        return

    def _is_video(self, request_header):
        url = self._url_extract(request_header)
        url = self._url_clear(url)
        if ".mp4" in url[0]:
            if "Range: " in request_header:
                print "Jump result cache fail(mp4)"# TODO delete old cache
                return False
            else:
                return True
        if ".flv" in url[0]:
            if "start=" in url[1]:
                if "start=0" in url[1]:
                    return True
                print "Jump result cache fail(flv)"# TODO delete old cache
                return False
            else:
                return True

    def _is_bav(self, request_header):
        url = self._url_extract(request_header)
        if "bilibili.com/video/av" in url:
            return True
        else:
            return False

    def _is_bplayurl(self, request_header):
        url = self._url_extract(request_header)
        if "interface.bilibili.com/playurl" in url:
            return True
        else:
            return False

    def _handle_bplayurl(self, key, data):
        # TODO data size < 5
        durl = data.find("<durl>")
        durl2 = data.find("</durl>")
        data_temp = self._replace_allurl(data[durl:durl2])
        data = data[:durl] + data_temp + data[durl2:]
        return data

    def _replace_allurl(self, data):
        # a = re.search(r'http://\S+', data)
        # print a.group(0)
        old_len = len(data)
        data = re.sub(r'\[http://\S+\]\]', "[http://127.0.0.1:8020/7074716-1.flv]]", data)
        return data

    def _get_redirection_url(self, response_header):
        re_temp = re.search(r"Location: (.*)\r\n", response_header)
        if re_temp:
            return re_temp.group(1)
        else:
            return None

    def _clear_redirection_url(self):
        self.redirection_data_temp = ""
        for k, v in self.redirection_dict.items():
            if v[2]:
                self.redirection_dict.pop(k)
            else:
                v[2] = True

    def get_intercept(self, l_sock, r_sock):
        key = self._sock2str(l_sock)
        key = key + self._sock2str(r_sock)
        if key in self.request_handle_queue:
            return self.request_handle_queue[key][4]
        else:
            return False

    def handle_redirection_data(self, key, data):
        if key in self.bilibili_handle_queue.keys():
            print "start redirection"
            self.redirection_data_temp += data
            header = self._http_header_extract(self.redirection_data_temp)
            if header:
                r_url = self._get_redirection_url(header[0])
                o_url = self.request_handle_queue[key][0]
                print o_url
                o_url = self._url_extract(o_url)
                if r_url:
                    self.redirection_dict[key] = [o_url, r_url, False]
                    print self.redirection_dict[key]
                    self.redirection_data_temp = ""
                else:
                    self.redirection_data_temp = ""
        else:
            return

    def handle_request_data(self, key, data):
        if self.request_handle_queue[key][1] is None:
            self.request_handle_queue[key][0] += data
            header = self._http_header_extract(self.request_handle_queue[key][0])
            if header:
                self.request_handle_queue[key][0] = header[0]
                self.request_handle_queue[key][1] = header[1]
                # self.request_handle_queue[key][2] = header[2] #end
                self.request_handle_queue[key][3] = self._get_md5(header[0])
                if self._is_video(header[0]):
                    self.bilibili_handle_queue[key] = True
                if self._is_bav(header[0]):
                    self.request_handle_queue[key][4] = True
                    self.response_handle_queue[key] = True
                    data = self._do_get(header[0])
                    print "find bav!"
                    if self.Cache_Handler.bilibili_av_relate(header[0], data[1]):
                        print "av releate success!"
                    return data[0] + data[1]
                if self._is_bplayurl(header[0]):
                    # TODO cache
                    self.request_handle_queue[key][4] = True
                    self.response_handle_queue[key] = True
                    data = self._do_get(header[0])
                    # data[1] = self._handle_bplayurl(key, data[1])
                    # data[0] = self._replace_contend_len(data[0], len(data[1]))
                    # print "modifi url done!"
                    url = self._url_extract(header[0])
                    re_temp = re.search(r"cid=(\d+)", url)
                    if re_temp:
                        cid = re_temp.group(1)
                        av = self.Cache_Handler._get_av_from_cid(cid)
                        if av:
                            data[1] = self.Resource_Handle.handle_xml_data(av, data[1])
                            print data[1]
                            data[0] = self._replace_contend_len(data[0], len(data[1]))
                            print "handle xml success!"
                        else:
                            print "unfind av from cid!"
                        if self.Cache_Handler.bilibili_url_relate(cid, data[1]):
                            print "url relate success!"
                        else:
                            print "url relate fail!"
                    else:
                        print "unfind cid in request!"
                    return data[0] + data[1]
                # if header[0][:4] == "POST":
                #     end = self._content_data_extract(self.request_handle_queue[key][3], header[0], len(header[1]))
                #     self.request_handle_queue[key][2] = end
                #     if end:
                #         print "request_end"
                # TODO post data handle
                return data
            else:
                return data
        else:
            self.request_handle_queue[key][1] += data
            return data
            # self.request_handle_queue[key][2] = end
        # TODO post data handle

    def handle_receive_data(self, key, data):
        if self.request_handle_queue[key][1] is None:
            print "no http request!"
            return data
        if key not in self.request_handle_queue.keys():
            print "Key is not in the request queue!"
        # elif not self.request_handle_queue[key][2]:
        #     print "Incomplete request!"
        if self.response_handle_queue[key][1] is None:
            self.response_handle_queue[key][0] += data
            header = self._http_header_extract(self.response_handle_queue[key][0])
            if header:
                self.response_handle_queue[key][0] = ""
                self.response_handle_queue[key][1] = header[0] # http_header
                # self.response_handle_queue[key][0] = header[1] # data_temp
                self.response_handle_queue[key][2] = len(header[1])
                self.response_handle_queue[key][3] = self._get_md5(header[0])
                end = self._content_data_extract(self.response_handle_queue[key][3], header[0], len(header[1]))
                if key in self.bilibili_handle_queue.keys():
                    url = self._url_extract(self.request_handle_queue[key][0])
                    self.bilibili_handle_queue[key] = self.Cache_Handler.bilibili_get_info_from_url(url)
                    if self.bilibili_handle_queue[key]:
                        print "Cache start!"
                        self.Cache_Handler.bilibili_save_video(header[1], end, *self.bilibili_handle_queue[key])
                        # TODO NO FUGAI
                    else:
                        print "no bilibili info"
                        self.bilibili_handle_queue.pop(key)
                        return data
                    # url = self._url_extract(self.request_handle_queue[key][0])
                    # url = self._get_md5(url)
                    # self._img_save(url, header[1], end)
                else:
                    return data
                # if end:
                #     print "response_end"
                #     self.request_handle_queue.pop(key)
                #     self.response_handle_queue.pop(key)
            else:
                return data
        else:
            self.response_handle_queue[key][2] += len(data)
            end = self._content_data_extract(self.response_handle_queue[key][3], self.response_handle_queue[key][1],
                                             self.response_handle_queue[key][2])
            if key in self.bilibili_handle_queue.keys():
                self.Cache_Handler.bilibili_save_video(data, end, *self.bilibili_handle_queue[key])
                if end:
                    print "video save success!"
                    self.bilibili_handle_queue.pop(key)
                # url = self._url_extract(self.request_handle_queue[key][0])
                # url = self._get_md5(url)
                # self._img_save(url, data, end)
            # if end:
            #     self.request_handle_queue.pop(key)
            #     self.response_handle_queue.pop(key)
        return data

    def pop_queue(self, l_sock, r_sock):
        key = self._sock2str(l_sock)
        key = key + self._sock2str(r_sock)
        if key in self.request_handle_queue:
            self.request_handle_queue.pop(key)
        if key in self.response_handle_queue:
            self.response_handle_queue.pop(key)
        if key in self.rev_data_queue:
            self.rev_data_queue.pop(key)
        if key in self.bilibili_handle_queue:
            print "cache bvideo fail2?"
            # TODO bilibili_del
            self.bilibili_handle_queue.pop(key)
        self._clear_redirection_url()

    def pr(self):
        for k, v in self.rev_data_queue.items():
            print v


def send_all(sock, data):
    bytes_sent = 0
    while True:
        r = sock.send(data[bytes_sent:])
        if r < 0:
            return r
        bytes_sent += r
        if bytes_sent == len(data):
            return bytes_sent

class ThreadingTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    allow_reuse_address = True


class Socks5Server(SocketServer.StreamRequestHandler):
    def handle_tcp(self, sock, remote):
        global Traffic_Analysis
        try:
            fdset = [sock, remote]
            while True:
                r, w, e = select.select(fdset, [], [])
                # request
                if sock in r:
                    data = sock.recv(4096)
                    if len(data) <= 0:
                        break
                    data = Traffic_Analysis.http_in(sock, remote, data, 0)
                    if Traffic_Analysis.get_intercept(sock, remote):
                        result = send_all(sock, data)
                        if result < len(data):
                            raise Exception('failed to send all data')
                        break
                    else:
                        result = send_all(remote, data)
                        if result < len(data):
                            raise Exception('failed to send all data')
                # receive
                if remote in r:
                    # if a.get_intercept():
                    #     data = ''
                    #     buffer = remote.recv(4096)
                    #     while True:
                    #         data += buffer
                    #         buffer = remote.recv(4096)
                    #         if len(buffer) <= 0:
                    #             break
                    # else:
                    data = remote.recv(4096)
                    if len(data) <= 0:
                        break
                    data = Traffic_Analysis.http_in(sock, remote, data, 1)
                    result = send_all(sock, data)
                    if result < len(data):
                        raise Exception('failed to send all data')
        finally:
            Traffic_Analysis.pop_queue(sock, remote)
            sock.close()
            remote.close()

    def handle(self):
        try:
            sock = self.connection
            sock.recv(262)
            sock.send("\x05\x00")
            data = self.rfile.read(4) or '\x00' * 4
            mode = ord(data[1])
            if mode != 1:
                logging.warn('mode != 1')
                return
            addrtype = ord(data[3])
            if addrtype == 1:
                addr_ip = self.rfile.read(4)
                addr = socket.inet_ntoa(addr_ip)
            elif addrtype == 3:
                addr_len = self.rfile.read(1)
                addr = self.rfile.read(ord(addr_len))
            elif addrtype == 4:
                addr_ip = self.rfile.read(16)
                addr = socket.inet_ntop(socket.AF_INET6, addr_ip)
            else:
                logging.warn('addr_type not support')
                # not support
                return
            addr_port = self.rfile.read(2)
            port = struct.unpack('>H', addr_port)
            try:
                reply = "\x05\x00\x00\x01"
                reply += socket.inet_aton('0.0.0.0') + struct.pack(">H", 2222)
                self.wfile.write(reply)
                # reply immediately
                remote = socket.create_connection((addr, port[0]))
                logging.info('connecting %s:%d' % (addr, port[0]))
            except socket.error, e:
                logging.warn(e)
                return
            self.handle_tcp(sock, remote)
        except socket.error, e:
            logging.warn(e)

def check_port(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(("127.0.0.1",int(port)))
        s.shutdown(2)
        return True
    except:
        return False

def main():
    global PORT, LOCAL, IPv6, Traffic_Analysis, b2b
    
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(levelname)-8s %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S', filemode='a+')

    # fix py2exe
    if hasattr(sys, "frozen") and sys.frozen in \
            ("windows_exe", "console_exe"):
        p = os.path.dirname(os.path.abspath(sys.executable))
        os.chdir(p)
    Resource_Handle = resources.ResourcesHandle()
    Traffic_Analysis = TrafficAnalysis(Resource_Handle)
    LOCAL = '127.0.0.1'
    IPv6 = False

    # b2b = b2bserver.start()

    PORT = 6812
    if check_port(PORT):
        print "tcp port 6812 is using!"
        sys.exit(0)
    if len(sys.argv) > 1:
        PORT = int(sys.argv[1])
    try:
        if IPv6:
            ThreadingTCPServer.address_family = socket.AF_INET6
        server = ThreadingTCPServer((LOCAL, PORT), Socks5Server)
        logging.info("starting local at %s:%d" % tuple(server.server_address[:2]))
        server.serve_forever()
    except socket.error, e:
        logging.error(e)
    except KeyboardInterrupt:
        # b2b.shutdown()
        print "ss end"
        server.shutdown()
        sys.exit(0)
        
if __name__ == '__main__':
    main()
