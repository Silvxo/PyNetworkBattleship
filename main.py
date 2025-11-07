import socket
import pygame
import threading
import time
 
# =========================
# CONFIG REDE (troque conforme o PC)
# =========================
LOCAL_IP = "191.4.248.28"   # seu IP local
UDP_PORT = 5000
REMOTE_IPs = ["191.4.248.15", "191.4.248.15"]  # IP do outro jogador
TCP_PORT = 5001
 
#Conexão TCP
socket_tcp_receive = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
socket_tcp_receive.bind((LOCAL_IP, TCP_PORT))
socket_tcp_receive.listen()
 
#Conexão UDP
socket_udp_receive = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
socket_udp_receive.bind((LOCAL_IP, UDP_PORT))

data_udp = 0
addr_udp = 0

data_tcp = 0
 
#Recebe UDP
def receive_udp():
    data_udp, addr_udp = socket_udp_receive.recvfrom(1024)
    print(data_udp)
    
 
#Recebe TCP
def receive_tcp():
    global data_tcp
    conn, addr = socket_tcp_receive.accept()
 
    with conn:
        while True:
            data_tcp = conn.recv(1024)
            print(data_tcp)
            if not data_tcp:
                break
            conn.sendall(data_tcp)
        conn.close()

 
#Inicia Threads
threading.Thread(target=receive_udp, daemon=True).start()
threading.Thread(target=receive_tcp, daemon=True).start()
 
#Envia TCP
def envia_tcp(data, address):
    try:
        socket_tcp_send = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_tcp_send.connect((address, TCP_PORT))
        socket_tcp_send.sendall(data.encode('utf-8'))
        print("Mensagem enviada com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar mensagem :/ \n Erro: {e}")
    finally:
        socket_tcp_send.close()
 
#Envia UDP
def envia_udp(data, address):
    try:
        socket_udp_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        socket_udp_send.sendto(data.encode('utf-8'), (address, UDP_PORT))
        print(f"Mensagem enviada!")
    except Exception as e:
        print(f"Erro ao enviar mensagem :/ \n Erro: {e}")
    finally:
        socket_udp_send.close()

mensagem = "Conectando"
envia_tcp(mensagem, REMOTE_IPs[0])

while True:
    envia_tcp(mensagem, REMOTE_IPs[0])
    if data_tcp != 0:
        print(data_udp)