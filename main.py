import socket
import pygame
import threading

# =========================
# CONFIG REDE (troque conforme o PC)
# =========================
LOCAL_IP = "191.4.248.14"   # seu IP local
UDP_PORT = 5000
REMOTE_IPs = ["191.4.248.15", "191.4.248.15"]  # IP do outro jogador
TCP_PORT = 5001

#Conexão TCP
socket_tcp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
socket_tcp.connect(('localhost', TCP_PORT))

#Conexão UDP
socket_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
socket_udp.bind('localhost', UDP_PORT)

#Recebe UDP
def receive_udp():
    data, addr = socket_udp.recvfrom(1024)

#Recebe UDP
def receive_tcp():
    data = socket_tcp.recv(1024).decode()

#Inicia Threads
threading.Thread(target=receive_udp, daemon=True).start()
threading.Thread(target=receive_tcp, daemon=True).start()

#Envia TCP
def envia_tcp(data, address):
    socket_tcp.sendto(data.encode('utf-8'), address)

#Envia UDP
def envia_udp(data, address):
    socket_udp.sendto(data.encode('utf-8'), address)

#Recebe TCP



