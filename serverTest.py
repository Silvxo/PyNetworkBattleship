import socket
import pygame
import threading
import time

# =========================
# CONFIG REDE (troque conforme o PC)
# =========================
LOCAL_IP = "191.4.248.14"   # seu IP local
UDP_PORT = 5000
REMOTE_IPs = ["191.4.248.15", "191.4.248.15"]  # IP do outro jogador
TCP_PORT = 5001

#Conexão TCP
socket_tcp_receive = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
socket_tcp_receive.connect(('localhost', TCP_PORT))
socket_tcp_receive.listen()

#Conexão UDP
socket_udp_receive = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
socket_udp_receive.bind('localhost', UDP_PORT)
socket_udp_receive.listen()

#Recebe UDP
def receive_udp():
    global data_udp, addr_udp
    data_udp, addr_udp = socket_udp_receive.recvfrom(1024)

#Recebe TCP
def receive_tcp():
    global data_tcp
    data_tcp = socket_tcp_receive.recv(1024)

#Inicia Threads
threading.Thread(target=receive_udp, daemon=True).start()
threading.Thread(target=receive_tcp, daemon=True).start()

#Envia TCP
def envia_tcp(data, address):
    socket_tcp_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    socket_tcp_send.connect((address, TCP_PORT))
    socket_tcp_send.sendall(data.encode('utf-8'))

#Envia UDP
def envia_udp(data, address):
    socket_udp_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    socket_udp_send.sendto(data.encode('utf-8'), ((address, UDP_PORT)))

while True:
    print(data_tcp.decode('utf-8'))
    time.sleep(1)