#!/usr/bin/env python
# -*- coding: gbk -*-
# Copyright (c) 2016 hadg
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
# TODO 接收数据时将lanip转成127.0.0.1
import re
import os
import sys
import threading
import random
import urllib2
import time

class ResourcesHandle(object):
    def __init__(self):
        if hasattr(sys, "frozen") and sys.frozen in \
                ("windows_exe", "console_exe"):
            p = os.path.dirname(os.path.abspath(sys.executable))
            os.chdir(p)
        # self.VIDEO_CACHE_DIR = "\\videoserver\\htdocs\\"
        # self.VIDEO_CACHE_DIR = sys.path[0] + self.VIDEO_CACHE_DIR # D:\pystudy\b2b\videoserver\htdocs\
        self.VIDEO_SERVER_PORT = "6810"
        self.HTTP_PATH = "http://127.0.0.1:" + self.VIDEO_SERVER_PORT
        self.VIDEO_CACHE_DIR = r"D:\Apache24\htdocs\\"
        self.lan_ip = self._get_lan_ip()
        if not self.lan_ip:
            self.lan_ip = "{%None%}"
            print "获取内网IP失败..."
        self.data_dict = {}
        self.xml_dict = {}
        xml_files = self._get_xml_files(self.VIDEO_CACHE_DIR[:-1]) # TODO self.VIDEO_CACHE_DIR[:-1]
        self._generating_cache_dict(xml_files)
        print self.cache_dict

    def _get_lan_ip(self):
        opener = urllib2.build_opener(urllib2.ProxyHandler({}))
        urllib2.install_opener(opener)
        try:
            data = urllib2.urlopen("http://1.1.1.1:8000/ext_portal.magi", timeout=5)
        except:
            return False
        data = data.read()
        data = re.search(r"wlanuserip=(\S+?)&", data)
        if data:
            return data.group(1)
        else:
            return None

    def _get_xml_files(self, dir):
        result = []
        for parent, dirnames, filenames in os.walk(dir):
            for filename in filenames:
                if ".xml" in filename:
                    path = os.path.join(parent, filename)
                    if os.path.getsize(path) > 0:
                        result.append(path)
        return result

    def _url_clear(self, url):
        a = url.find("?")
        if a == -1:
            return url
        else:
            return url[:a]

    def _video_url_extract(self, xml_data):# {'1': ['http://cn-tj9-cu.acgvideo.com/vg3/0/61/7699052-1.flv', 'http://cn-tj8-cu.acgvideo.com/vg2/3/02/7699052-1.flv', 'http://ws.acgvideo.com/f/b2/7699052-1.flv']}
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

    def _generating_cache_dict(self, xml_files_list):
        # self.cache_dict = {"av":["http://server1:port", "http://server2:port"]}
        self.cache_dict = {}
        for file in xml_files_list:
            with open(file, "rb") as xml_file:
                (filepath, filename) = os.path.split(xml_file.name)
                av = os.path.splitext(filename)[0]
                xml_data = xml_file.read()
                video_dict = self._video_url_extract(xml_data)
                http_path = None
                for i in range(1, len(video_dict) + 1):
                    path = self.VIDEO_CACHE_DIR + av + "_" + str(i)
                    # http_path = "http://127.0.0.1:" + self.VIDEO_SERVER_PORT + "/" + av + "_" + str(i)
                    http_path = self.HTTP_PATH
                    if os.path.exists(path + ".flv"):
                        path = path + ".flv"
                    elif os.path.exists(path + ".mp4"):
                        path = path + ".mp4"
                    else:
                        http_path = None
                        break
                    if os.path.getsize(path) <= 0:
                        os.remove(path)
                        http_path = None
                        break
                if http_path:
                    self.cache_dict[av] = [http_path]

    def _sort_by_self(self, server_list):
        server_list_temp = []
        local_server = False
        for server in server_list:
            if self.HTTP_PATH == server:
                local_server = True
            elif re.match(r"http://\d+\.\d+\.\d+\.\d+:\d+", server):
                server_list_temp.append(server)
        get_ip_func = lambda x:re.search(r"\d+\.\d+\.\d+\.\d+", x).group(0)
        int_ip_func = lambda x:int(''.join([ i.rjust(3, '0') for i in get_ip_func(x).split('.')]))
        self_lan_ip = int_ip_func(self.lan_ip)
        server_list_temp.sort(lambda x,y: cmp(abs(int_ip_func(x) - self_lan_ip), abs(int_ip_func(y) - self_lan_ip)))
        if local_server:
            server_list_temp.insert(0, self.HTTP_PATH)
        return server_list_temp

    def _get_data(self, http_path, key="",thread_s=False):
        try:
            opener = urllib2.build_opener(urllib2.ProxyHandler({}))
            urllib2.install_opener(opener)
            data = urllib2.urlopen(http_path, timeout=2)
        except:
            if thread_s and key in self.data_dict:
                self.data_dict[key][http_path] = None
            return None
        data = data.read()
        if thread_s and key in self.data_dict:
            self.data_dict[key][http_path] = data
        return data

    def _check_server(self, server_addr):
        data = self._get_data(server_addr)
        if data == "b2b_running":
            return True
        else:
            return False

    def _check_xml(self, server_addr, av):
        path = server_addr + "/" + av + ".xml"
        request = urllib2.Request(path,)
        request.get_method = lambda: 'HEAD'
        try:
            data = urllib2.urlopen(request, timeout=2)
        except:
            return False
        code = data.code
        if code == 200:
            return True
        else:
            return False

    def _get_offline_server(self, server_list):
        key = str(random.randint(0,9999999999))
        self.data_dict[key] = {}
        offline_list = []
        server_list_temp = [x for x in server_list]
        server_list_n = len(server_list_temp)
        while server_list_temp:
            check_server_thread = threading.Thread(target=self._get_data,
                                                   args=(server_list_temp.pop(0), key, True))
            check_server_thread.start()
            time.sleep(0.1)
        while len(self.data_dict[key]) != server_list_n:
            time.sleep(0.1)
        for k, v in self.data_dict[key].items():
            if not v:
                offline_list.append(k)
        self.data_dict.pop(key)
        return offline_list

    def _video_url_replace(self, av, xml_data):# {'1': ['http://cn-tj9-cu.acgvideo.com/vg3/0/61/7699052-1.flv', 'http://cn-tj8-cu.acgvideo.com/vg2/3/02/7699052-1.flv', 'http://ws.acgvideo.com/f/b2/7699052-1.flv']}
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
                for url in re_temp:
                    url_temp = self._url_clear(url)
                    type = url_temp[-4:]
                    new_url = "http://" + "{%server%)" + "/" + av + "_" + str(i) + type
                    xml_data = xml_data.replace(url, new_url)
                i += 1
        return xml_data

    def _get_xml_from_server(self, av, server_list):
        key = str(random.randint(0,9999999999))
        self.data_dict[key] = {}
        xml_server = None
        server_list_temp = [x for x in server_list]
        server_list_temp = self._sort_by_self(server_list_temp)
        server_list_n = len(server_list_temp)
        while server_list_temp:
            for k, v in self.data_dict[key].items():
                if v:
                    xml_server = [k, v]
            if xml_server:
                break
            xml_path = server_list_temp.pop(0) + "/" + av +".xml"
            check_server_thread = threading.Thread(target=self._get_data,
                                                   args=(xml_path, key, True))
            check_server_thread.start()
        while len(self.data_dict[key]) != server_list_n:
            for k, v in self.data_dict[key].items():
                if v:
                    xml_server = [k, v]
            if xml_server:
                break
            time.sleep(0.1)
        for k, v in self.data_dict[key].items():
            if v:
                xml_server = [k, v]
        self.data_dict.pop(key)
        return xml_server

    def _url_extract(self, xml_url):
        url = re.match(r"http://(\d+\.\d+\.\d+\.\d+:\d+)", xml_url)
        if url:
            return url.group(1)

    def handle_xml_data(self, av, xml_data):
        print av
        if av in self.cache_dict.keys():
            print "xml发现可替换av号"
            temp = self._get_xml_from_server(av, self.cache_dict[av])
            if temp:
                xml_server = self._url_extract(temp[0])
                xml_data = temp[1].replace("{%server%)", xml_server)
                print "替换成功"
                print xml_data
                return xml_data
            else:
                return xml_data
        else:
            print "xml_未发现可用av号"
            o_xml_data = xml_data
            xml_data = self._video_url_replace(av, xml_data)
            print xml_data
            self.xml_dict[av] = xml_data
            # TODO 缓存失败删除
            return o_xml_data

    def add_cache(self, av):
        print "add_cache av:"
        print av
        if av in self.xml_dict.keys():
            if av not in self.cache_dict.keys():
                self.cache_dict[av] = []
            self.cache_dict[av].append(self.HTTP_PATH)
            xml_path = self.VIDEO_CACHE_DIR + av + ".xml"
            with open(xml_path, "wb") as xml_file:
                xml_file.write(self.xml_dict[av])
            self.xml_dict.pop(av)
            return True
        else:
            print "add_cache异常错误！"
            return False

    def remove_cache(self, av):
        if av in self.xml_dict.keys():
            self.xml_dict.pop(av)
        i = 1
        while True:
            path = self.VIDEO_CACHE_DIR + av + "_" + str(i)
            if os.path.exists(path + ".flv"):
                path = path + ".flv"
            elif os.path.exists(path + ".mp4"):
                path = path + ".mp4"
            else:
                break
            os.remove(path)
            i += 1

    def _cache_dict2server_dict(self, cache_dict):
        cache_dict_temp = self.cache_dict.copy()
        server_dict = {} # {"http://server1:port":[av1,av2]}
        for k, v in cache_dict_temp.items():
            for server in v:
                if server not in server_dict.keys():
                    server_dict[server] = []
                server_dict[server].append(k)
        return server_dict

    def _server_dict2server_data(self, server_dict):
        data = ""
        for k, v in server_dict.items():
            data += "{%0%}"
            if k == self.HTTP_PATH:
                temp = "http://" + self.lan_ip + ":" + self.VIDEO_SERVER_PORT
            else:
                temp = k
            data += temp + "{%,%}"
            for av in v:
                data += av + "{%,%}"
            data += "{%1%}"
        return data

    def  _server_data2server_dict(self, server_data):
        server_arr = re.findall(r"\{%0%\}(.*?)\{%1%\}", server_data)
        server_dict = {}
        for v in server_arr:
            temp = v.split("{%,%}")
            if len(temp) >= 3:
                if temp[0] == self.lan_ip:
                    temp[0] = self.HTTP_PATH
                server_dict[temp[0]] = temp[1:]
                server_dict[temp[0]].pop()
        return server_dict

    def _add_server(self, server_addr, cache_list):
        if self._check_server(server_addr):
            for av in cache_list:
                if av not in self.cache_dict.keys():
                    self.cache_dict[av] = []
                if server_addr not in self.cache_dict[av]:
                    self.cache_dict[av].append(server_addr)

    def _add_resource(self, server_addr, av):
        if self._check_xml(server_addr, av):
            if av not in self.cache_dict.keys():
                self.cache_dict[av] = []
            if server_addr not in self.cache_dict[av]:
                self.cache_dict[av].append(server_addr)

    def _cmp_cache_list(self, server_addr, l_cache_list, r_cache_list, response_dict):
        l_cache_list_temp = [x for x in l_cache_list]
        for r_av in r_cache_list:
            if r_av in l_cache_list:
                l_cache_list_temp.remove(r_av)
            else:
                self._add_resource(server_addr, r_av)
        if len(l_cache_list_temp) > 0:
            for l_av in l_cache_list_temp:
                if self._check_xml(server_addr, l_av):
                    if server_addr not in response_dict.keys():
                        response_dict[server_addr] = []
                    response_dict[server_addr].append(l_av)
                else:
                    if l_av in self.cache_dict.keys():
                        if server_addr in self.cache_dict[l_av]:
                            self.cache_dict[l_av].remove(server_addr)
                        else:
                            print "移除无用资源失败！"

    def _cmp_server_dict(self, l_server_dict, r_server_dict):
        response_dict = {}
        l_server_dict_temp = l_server_dict.copy()
        for k in r_server_dict.keys():
            if k not in l_server_dict.keys():
                self._add_server(k, r_server_dict[k])
            else:
                l_server_dict_temp.pop(k)
                self._cmp_cache_list(k, l_server_dict[k], r_server_dict[k], response_dict)
        if len(l_server_dict_temp) > 0:
            for k in l_server_dict_temp.keys():
                if self._check_server(k):
                    if k not in response_dict:
                        response_dict[k] = l_server_dict_temp[k]
                    else:
                        print "添加回馈服务器失败！"
        return response_dict

    def handle_cache_data(self, server_data):
        local_server_dict = self._cache_dict2server_dict(self.cache_dict)
        remote_server_dict = self._server_data2server_dict(server_data)
        response_dict = self._cmp_server_dict(local_server_dict, remote_server_dict)
        response_data = self._server_dict2server_data(response_dict)
        return response_data


b = '''<?xml version="1.0" encoding="UTF-8"?>
<video>
	<result>suee</result>
	<timelength>619677</timelength>
	<format><![CDATA[flv]]></format>
	<accept_format><![CDATA[mp4,hdmp4,flv]]></accept_format>
	<accept_quality><![CDATA[3,2,1]]></accept_quality>
	<from><![CDATA[local]]></from>
	<seek_param><![CDATA[start]]></seek_param>
	<seek_type><![CDATA[offset]]></seek_type>
	<src>0</src>
	<durl>
		<order>1</order>
		<length>296363</length>
		<size>49899544</size>
		<url><![CDATA[http://cn-zjwz1-cu.acgvideo.com/vg4/3/86/7113288-1.flv?expires=1464111000&ssig=F16MtRgTKS_hZaKI0E79wg&oi=2018869381&player=1&or=1885007044&rate=0]]></url>
		<backup_url>
		<url><![CDATA[http://cn-sxbj2-cu.acgvideo.com/vg2/f/52/7113288-1.flv?expires=1464111000&ssig=sQKWIGqiie8I7OdxQKESVA&oi=2018869381&player=1&or=1885007044&rate=0]]></url>
		<url><![CDATA[http://ws.acgvideo.com/4/7c/7113288-1.flv?wsTime=1464111183&wsSecret2=5e27df294f936601d1a31d31c8eb6f40&oi=2018869381&player=1&or=1885007044]]></url>
		</backup_url>
	</durl>
	<durl>
		<order>2</order>
		<length>323314</length>
		<size>51261190</size>
		<url><![CDATA[http://cn-zjwz1-cu.acgvideo.com/vg4/3/86/7113288-2.flv?expires=1464111000&ssig=ZufWJqWlucLdRg6k0MT4Ng&oi=2018869381&player=1&or=1885007044&rate=0]]></url>
		<backup_url>
		<url><![CDATA[http://cn-sxbj2-cu.acgvideo.com/vg2/f/52/7113288-2.flv?expires=1464111000&ssig=Nse3I9p4BJx_EB_V_WhjAQ&oi=2018869381&player=1&or=1885007044&rate=0]]></url>
		<url><![CDATA[http://ws.acgvideo.com/4/7c/7113288-2.flv?wsTime=1464111183&wsSecret2=b24d4501f6a4b603cf959a313b07a548&oi=2018869381&player=1&or=1885007044]]></url>
		</backup_url>
	</durl>
</video>'''
