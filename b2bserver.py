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
# TODO 防火墙检查
import SocketServer
import urllib2
import socket
import Queue
import threading
import time
import sys
import re
import random
import hashlib

def xor(content):
    key = "a4f26eee263f4963ab001059d423d40f" # git ignored
    dlen = len(content)
    klen = len(key)
    decoded = ''
    i = 0
    while i < dlen:
        idx = i % klen
        newbie = ord(content[i]) ^ ord(key[idx])
        decoded += chr(newbie)
        i += 1
    return decoded

class TCPClient(object):
    def __init__(self, lan_ip):
        self.lan_ip = lan_ip

    def _send_all(self, sock, data):
        bytes_sent = 0
        while True:
            r = sock.send(data[bytes_sent:])
            if r < 0:
                return r
            bytes_sent += r
            if bytes_sent == len(data):
                return bytes_sent

    def _generate_data(self, data):
        result = "{%|%}".join(data)
        result = xor(result)
        result += "{%E%}"
        return result

    def sentto(self, host, port, data, timeout=5.0): # data is list!
        # if host == self.lan_ip:
        #     print "禁止与本机通信(TCP)"
        #     return None
        addr = (host, port)
        data_temp = self._generate_data(data)
        try:
            client_sock = socket.create_connection(addr, timeout=timeout)
            client_sock.sendall(data_temp)
            buffer = ""
            while True:
                data_temp = client_sock.recv(4096)
                buffer += data_temp
                if data_temp[-5:] == "{%E%}":
                    break
                if not data_temp:
                    break
        except socket.timeout:
            print "++++ERROR++++"
            print "tcp client timeout"
            print "host:" + host
            print "data:" + str(data)
            print "++++END++++"
            return None
        except socket.error, e:
            e = str(e)
            if e == "[Errno 10061] ":
                print "++++ERROR++++"
                print "tcp client outline"
                print "host:" + host
                print "data:" + str(data)
                print "++++END++++"
                return None
            print "++++ERROR++++"
            print "tcp client error"
            print "host:" + host
            print "data:" + str(data)
            print "++++END++++"
            print e
            return None
        client_sock.close()
        if buffer[-5:] == "{%E%}":
            result = xor(buffer[:-5])
            return result
        else:
            return None

    def send_back(self, sock, data):
        data = xor(data)
        data += "{%E%}"
        try:
            sock.sendall(data)
            return True
        except socket.timeout:
            print "tcp client timeout"
            return None
        except socket.error, e:
            print "tcp client send back error"
            print e
            return None


class B2BServer(SocketServer.StreamRequestHandler):
    global b2b

    def handle(self):
        try:
            sock = self.connection
            buffer = ""
            while True:
                data_temp = sock.recv(4096)
                buffer += data_temp
                if data_temp[-5:] == "{%E%}":
                    break
                if not data_temp:
                    break
        except socket.error, e:
            b2b.handle_queue.put(None)
            b2b.handle_data()
            print "b2b handle error"
            print e
            return
        if buffer[-5:] == "{%E%}":
            result = xor(buffer[:-5])
            buffer = (sock, result)
            b2b.handle_queue.put(buffer)
            b2b.handle_data()


class SearchServer(SocketServer.BaseRequestHandler):
    global b2b

    def handle(self):
        data = self.request[0].strip()
        socket = self.request[1]
        client_addr = self.client_address[0]
        addr_temp = (client_addr, 6813)
        if b2b.search_status == "done":
            if data == "{%200%}":
                pass
            elif data == "{%FULL%}":
                pass
            elif data == "{%C%}":
                socket.sendto("{%200%}", addr_temp)
                print "receive check"
            elif data == "{%S%}":
                # if b2b.server_type == "father_server" or b2b.server_type == "elder_server":
                if b2b.server_usable:
                    socket.sendto("{%200%}", addr_temp)
                    print "search back 200"
                elif b2b.server_type == "wait":
                    socket.sendto("{%500%}", addr_temp)
                    print "search back 500"
                else:
                    socket.sendto("{%FULL%}", addr_temp)
                    print "search back full"
                # else:
                #     socket.sendto("{%CLIENT%}", addr_temp)
                print "receive search"
        else:
            if data == "{%200%}":
                b2b.search_status = "find"
                print "find! 200"
                b2b.server_queue.put([client_addr, "usable"])
            elif data == "{%FULL%}":
                b2b.search_status = "find"
                print "find! full"
                b2b.server_queue.put([client_addr, "full"])
            # elif data == "{%CLIENT%}":
            #     b2b.search_status = "find"
            #     b2b.server_queue.put([client_addr, "client"])
            elif data == "{%S%}":
                socket.sendto("{%-1%}", addr_temp)
                print "receive search when searching"
            elif data == "{%-1%}" and b2b.search_status == "":
                b2b.search_status = "search_busy"


class ThreadingUDPServer(SocketServer.ThreadingMixIn, SocketServer.UDPServer):
    allow_reuse_address = True


class ThreadingTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    allow_reuse_address = True


class B2B(object):
    def __init__(self, status):
        self.shutdown_s = False
        self.outline = False
        self.server_queue = Queue.Queue()
        self.handle_queue = Queue.Queue()
        self.client_list = []
        self.server_list = []
        self.father_server_list = []
        self.zero_server_list = []
        self.usable_server_list = []
        self.usable_server_dict = {}
        self.unusable_server_list = []
        self.level = 0
        self.list_temp = []
        self.client_empty_dict = {}
        self.outline_dict = {}
        self._sent_message_dict = {}
        self._sentto_zero_dict = {}
        self.list_temp_dict = {}
        self.check_server_start = 0
        self.server_type = "wait" # father_server elder_server
        self.client_is_empty = True
        self.server_usable = True
        self.client_outline_busy = False
        self.loop_busy = False
        self.replace_access_mutex = threading.Lock()
        self.replace_require_mutex = threading.Lock()
        self.replace_handle_mutex = threading.Lock()
        self._loop_mutex = threading.Lock()
        self._loop_list = []
        self.replace_key = ""
        self.father_server_outline = False
        self.father_server = ""
        self.grandpa_server = ""
        self.reserve_replace_server = ""
        self.reserve_replace_dict = {}
        self.max_client_n = 2
        self.DEBUG_BUSY = False
        self.lan_ip = self._get_lan_ip()
        print "lan_ip"
        print self.lan_ip
        if not self.lan_ip:
            print "无法获取内网IP，请检查网络是否正常"
            print "进入离线模式！"
            status[0] = False
        else:
            status[0] = True
        self.client = TCPClient(self.lan_ip)

    def check_network_thread(self):
        while not self.shutdown_s:
            try:
                socket.gethostbyaddr(self.lan_ip)
            except:
                self.shutdown_s = True
                print "网络异常，进入离线模式"
                self.shutdown()
                # TODO 离线模式
            time.sleep(3)

    def check_firewall(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((self.lan_ip, 6811))
        sock.listen(5)


    def start(self):
        self.server = ThreadingTCPServer((self.lan_ip, 6814), B2BServer)
        tcp_thread = threading.Thread(target=self.server.serve_forever)
        tcp_thread.start()
        self.search_server = ThreadingUDPServer((self.lan_ip, 6813), SearchServer)
        udp_thread = threading.Thread(target=self.search_server.serve_forever)
        udp_thread.start()
        search_thread = threading.Thread(target=self._search_server_thread)
        search_thread.start()
        time.sleep(0.5)
        if self.searching_handle():
            return True
        else:
            if self.search_status == "search_busy":
                print "搜索队列忙！8秒后自动重试..."
                for i in range(1, 4):
                    time.sleep(8)
                    print "重试第%d次" % i
                    self.search_status = ""
                    search_thread = threading.Thread(target=self._search_server_thread)
                    search_thread.start()
                    time.sleep(0.5)
                    if self.searching_handle():
                        return True
                    if self.search_status == "search_busy":
                        pass
                    else:
                        print "搜索完毕！"
                        self.b2bstart()
                        return
                print "搜索异常，请稍后尝试重新启动"
                self.search_server.shutdown()
                sys.exit(0)
            else:
                print "搜索完毕！"
                self.b2bstart()

    def _search_server_thread(self):
        self.server_queue = Queue.Queue()
        self.search_completed = False
        self.search_status = ""
        print "开始搜索服务器..."
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        data = "{%S%}"
        ip_list = self._ip_list_builder(self.lan_ip)
        for ip in ip_list:
            addr = (ip, 6813)
            s.sendto(data, addr)
            s.sendto(data, addr)
        s.close()
        if self.search_status == "":
            self.search_status = "ok"
        self.search_completed = True

    def _search_receive_data_handle(self):
        self._search_full_list = []
        self._search_usable_list = []
        # self._search_client_list = []
        while not self.server_queue.empty():
            temp = self.server_queue.get()
            print "handle temp"
            print temp
            if temp[1] == "usable":
                self._search_usable_list.append(temp[0])
            elif temp[1] == "full":
                self._search_full_list.append(temp[0])
        func = lambda x,y:x if y in x else x + [y]
        list_temp = reduce(func, [[], ] + self._search_usable_list)
        self._search_usable_list = list_temp
        func = lambda x,y:x if y in x else x + [y]
        list_temp = reduce(func, [[], ] + self._search_full_list)
        self._search_full_list = list_temp
        self._search_all_list = [x for x in self._search_usable_list]
        self._search_all_list.extend(self._search_full_list)
        return

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

    def _ip_range(self, start_ip, end_ip=""):
        start = list(map(int, start_ip.split(".")))
        if end_ip != "":
            end = list(map(int, end_ip.split(".")))
        else:
            start[3] = 1
            end = [x for x in start]
            end[3] = 255
        temp = start
        ip_range = []
        ip_range.append(".".join(map(str, temp)))
        while temp != end:
            start[3] += 1
            for i in (3, 2, 1):
                if temp[i] == 256:
                    temp[i] = 1
                    temp[i-1] += 1
            if temp[3] != 255:
                ip_range.append(".".join(map(str, temp)))
        return ip_range

    def _ip_list_builder(self, lan_ip):
        ip_list = []
        ip_list.extend(self._ip_range(lan_ip))
        before = list(map(int, lan_ip.split(".")))
        after = [x for x in before]
        while before[2] != 255 or after[2] != 0:
            if before[2] == 255:
                pass
            else:
                before[2] += 1
                before_temp = ".".join(map(str, before))
                ip_list.extend(self._ip_range(before_temp))
            if after[2] == 0:
                pass
            else:
                after[2] -= 1
                after_temp = ".".join(map(str, after))
                ip_list.extend(self._ip_range(after_temp))
        ip_list.remove(lan_ip)
        return ip_list

    def _check_server(self, server_addr):
        check = self.client.sentto(server_addr, 6814, ["0", ""], 3)
        if check == "{%200%}":
            return True
        else:
            return False

    def _sent_message(self, key, message, server_port, server_addr, timeout):
        status = self.client.sentto(server_addr, server_port, message, timeout)
        try:
            self._sent_message_dict[key][server_addr] = status
        except Exception, e:
            print "thread send error"
            print message
            print e

    def sent_message_thread(self, message, server_port, server_list, timeout=5.0):
        key = str(random.randint(0,9999999999))
        self._sent_message_dict[key] = {}
        server_list_temp = [x for x in server_list]
        for server in server_list_temp:
            sent_thread = threading.Thread(target=self._sent_message, args=(key, message, server_port, server, timeout))
            sent_thread.start()
        while not self.shutdown_s:
            if len(self._sent_message_dict[key].keys()) == len(server_list_temp):
                break
        return self._sent_message_dict.pop(key)

    def check_zero_server(self, server_addr):
        check = self.client.sentto(server_addr, 6814, ["0", "2"], 1.5)
        if check == "{%200%}":
            return True
        else:
            return False

    def _sentto_zero_loop(self, message, server_port, key, timeout=5.0, attempts=12):
        self.loop_busy = True
        attempt_n = 0
        while not self.shutdown_s:
            if key == self._loop_list[0]:
                break
            time.sleep(0.1)
        while not self.shutdown_s:
            if self.check_zero_server(self.zero_server_list[0]):
                result_dict = self.sent_message_thread(message, 6814, self.zero_server_list, timeout)
                if None not in result_dict.values():
                    self._loop_list.pop(0)
                    self.loop_busy = False
                    return True
            print "Loop fail +1"
            attempt_n = attempt_n + 1
            if attempt_n >= attempts:
                self.loop_busy = False
                self.DEBUG_PRINT()
                print "Important Error:与zero_server通信异常！"
                # TODO 应急处理
            time.sleep(0.1)

    def sentto_zero_loop_thread(self, message, server_port, timeout=5.0, attempts=12):
        md5 = hashlib.md5()
        data = ''.join(message)
        md5.update(data)
        key =  md5.hexdigest()
        self._loop_mutex.acquire()
        if key in self._loop_list:
            self._loop_mutex.release()
            return True
        else:
            self._loop_list.append(key)
        self._loop_mutex.release()
        sent_thread = threading.Thread(target=self._sentto_zero_loop,
                                       args=(message, server_port, key, timeout, attempts))
        sent_thread.start()

    def handle_data(self):
        data = self.handle_queue.get()
        if data is None:
            print "Socket error"
            return
        client_sock = data[0]
        try:
            client_addr = client_sock.getpeername()[0]
        except socket.error,e:
            print "handle remote socket error"
            print e
            return False
        if self.outline:
            client_sock.close()
        data = data[1]
        # message loop
        message_temp = data.split("{%|%}")
        if len(message_temp) < 2:
            print "不符合规范的请求!"
            return
        message_code = message_temp[0]
        message = [x for x in message_temp[1:]]
        if message_code == "0":# receive check
            if len(message) == 2:
                if message[0] == "1":# father_server receive client check
                    if client_addr in self.client_list:
                        self.client.send_back(client_sock, "{%200%}")
                        return
                    try:
                        client_level = int(message[1])
                        print client_level
                    except:
                        print "非法client check请求！"
                        self.client.send_back(client_sock, "{%500%}")
                        return
                    if client_level > self.level:
                        print "sent C_OUTLINE"
                        self.client.send_back(client_sock, "{%C_OUTLINE%}") # client outline
                        return
                    else:
                        print "sent F_OUTLINE"
                        self.client.send_back(client_sock, "{%F_OUTLINE%}") # father server outline
                        return
                elif message[0] == "2":# same level server receive check
                    try:
                        client_level = int(message[1])
                        print client_level
                    except:
                        print "非法client check请求！"
                        self.client.send_back(client_sock, "{%500%}")
                        return
                    if client_level > self.level:
                        print "sent {%S_OUTLINE%}"
                        self.client.send_back(client_sock, "{%S_OUTLINE%}")
                        return
                    else:
                        self.client.send_back(client_sock, "{%200%}")
                        return
            if message[0] == "2":
                if self.server_type == "father_server":
                    self.client.send_back(client_sock, "{%200%}")
                else:
                    self.client.send_back(client_sock, "{%500%}")
                return
            if client_addr == self.father_server:
                self.check_server_start = time.clock()
            self.client.send_back(client_sock, "{%200%}")
        elif message_code == "1":# receive server list sync
            server_type = message[0]
            key = message[1]
            if self.sent_server_list(client_addr, server_type, key):
                self.client.send_back(client_sock, "{%200%}")
            else:
                self.client.send_back(client_sock, "{%500%}")
                print "发送服务器列表失败"
        elif message_code == "2" and self.search_status == "done":# receive join don't refused
            if self.replace_require_mutex.acquire(0):
                if self.replace_handle_mutex.acquire(0):
                    accept_join = True
                else:
                    self.replace_require_mutex.release()
                    accept_join = False
            else:
                accept_join = False
            if not accept_join:
                self.client.send_back(client_sock, "{%BUSY%}")
                print "服务器忙，客户无法加入"
                return
            if self.receive_join(client_addr):
                self.replace_require_mutex.release()
                self.replace_handle_mutex.release()
                self.client.send_back(client_sock, "{%200%}")
                print "客户接入成功"
                sync_client_thread = threading.Thread(target=self.sent_message_thread,
                                                                      args=(["5", "sync_client_list"], 6814, self.client_list))
                sync_client_thread.start()
                self.DEBUG_PRINT()
            else:
                self.replace_require_mutex.release()
                self.replace_handle_mutex.release()
                self.client.send_back(client_sock, "{%500%}")
                print "客户端接入失败"
        elif message_code == "3":# receive list
            key = message[-1]
            data = message[:-1]
            if key in self.list_temp_dict.keys():
                self.list_temp_dict[key] = data
                self.client.send_back(client_sock, "{%200%}")
            else:
                print "非法 set list"
                self.client.send_back(client_sock, "{%500%}")
        elif message_code == "4": # receive check_server_status
            outline_check_target = message[0]
            if client_addr in self.server_list:
                if self._check_line(outline_check_target):
                    self.client.send_back(client_sock, "{%ONLINE%}")
                else:
                    self.outline_dict[outline_check_target] = True
                    self.client.send_back(client_sock, "{%OUTLINE%}")
            else:
                print "非法测试outline server请求"
                self.client.send_back(client_sock, "{%500%}")
                return
        elif message_code == "5": # receive sync client list
            if client_addr == self.father_server:
                l_temp = self.sync_list_from(self.father_server, "client_list")
                if not l_temp == "None":
                    self.server_list = l_temp
                    print "同步client成功!"
                    self.client.send_back(client_sock, "{%200%}")
                    if len(self.client_list) > 0:
                        self.sent_message_thread(["18", "refresh_father_server_list"], 6814, self.client_list, 3)
                else:
                    print "同步client失败!"
                    self.client.send_back(client_sock, "{%500%}")
            else:
                print "非法同步client请求"
                self.client.send_back(client_sock, "{%500%}")
        elif message_code == "6": # remove usable list
            if client_addr == self.father_server or self.server_type == "father_server":
                status = self.client.sentto(message[0], 6814, ["9", "check_server_usable"], 1.5)
                if status != "{%200%}":
                    for server_list in self.usable_server_dict.values():
                        if message[0] in server_list:
                            server_list.remove(message[0])
                            print "移除可用服务器成功"
                    self.client.send_back(client_sock, "{%200%}")
                    self.DEBUG_PRINT()
                else:
                    print "移除可用服务器失败（目标服务器可用）"
                    print "IP"
                    print message[0]
                    print "status"
                    print status
                    self.client.send_back(client_sock, "{%500%}")
                    return
                server_list_temp = []
                server_list_temp.extend(self.client_list)
                sync_usable_list = threading.Thread(target=self.sent_message_thread,
                                                    args=(["6", message[0]], 6814, server_list_temp))
                sync_usable_list.start()
            else:
                print "非法remove usable过程"
                self.client.send_back(client_sock, "{%500%}")
        elif message_code == "7": # join_server_back
            join_access = False
            if client_addr == self.father_server:
                join_access = True
            elif client_addr == self.grandpa_server:
                join_access = True
            if join_access:
                if self.become_server(client_addr, message[0]):
                    self.level = int(message[1])
                    self.client.send_back(client_sock, "{%200%}")
                    print "加入服务器成功"
                    print "len(self.client_list)"
                    print len(self.client_list)
                    if len(self.client_list) < self.max_client_n:
                        self.server_usable = True
                        self.add_usable_list(self.lan_ip, str(self.level))
                    else:
                        self.server_usable = False
                        self.remove_usable_list(self.lan_ip)
                else:
                    print "加入服务器失败"
            else:
                self.client.send_back(client_sock, "{%500%}")
                print "加入服务器请求无授权"
        elif message_code == "8": # receive remove server_list
            remove_target = message[0]
            if self.server_list and client_addr in self.server_list:
                if remove_target in self.server_list and remove_target in self.outline_dict.keys():
                    self.server_list.remove(remove_target)
                    self.outline_dict.pop(remove_target)
                    self.client.send_back(client_sock, "{%200%}")
                else:
                    print "remove server_list 异常2"
                    self.client.send_back(client_sock, "{%500%}")
            else:
                print "remove server_list 异常1"
                self.client.send_back(client_sock, "{%500%}")
        elif message_code == "9": # receive check server usable
            if self.server_usable:
                self.client.send_back(client_sock, "{%200%}")
            else:
                self.client.send_back(client_sock, "{%500%}")
        elif message_code == "10": # receive add usable list
            if client_addr == self.father_server or self.server_type == "father_server":
                usable_server_temp = message[0]
                level_temp = message[1]
                status = self.client.sentto(message[0], 6814, ["9", "check_server_usable"])
                if status == "{%200%}":
                    self._add_usable_server(usable_server_temp, level_temp)
                    self.client.send_back(client_sock, "{%200%}")
                else:
                    print "目标主机不可用，添加usable失败"
                    self.client.send_back(client_sock, "{%500%}")
                sync_usable_list = threading.Thread(target=self.sent_message_thread,
                                                    args=(["10", usable_server_temp, level_temp], 6814, self.client_list))
                sync_usable_list.start()
                print "添加usable server过程"
                self.DEBUG_PRINT()
            else:
                print "非法add usable过程"
                self.client.send_back(client_sock, "{%500%}")
        elif message_code == "11": # receive sync father_server_list and set father_server and set grandpa server
            if client_addr == self.reserve_replace_server:
                self.father_server = client_addr
                self.reserve_replace_server = ""
            if client_addr == self.father_server:
                l_temp = self.sync_list_from(client_addr, "server_list")
                l_temp_2 = self.sync_list_from(client_addr, "client_list")
                d_temp = self.sync_dict_from(client_addr, "usable_server_dict")
                if not l_temp == "None" and not l_temp_2 == None and not d_temp == "None":
                    if l_temp[0] == "father_server":
                        self.grandpa_server = l_temp[1]
                        l_temp.pop(0)
                        l_temp.pop(0)
                    if l_temp[0] == "grandpa_server":
                        l_temp.pop(0)
                        l_temp.pop(0)
                    if l_temp[0] == "zero_server":
                        self.zero_server_list = [l_temp[1]]
                        l_temp.pop(0)
                        l_temp.pop(0)
                    self.father_server_list = l_temp
                    self.server_list = l_temp_2
                    self.usable_server_dict = d_temp
                    if len(self.client_list) > 0:
                        sync_thread = threading.Thread(target=self.sent_message_thread,
                                        args=(["11", "sync_F_Z_G"], 6814, self.client_list))
                        sync_thread.start()
                    self.client.send_back(client_sock, "{%200%}")
                    print "同步 F_Z_G 成功"
                    self.DEBUG_PRINT()
                else:
                    print "同步 F_Z_G 失败"
            else:
                print "无授权同步 FZG 请求"
                self.client.send_back(client_sock, "{%500%}")
        elif message_code == "12": # receive search client empty
            if client_addr == self.father_server or client_addr == self.lan_ip:
                replace_request_server = message[0]
                replace_key = message[1]
                self.client.send_back(client_sock, "{%200%}")
                if len(self.client_list) == 0:
                    if self.reserve_replace_server == "":
                        if self.replace_handle_mutex.acquire(10):
                            m_back = self.client.sentto(replace_request_server, 6814, ["13", replace_key], 10)
                        else:
                            print "replace_handle_mutex 锁定失败"
                            return
                        if m_back == "{%200%}":
                            self.reserve_replace_server = replace_request_server
                            print "1 reserver"
                            print self.reserve_replace_server
                            self.replace_process(replace_request_server)
                            self.replace_handle_mutex.release()
                            self.reserve_replace_server = ""
                            # start replace
                else:
                    s_empty_thread = threading.Thread(target=self.sent_message_thread,
                                    args=(["12", replace_request_server, replace_key], 6814, self.client_list))
                    s_empty_thread.start()
            else:
                self.client.send_back(client_sock, "{%500%}")
                print "非法 search client empty 请求"
        elif message_code == "13": # receive get access to replace
            replace_key = message[0]
            self.replace_access_mutex.acquire()
            if replace_key not in self.reserve_replace_dict:
                print "无效的replace_key"
                self.client.send_back(client_sock, "{%500%}")
                self.replace_access_mutex.release()
                return
            if self.reserve_replace_dict[replace_key] == "":
                self.reserve_replace_dict[replace_key] = client_addr
                self.reserve_replace_server = client_addr
                self.replace_access_mutex.release()
                self.sent_message_thread(["17", self.reserve_replace_server], 6814, self.server_list)
                self.client.send_back(client_sock, "{%200%}")
                # threading replace
            else:
                self.client.send_back(client_sock, "{%500%}")
                self.replace_access_mutex.release()
        elif message_code == "14": # receive client outline
            self.client_outline_busy = True
            print "客户机主动下线"
            outline_type = message[0]
            if client_addr in self.client_list:
                self.client_outline(client_addr, outline_type)
                self.client.send_back(client_sock, "{%200%}")
                print "客户机主动下线成功"
            else:
                print "客户机主动下线失败，不存在于客户表内"
                self.client.send_back(client_sock, "{%500%}")
            self.client_outline_busy = False
        elif message_code == "15": # receive father server outline
            print "父服务器主动下线"
        elif message_code == "16":# receive get father server
            if self._client_check_father() == "{%200%}":
                self.client.send_back(client_sock, self.father_server)
            else:
                self.client.send_back(client_sock, "")
        elif message_code == "17":# receive set reserve_replace_server
            if client_addr == self.server_list[0]:
                self.reserve_replace_server = message[0]
                self.client.send_back(client_sock, "{%200%}")
            else:
                print "无权限请求 set reserve_replace_server"
                self.client.send_back(client_sock, "{%500%}")
        elif message_code == "18":# receive refresh father_server_list
            if client_addr == self.father_server:
                l_temp = self.sync_list_from(self.father_server, "server_list")
                if not l_temp == "None":
                    if l_temp[0] == "father_server":
                        l_temp.pop(0)
                        l_temp.pop(0)
                    if l_temp[0] == "grandpa_server":
                        l_temp.pop(0)
                        l_temp.pop(0)
                    if l_temp[0] == "zero_server":
                        l_temp.pop(0)
                        l_temp.pop(0)
                    self.father_server_list = l_temp
                    self.client.send_back(client_sock, "{%200%}")
                else:
                    self.client.send_back(client_sock, "{%500%}")
            else:
                print "非法同步父服务器列表请求"
                self.client.send_back(client_sock, "{%500%}")
        elif message_code == "19":# receive remove server in server list
            if self.server_list and client_addr in self.server_list:
                self.server_list.remove(client_addr)
                self.client.send_back(client_sock, "{%200%}")
            else:
                print "无权限请求 remove server in server list"
                self.client.send_back(client_sock, "{%500%}")

    def _remove_server_in_usable(self, server_addr):
        for server_list in self.usable_server_dict.values():
            if server_addr in server_list:
                server_list.remove(server_addr)

    def _add_usable_server(self, server_addr, level):
        self._remove_server_in_usable(server_addr)
        if level in self.usable_server_dict.keys():
            if server_addr not in self.usable_server_dict[level]:
                self.usable_server_dict[level].append(server_addr)
        else:
            self.usable_server_dict[level] = [server_addr]

    def add_usable_list(self, client_addr, level):
        print "添加usable"
        print client_addr
        print level
        self._add_usable_server(client_addr, level)
        self.sentto_zero_loop_thread(["10", client_addr, level], 6814)

    def remove_usable_list(self, client_addr):
        self._remove_server_in_usable(client_addr)
        self.sentto_zero_loop_thread(["6", client_addr], 6814)

    def sent_self_not_empty(self, server_addr):
        status = self.client.sentto(server_addr, 6814, ["5", "set_self_not_empty"])
        if status == "{%200%}":
            return True
        else:
            return False

    def sent_self_empty(self, server_addr):
        status = self.client.sentto(server_addr, 6814, ["6", "set_self_empty"])
        if status == "{%200%}":
            return True
        else:
            return False

    def receive_add_list(self,):
        pass

    def receive_join(self, client_addr):
        if self.server_type == "father_server":
            # if len(self.server_list) < self.max_client_n:
            if False:
                # type = "father_server"
                # if client_addr not in self.server_list:
                #     self.server_list.append(client_addr)
                # self.zero_server_list.append(client_addr)
                # # self.client_empty_dict[client_addr] = "0" # unusable
                # self.usable_server_list.append(client_addr)
                # level_temp = str(self.level + 1)
                # if level_temp in self.usable_server_dict.keys():
                #     if client_addr not in self.usable_server_dict[level_temp]:
                #         self.usable_server_dict[level_temp].append(client_addr)
                # else:
                #     self.usable_server_dict[level_temp] = [client_addr]
                # if self._sent_join(client_addr, type):
                #     #TODO sync server and alive_able_server list (thread)
                #     self.add_usable_list(client_addr, level_temp)
                #     print "客户成为父服务器成功！"
                #     return True
                # else:
                #     self.server_list.remove(client_addr)
                #     self.zero_server_list.remove(client_addr)
                #     # self.client_empty_dict.pop(client_addr)
                #     self.usable_server_list.remove(client_addr)
                #     self.usable_server_dict[level_temp].remove(client_addr)
                #     return False
                pass
            else:
                type = "elder_server"
                if client_addr not in self.client_list:
                    self.client_list.append(client_addr)
                if self._sent_join(client_addr, type):
                    print "客户成为子服务器成功！"
                    if len(self.client_list) >= self.max_client_n:
                        self.server_usable = False
                        self.remove_usable_list(self.lan_ip)
                    return True
                else:
                    self.client_list.remove(client_addr)
                    # self.client_empty_dict.pop(client_addr)
                    self.usable_server_list.remove(client_addr)
                    # self.usable_server_dict[level_temp].remove(client_addr)
                    print "客户成为子服务器失败！"
                    return False
        elif self.server_type == "elder_server":
            type = "elder_server"
            if client_addr not in self.client_list:
                self.client_list.append(client_addr)
            if self._sent_join(client_addr, type):
                print "客户成为子服务器成功(父)"
                if len(self.client_list) >= self.max_client_n:
                    self.server_usable = False
                    self.remove_usable_list(self.lan_ip)
                return True
            else:
                self.client_list.remove(client_addr)
                # self.client_empty_dict.pop(client_addr)
                self.usable_server_list.remove(client_addr)
                # self.usable_server_dict[level_temp].remove(client_addr)
                return False
        return False

    def _sent_join(self, client_addr, type):
        status = self.client.sentto(client_addr, 6814, ["7", type, str(self.level + 1)])
        if status == "{%200%}":
            return True
        else:
            return False

    def sent_server_list(self, server_addr, type, key):
        data = ["3"]
        if type == "server_list":
            data.append("father_server")
            data.append(self.father_server)
            data.append("grandpa_server")
            data.append(self.grandpa_server)
            data.append("zero_server")
            data.append(self.zero_server_list[0])
            data.extend(self.server_list)
        elif type == "father_server_list":
            data.extend(self.father_server_list)
        elif type == "client_list":
            if self.server_type == "elder_server":
                for client in self.client_list:
                    data.append(client)
                    # data.append(self.client_empty_dict[client])
            else:
                data.extend(self.client_list)
        elif type == "usable_server_list":
            if len(self.usable_server_list) == 0:
                print "本机可用服务器列表为空"
                data.append("")
            else:
                data.extend(self.usable_server_list)
        elif type == "usable_server_dict":
            usable_list = []
            for level in self.usable_server_dict.keys():
                usable_list.append("level" + level)
                usable_list.extend(self.usable_server_dict[level])
            data.extend(usable_list)
        elif type == "zero_server_list":
            data.extend(self.zero_server_list)
        if len(data) == 1:
            print "请求的列表为空！"
            data.append("{%EMPTY%}")
            print type
        data.append(key)
        status = self.client.sentto(server_addr, 6814, data)
        if status == "{%200%}":
            return True
        else:
            return False

    def become_server(self, server_addr, server_type):
        if server_type == "father_server":
            l_temp = self.sync_list_from(server_addr, "server_list")
            if not l_temp == "None":
                n = True
                self.server_list = []
                self.client_empty_dict = {}
                for server in l_temp:
                    if n:
                        n = False
                        self.server_list.append(server)
                    else:
                        n = True
                        self.client_empty_dict[self.server_list[-1]] = server
                if not n:
                    print "同步server_list异常(father)"
            else:
                return False
            l_temp = self.sync_list_from(server_addr, "usable_server_list")
            if not l_temp == "None":
                self.usable_server_list = l_temp
                print "test usable list"
                print self.usable_server_list
            else:
                return False
            l_temp = self.sync_list_from(server_addr, "usable_server_dict")
            if not l_temp == "None":
                usable_list_temp = l_temp
                self.usable_server_dict = {}
                level_temp = "undefined"
                for x in usable_list_temp:
                    if "level" in x:
                        level_temp = x[5:]
                        print level_temp
                        self.usable_server_dict[level_temp] = []
                    else:
                        self.usable_server_dict[level_temp].append(x)
                print "test usable dict"
                print self.usable_server_dict
            else:
                return False
            l_temp = self.sync_list_from(server_addr, "zero_server_list")
            if not l_temp == "None":
                self.zero_server_list = l_temp
            else:
                return False
            # TODO resource list
            self.father_server = ""
        elif server_type == "elder_server":
            l_temp = self.sync_list_from(server_addr, "server_list")
            if not l_temp == "None":
                if l_temp[0] == "father_server":
                    self.grandpa_server = l_temp[1]
                    l_temp.pop(0)
                    l_temp.pop(0)
                if l_temp[0] == "grandpa_server":
                    l_temp.pop(0)
                    l_temp.pop(0)
                if l_temp[0] == "zero_server":
                    self.zero_server_list = [l_temp[1]]
                    l_temp.pop(0)
                    l_temp.pop(0)
                self.father_server_list = l_temp
            else:
                return False
            l_temp = self.sync_list_from(server_addr, "usable_server_list")
            if not l_temp == "None":
                self.usable_server_list = l_temp
            else:
                return False
            l_temp = self.sync_list_from(server_addr, "usable_server_dict")
            if not l_temp == "None":
                usable_list_temp = l_temp
                print "usable_list_temp"
                print usable_list_temp
                self.usable_server_dict = {}
                level_temp = "undefined"
                for x in usable_list_temp:
                    if "level" in x:
                        level_temp = x[5:]
                        self.usable_server_dict[level_temp] = []
                    else:
                        self.usable_server_dict[level_temp].append(x)
                print "test usable dict elder"
                print self.usable_server_dict
            else:
                return False
            l_temp = self.sync_list_from(server_addr, "client_list")
            if not l_temp == "None":
                self.server_list = l_temp
            else:
                return False
            l_temp = self.sync_list_from(server_addr, "zero_server_list")
            if not l_temp == "None":
                self.zero_server_list = l_temp
            else:
                return False
            self.father_server = server_addr
        else:
            print "不标准的消息"
            return False
        self.server_usable = True
        self.server_type = server_type
        return True

    def join_server(self, server_addr):
        if server_addr == self.lan_ip:
            print "不能加入自己！"
            return False
        self.father_server = server_addr
        status = self.client.sentto(server_addr, 6814, ["2", "join_in_server"])
        if status == "{%200%}":
            return True
        elif status == "{%BUSY%}":
            time.sleep(1)
            for i in range(3):
                print "服务器忙，重新尝试加入服务器..."
                status = self.client.sentto(server_addr, 6814, ["2", "join_in_server"], 3)
                if status == "{%200%}":
                    return True
                elif status == "{%BUSY%}":
                    time.sleep(2)
                    continue
                else:
                    return False
            return False
        else:
            return False

    def sync_resource_list_from(self, server_addr):
        pass

    def sync_list_from(self, server_addr, type):
        key = str(random.randint(0,9999999999))
        self.list_temp_dict[key] = ""
        status = self.client.sentto(server_addr, 6814, ["1", type, key])
        if status == "{%200%}":
            if self.list_temp_dict[key] == ["{%EMPTY%}"]:
                print "收到的列表为空"
                print type
                self.list_temp_dict.pop(key)
                return []
            else:
                return self.list_temp_dict.pop(key)
        else:
            self.list_temp_dict.pop(key)
            return "None"

    def sync_dict_from(self, server_addr, type):
        l_temp = self.sync_list_from(server_addr, type)#
        if not l_temp == "None":
            if type == "usable_server_dict":
                usable_list_temp = l_temp
                dict_temp = {}
                level_temp = "undefined"
                for x in usable_list_temp:
                    if "level" in x:
                        level_temp = x[5:]
                        dict_temp[level_temp] = []
                    else:
                        dict_temp[level_temp].append(x)
                return dict_temp
            else:
                print "未定义的dict"
                return "None"
        else:
            return "None"

    def pop_list_most(self, list_temp):
        temp=[]
        for i in list_temp:
            temp+=[list_temp.count(i)]
        result = list_temp.pop(temp.index(max(temp)))
        while True:
            if result in list_temp:
                list_temp.remove(result)
            else:
                break
        return result

    def replace_process(self, replace_client):
        o_father_server = self.father_server
        o_server_list = [ x for x in self.server_list]
        o_server_list.remove(self.lan_ip)
        l_temp = self.sync_list_from(replace_client, "server_list")
        l_temp_2 = self.sync_list_from(replace_client, "father_server_list")
        if not l_temp == "None" and not l_temp_2 == "None":
            outline_father_server = ""
            if l_temp[0] == "father_server":
                outline_father_server = l_temp[1]
                l_temp.pop(0)
                l_temp.pop(0)
            if l_temp[0] == "grandpa_server":
                self.father_server = l_temp[1]
                l_temp.pop(0)
                l_temp.pop(0)
            if l_temp[0] == "zero_server":
                self.zero_server_list = [l_temp[1]]
                l_temp.pop(0)
                l_temp.pop(0)
            self.client_list = l_temp
            server_list_temp = l_temp_2
            print l_temp_2
            if outline_father_server in server_list_temp:
                server_list_temp.remove(outline_father_server)
            if self.lan_ip in self.client_list:
                self.client_list.remove(self.lan_ip)
        else:
            print "同步失败!(replace)"

            return False
        print "开始替换父服务器..."
        print self.father_server
        if self.father_server != "":
            if self.join_server(self.father_server):
                print "替换成功"
                # self.replace_process(o_client_list, o_server_list)
            else:
                print "替换失败...5秒后重试"
                replace_success = False
                for i in range(6):
                    time.sleep(5)
                    result_dict = self.sent_message_thread(["16", "get_father_server"], 6814, server_list_temp)
                    result_list = [x for x in result_dict.values() if x != None]
                    result_temp = []
                    while len(result_list) > 0:
                        result_temp.append(self.pop_list_most(result_list))
                    if len(result_temp) > 0:
                        for father_server in result_temp:
                            father_server_re = re.match(r"\d+\.\d+\.\d+\.\d+", father_server)
                            if father_server_re:
                                if self.join_server(father_server):
                                    print "替换成功"
                                    replace_success = True
                                    break
                    print "替换失败...5秒后重试"
                if not replace_success:
                    print "无法替换父服务器，进入离线模式！"
                    self.shutdown()
                    # TODO 紧急响应
        else:
            self.zero_server_list = [self.lan_ip]
            self.server_list = [self.lan_ip]
            self.father_server_list = []
            self.grandpa_server = ""
            self.level = 0
            self.server_type = "father_server"
            print "替换成功（父）"
            if len(self.client_list) < self.max_client_n:
                self.server_usable = True
                self.add_usable_list(self.lan_ip, '0')
            else:
                self.server_usable = False
                self.remove_usable_list(self.lan_ip)
        if self.lan_ip != replace_client:
            status = self.client.sentto(o_father_server, 6814, ["14", "1"], 10)
            if status != "{%200%}":
                self.sent_message_thread(["19", "remove_server_in_server_list"], 6814, o_server_list, 5)
        if self.father_server != "":
            d_temp = self.sync_dict_from(self.father_server, "usable_server_dict")
            if not d_temp == "None":
                self.usable_server_dict = d_temp
            else:
                print "同步usable_server_dict失败（替换）"
        if len(self.client_list) > 0:
            sync_thread = threading.Thread(target=self.sent_message_thread,
                                           args=(["11", "sync_F_Z_G"], 6814, self.client_list))
            sync_thread.start()
        self.DEBUG_PRINT()
        return True

    def _check_line(self, before_server):
        status = self.client.sentto(self.father_server, 6814, ["0", "2", str(self.level)], 3)
        if status == "{%200%}":
            return True
        else:
            return False

    def check_line(self):
        self_index = self.server_list.index(self.lan_ip)
        before_server = self.server_list[self_index - 1]
        if not self._check_line(before_server):
            server_list = [x for x in self.server_list]
            server_list.remove(before_server)
            check_dict = self.sent_message_thread(["4", before_server], 6814, server_list)
            if "{%ONLINE%}" in check_dict.values():
                return True
            else:
                self.sent_message_thread(["8", before_server], 6814, server_list)
                self.remove_usable_list(before_server)
        return True

    def client_outline(self, client_addr, outline_type="0"):
        self.client_list.remove(client_addr)
        self.sent_message_thread(["5", "sync_client_list"], 6814, self.client_list, 3)
        print "outline_type"
        print outline_type
        if outline_type != "1":
            print "客户下线，移除可用列表"
            self.remove_usable_list(client_addr)
        if len(self.client_list) < self.max_client_n:
            self.server_usable = True
            self.add_usable_list(self.lan_ip, str(self.level))
        self.DEBUG_PRINT()

    def clear_unusable_thread(self):
        while not self.shutdown_s:
            if len(self.unusable_server_list) > 0:
                unusable_server = self.unusable_server_list.pop()
                status = self.client.sentto(unusable_server, 6814, ["9", "check_server_usable"], 3)
                if status != "{%200%}":
                    self.remove_usable_list(unusable_server)
            else:
                break

    def _client_check_father(self):
        status = self.client.sentto(self.father_server, 6814, ["0","1",str(self.level)], 3)
        return status

    def client_check_father(self):
        status = self._client_check_father()
        if status == None or status == "{%F_OUTLINE%}":
            print "父服务器下线"
            if not self.replace_require_mutex.acquire(10):
                print "Important Error:replace_require_mutex致命错误！"
                return False
            self.replace_key = str(random.randint(0,9999999999))
            father_server_temp = self.father_server
            self.reserve_replace_dict[self.replace_key] = ""
            self.client.sentto(self.lan_ip, 6814, ["12", self.lan_ip, self.replace_key])
            replace_start = time.clock()
            replace_n = 0
            while not self.shutdown_s:
                time.sleep(1)
                if self.server_type == "father_server" or self._client_check_father() == "{%200%}":
                    self.remove_usable_list(father_server_temp)
                    print "成功替换父服务器！"
                    break
                if time.clock() - replace_start > 50.0:
                    if self.reserve_replace_server != "":
                        if self._check_server(self.reserve_replace_server):
                            replace_start = time.clock()
                            continue
                    print "替换父服务器超时，重试！"
                    self.reserve_replace_server = ""
                    self.reserve_replace_dict[self.replace_key] = ""
                    self.client.sentto(self.lan_ip, 6814, ["12", self.lan_ip, self.replace_key])
                    replace_n = replace_n + 1
                    replace_start = time.clock()
                if replace_n >= 5:
                    print "替换父服务器失败！"
                    print "异常错误，进入离线模式！"
                    self.shutdown()
                    # TODO 紧急响应
                    break
            self.replace_require_mutex.release()
            self.DEBUG_PRINT()
            return True
        elif status == "{%200%}":
            return True
        elif status == "{%C_OUTLINE%}":
            print "客户超时...尝试重新加入父服务器"
            replace_success = False
            for i in range(6):
                result_dict = self.sent_message_thread(["16", "get_father_server"], 6814, self.server_list)
                result_list = [x for x in result_dict.values() if x != None]
                result_temp = []
                while len(result_list) > 0:
                    result_temp.append(self.pop_list_most(result_list))
                if len(result_temp) > 0:
                    for father_server in result_temp:
                        father_server_re = re.match(r"\d+\.\d+\.\d+\.\d+", father_server)
                        if father_server_re:
                            if self.join_server(father_server):
                                print "重新加入父服务器成功！"
                                if len(self.client_list) > 0:
                                    sync_thread = threading.Thread(target=self.sent_message_thread,
                                                                   args=(["11", "sync_F_Z_G"], 6814, self.client_list))
                                    sync_thread.start()
                                replace_success = True
                                return True
                print "替换失败...5秒后重试"
                time.sleep(5)
            if not replace_success:
                print "重新加入父服务器失败！进入离线模式！"
                self.shutdown()
                # TODO 紧急响应
        else:
            return False

    def check_client_thread(self):
        self.check_client_start = time.clock()
        while not self.shutdown_s:
            time.sleep(1)
            if time.clock() - self.check_client_start >= 5.0:
                if len(self.client_list) > 0:
                    client_list_temp = [x for x in self.client_list]
                    response_dict = self.sent_message_thread(["0", ""], 6814, client_list_temp, 3)
                    for client in client_list_temp:
                        if client in response_dict.keys():
                            if response_dict[client] != "{%200%}":
                                print "客户超时下线"
                                self.client_outline_busy = True
                                self.client_outline(client)
                                self.client_outline_busy = False
                                self.DEBUG_PRINT()
                        else:
                            print "client不存在于response_dict"
                self.check_client_start = time.clock()

    def check_server_thread(self):
        self.check_server_start = time.clock()
        check_client = threading.Thread(target=self.check_client_thread)
        check_client.start()
        check_network = threading.Thread(target=self.check_network_thread)
        check_network.start()
        if len(self.unusable_server_list) > 0:
            clear_unusable = threading.Thread(target=self.clear_unusable_thread)
            clear_unusable.start()
        while not self.shutdown_s:
            time.sleep(1)
            if self.server_type != "father_server":
                if time.clock() - self.check_server_start >= 7.0:
                    print "father sent check time out"
                    if self.server_list[0] == self.lan_ip:
                        self.client_check_father()
                        self.check_server_start = time.clock()
                    else:
                        self.check_line()
                        self.check_server_start = time.clock()

    def searching_handle(self):
        self._search_full_list = []
        self._search_usable_list = []
        self._search_all_list = []
        pointer = 0
        func = lambda x,y:x if y in x else x + [y]
        while not self.shutdown_s:
            time.sleep(0.1)
            if not self.server_queue.empty():
                temp = self.server_queue.get()
                if temp[1] == "usable":
                    self._search_usable_list.append(temp[0])
                elif temp[1] == "full":
                    self._search_full_list.append(temp[0])
                self._search_all_list.append(temp[0])
                l_temp = reduce(func, [[], ] + self._search_all_list)
                if len(l_temp) == len(self._search_all_list):
                    print "发现服务器，尝试获取可用服务器列表！"
                else:
                    print "去重"
                    self._search_all_list = l_temp
                    continue
                print "self._search_all_list[pointer]"
                print self._search_all_list[pointer]
                d_temp = self.sync_dict_from(self._search_all_list[pointer], "usable_server_dict")
                if not d_temp == "None":
                    self.usable_server_dict = d_temp
                    usable_list = sorted(self.usable_server_dict.iteritems(), key=lambda d:d[0])
                    for x in usable_list:
                        for server in x[1]:
                            if self.join_server(server):
                                check_thread = threading.Thread(target=self.check_server_thread)
                                check_thread.start()
                                self.search_status = "done"
                                print "加入服务器成功！"
                                self.DEBUG_PRINT()
                                return True
                            else:
                                self.unusable_server_list.append(server)
                                print "加入服务器失败！"
                else:
                    print "同步usable_server_dict失败"
                pointer = pointer + 1
            elif self.search_completed:
                print "等待响应..."
                time.sleep(3)
                break
        self._search_usable_list = reduce(func, [[], ] + self._search_usable_list)
        self._search_full_list = reduce(func, [[], ] + self._search_full_list)
        return False

    def b2bstart(self):
        if len(self._search_all_list) == 0:
            print "暂时没发现内网服务器，本机将成为母体！"
            self.server_type = "father_server"
            self.zero_server_list = [self.lan_ip]
            self.server_list.append(self.lan_ip)
            self.usable_server_list.append(self.lan_ip)
            self.usable_server_dict["0"] = [self.lan_ip]
            self.server_usable = True
            #TODO sync resource
            check_thread = threading.Thread(target=self.check_server_thread)
            check_thread.start()
            self.search_status = "done"
            return
        elif len(self._search_usable_list) > 0:
            print "发现空闲服务器，正在尝试加入服务器..."
            for server in self._search_usable_list:
                if self.join_server(server):
                    check_thread = threading.Thread(target=self.check_server_thread)
                    check_thread.start()
                    self.search_status = "done"
                    print "加入服务器成功！"
                    self.DEBUG_PRINT()
                    return
                else:
                    print "加入服务器失败！"
        elif len(self._search_full_list) > 0:
            print "加入服务器失败，尝试强制插入服务器队列！"
            for server in self._search_full_list:
                if self.join_server(server):
                    check_thread = threading.Thread(target=self.check_server_thread)
                    check_thread.start()
                    self.search_status = "done"
                    print "强制加入服务器成功！"
                    return
                else:
                    print "强制加入服务器失败！"
            print "强制加入服务器失败，请检查网络！进入离线模式！"
        print "加入服务器异常！请检查网络状态或稍后重新启动"
        self.shutdown()
        # TODO 离线模式
        # TODO 加入失败就离线

    def DEBUG_PRINT(self):
        while True:
            if not self.DEBUG_BUSY:
                self.DEBUG_BUSY = True
                print "++++++++DEBUG+++++++"
                print "D:father_server:"
                print self.father_server
                print "D:grandpa_server:"
                print self.grandpa_server
                print "D:usable_server_dict:"
                print self.usable_server_dict
                print "D:server_usable:"
                print self.server_usable
                print "D:zero_server_list:"
                print self.zero_server_list
                print "D:server_list:"
                print self.server_list
                print "D:father_server_list:"
                print self.father_server_list
                print "D:client_list:"
                print self.client_list
                print "D:level:"
                print self.level
                print "D:server_type:"
                print self.server_type
                print "D:lan_ip:"
                print self.lan_ip
                print "++++++++END+++++++"
                self.DEBUG_BUSY = False
                break
            else:
                time.sleep(0.1)

    def self_outline(self):
        while True:
            if self.client_outline_busy:
                continue
            if self.loop_busy:
                continue
            self.shutdown_s = True
            if self.replace_require_mutex.acquire(0):
                if self.replace_handle_mutex.acquire(0):
                    print "开始下线"
                    self.outline = True
                    start = time.clock()
                    if self.father_server != "":
                        status = self.client.sentto(self.father_server, 6814, ["14", "0"], 10)
                        if status != "{%200%}":
                            self.sent_message_thread(["19", "remove_server_in_server_list"], 6814, self.server_list, 5)
                    while True:
                        if time.clock() - start > 5.0:
                            break
                        else:
                            time.sleep(1)
                    return True
                else:
                    self.replace_require_mutex.release()
            time.sleep(0.1)

    def shutdown(self):
        print "end"
        if not self.outline:
            self.self_outline()
            self.search_server.shutdown()
            self.server.shutdown()

def start():
    global b2b
    status = [False]
    b2b = B2B(status)
    if status[0]:
        b2b.start()
        b2b.DEBUG_PRINT()
    return b2b