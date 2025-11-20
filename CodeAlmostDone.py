#!/usr/bin/env python3
"""
Versão corrigida e reforçada do jogo em rede (UDP/TCP).
Melhorias: correção scout dx/dy, checagem recv vazio, SO_REUSEADDR,
timeouts, bind antes de broadcast, decodificação segura, separação de comando/args.
"""

import socket
import threading
import random
import time
import sys
import ast
import traceback

# --- Configurações Globais ---
UDP_PORT = 5000
TCP_PORT = 5001
GRID_SIZE = 10
BROADCAST_ADDR = '255.255.255.255'

# --- Estado do Jogo ---
participants = set()
my_position = (0, 0)
my_ip = ""
times_hit = 0
players_hit = set()
game_running = True
move_penalty = False
lock = threading.Lock()

# --- Configurações adicionais ---
TCP_SEND_TIMEOUT = 3.0  # timeout ao tentar enviar via TCP
SERVER_ACCEPT_TIMEOUT = 1.0  # timeout no accept()/recv() dos servidores
UDP_RECV_TIMEOUT = 1.0

# -------------------------
# UTILIDADES
# -------------------------
def safe_decode(data):
    """Decodifica bytes para str de forma segura."""
    try:
        return data.decode().strip()
    except Exception:
        # tenta com erros substituídos
        try:
            return data.decode(errors='replace').strip()
        except Exception:
            return ""

def print_exc_context(prefix=""):
    """Imprime traceback para debug de exceptions."""
    print(prefix)
    traceback.print_exc()

# =============================================================================
# COMUNICAÇÃO
# =============================================================================

def get_my_ip():
    """Descobre IP local 'visível' conectando a um destino externo (não envia dados)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # destino arbitrário; não envia pacotes
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def send_broadcast_udp(message):
    """Envia mensagem UDP em broadcast. Faz bind em porta efêmera antes de enviar."""
    try:
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Reuseaddr pode ajudar em alguns sistemas
        try:
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        # bind em porta efêmera para controlar interface de envio em alguns ambientes
        try:
            udp_socket.bind(('', 0))
        except Exception:
            pass
        udp_socket.sendto(message.encode(), (BROADCAST_ADDR, UDP_PORT))
        udp_socket.close()
        print(f"[UDP Broadcast Enviado]: {message}")
    except Exception as e:
        print(f"Erro ao enviar broadcast: {e}")
        print_exc_context()

def send_udp_to_all(message):
    """Envia UDP para cada participante conhecido (thread-safe)."""
    with lock:
        current_participants = list(participants)
    try:
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for ip in current_participants:
            try:
                udp_socket.sendto(message.encode(), (ip, UDP_PORT))
            except Exception as e:
                print(f"Erro ao enviar UDP para {ip}: {e}")
        udp_socket.close()
        if message != "saindo":
            print(f"[UDP Enviado para Todos]: {message}")
    except Exception as e:
        print(f"Erro ao enviar UDP para todos: {e}")
        print_exc_context()

def send_tcp_message(ip, message, timeout=TCP_SEND_TIMEOUT):
    """Envia uma mensagem TCP, com timeout e tratamento."""
    try:
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.settimeout(timeout)
        tcp_socket.connect((ip, TCP_PORT))
        tcp_socket.sendall(message.encode())
        tcp_socket.close()
        print(f"[TCP Enviado para {ip}]: {message}")
    except Exception as e:
        print(f"Erro ao enviar TCP para {ip}: {e}")
        # print_exc_context()  # útil em debug

# =============================================================================
# LÓGICA DE MENSAGENS
# =============================================================================

def handle_message(data, ip, protocol, tcp_conn=None):
    """Processa mensagens recebidas (UDP ou TCP)."""
    global times_hit
    try:
        message = safe_decode(data)
        if message == "":
            return
        print(f"[Mensagem {protocol.upper()} Recebida de {ip}]: {message}")

        # --- Conexão ---
        if message == "Conectando":
            list_str = None
            with lock:
                if ip not in participants and ip != my_ip:
                    participants.add(ip)
                    print(f"Novo participante: {ip}")
                    print(f"Lista de participantes atualizada: {list(participants)}")
                    # inclui todos que conheço + eu mesmo
                    all_ips = set(participants)
                    if my_ip:
                        all_ips.add(my_ip)
                    list_str = f"participantes:{list(all_ips)}"
            # responde via TCP com a lista (se tiver algo novo para mandar)
            if list_str is not None:
                try:
                    send_tcp_message(ip, list_str)
                except Exception:
                    pass

        elif message.startswith("participantes:"):
            try:
                ip_list_str = message.split(":", 1)[1].strip()
                new_ips = ast.literal_eval(ip_list_str)
                with lock:
                    updated = False
                    for new_ip in new_ips:
                        if new_ip not in participants and new_ip != my_ip:
                            participants.add(new_ip)
                            updated = True
                    if updated:
                        print(f"Lista de participantes atualizada: {list(participants)}")
            except Exception as e:
                print(f"Erro ao processar lista de participantes: {e}")
                print_exc_context()

        # --- Jogo: shot (UDP) ---
        elif message.startswith("shot:"):
            try:
                coords = message.split(':', 1)[1].split(',')
                x, y = int(coords[0]), int(coords[1])
                with lock:
                    if (x, y) == my_position:
                        print(f"ALERTA: Fui atingido por 'shot' de {ip}!")
                        times_hit += 1
                        # Responde com "hit" via TCP
                        send_tcp_message(ip, "hit")
            except Exception as e:
                print(f"Erro ao processar 'shot': {e}")
                print_exc_context()

        # --- Jogo: scout (TCP preferido) ---
        elif message.startswith("scout:"):
            try:
                coords = message.split(':', 1)[1].split(',')
                shot_x, shot_y = int(coords[0]), int(coords[1])

                with lock:
                    my_x, my_y = my_position

                if (shot_x, shot_y) == (my_x, my_y):
                    print(f"ALERTA: Fui atingido por 'scout' de {ip}!")
                    with lock:
                        times_hit += 1
                    # responde abrindo TCP de volta
                    send_tcp_message(ip, "hit")
                else:
                    # dx = sign(my_x - shot_x), dy = sign(my_y - shot_y)
                    if my_x > shot_x:
                        dx = 1
                    elif my_x < shot_x:
                        dx = -1
                    else:
                        dx = 0

                    if my_y > shot_y:
                        dy = 1
                    elif my_y < shot_y:
                        dy = -1
                    else:
                        dy = 0

                    info_msg = f"info:{dx},{dy}"
                    send_tcp_message(ip, info_msg)
            except Exception as e:
                print(f"Erro ao processar 'scout': {e}")
                print_exc_context()

        elif message == "hit":
            print(f"SUCESSO: Você atingiu {ip}!")
            with lock:
                players_hit.add(ip)

        elif message.startswith("info:"):
            print(f"INFO (Scout): Pista de {ip}: {message}")

        elif message == "moved":
            print(f"INFO: Jogador {ip} se moveu.")

        elif message == "saindo":
            print(f"INFO: Jogador {ip} saiu do jogo.")
            with lock:
                if ip in participants:
                    participants.remove(ip)
                    print(f"Lista de participantes atualizada: {list(participants)}")

        else:
            print(f"Mensagem desconhecida de {ip}: {message}")

    except Exception as e:
        print(f"Erro geral ao processar mensagem de {ip}: {e}")
        print_exc_context()

# =============================================================================
# TCP CLIENT HANDLER
# =============================================================================

def handle_tcp_client(connection, addr):
    """Lida com uma conexão TCP - pode receber múltiplas mensagens curtas."""
    ip = addr[0]
    try:
        connection.settimeout(1.0)
        while True:
            try:
                data = connection.recv(4096)
            except socket.timeout:
                # continua esperando por novas mensagens, até a conexão fechar
                continue
            except Exception:
                # erro de recv: encerra o handler
                break

            if not data:
                # conexão fechada pela outra ponta
                break

            # processa a mensagem, permitindo respostas através da mesma conexão
            handle_message(data, ip, 'tcp', tcp_conn=connection)

    except Exception as e:
        print(f"Erro ao lidar com cliente TCP {ip}: {e}")
        print_exc_context()
    finally:
        try:
            connection.close()
        except Exception:
            pass

# =============================================================================
# THREADS DE SERVIDOR
# =============================================================================

def udp_server_thread():
    """Thread que escuta UDP."""
    global game_running
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    try:
        udp_socket.bind(('', UDP_PORT))
    except Exception as e:
        print(f"Falha ao bindar UDP ({UDP_PORT}): {e}")
        print_exc_context()
        return

    udp_socket.settimeout(UDP_RECV_TIMEOUT)
    print(f"[*] Escutando UDP na porta {UDP_PORT}...")

    while game_running:
        try:
            data, addr = udp_socket.recvfrom(4096)
            sender_ip = addr[0]
            # ignora mensagens locais de loopback e as próprias mensagens (se desejar)
            if sender_ip == my_ip or sender_ip == "127.0.0.1":
                continue
            handle_message(data, sender_ip, 'udp')
        except socket.timeout:
            continue
        except Exception as e:
            if game_running:
                print(f"Erro no servidor UDP: {e}")
                print_exc_context()
    try:
        udp_socket.close()
    except Exception:
        pass
    print("Servidor UDP encerrado.")

def tcp_server_thread():
    """Thread que aceita conexões TCP e cria handlers."""
    global game_running
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass

    try:
        tcp_socket.bind(('', TCP_PORT))
        tcp_socket.listen(5)
    except Exception as e:
        print(f"Falha ao criar servidor TCP ({TCP_PORT}): {e}")
        print_exc_context()
        return

    tcp_socket.settimeout(SERVER_ACCEPT_TIMEOUT)
    print(f"[*] Escutando TCP na porta {TCP_PORT}...")

    while game_running:
        try:
            conn, addr = tcp_socket.accept()
            sender_ip = addr[0]
            if sender_ip == my_ip or sender_ip == "127.0.0.1":
                # fecha conexões locais indesejadas
                try:
                    conn.close()
                except Exception:
                    pass
                continue
            # cria thread para tratar essa conexão
            client_handler = threading.Thread(target=handle_tcp_client, args=(conn, addr), daemon=True)
            client_handler.start()
        except socket.timeout:
            continue
        except Exception as e:
            if game_running:
                print(f"Erro no servidor TCP: {e}")
                print_exc_context()
    try:
        tcp_socket.close()
    except Exception:
        pass
    print("Servidor TCP encerrado.")

# =============================================================================
# JOGO E INTERFACE
# =============================================================================

def initialize_game():
    global my_position, my_ip
    my_ip = get_my_ip()
    my_position = (random.randint(0, GRID_SIZE - 1), random.randint(0, GRID_SIZE - 1))
    print(f"Meu IP: {my_ip}")
    print(f"Meu navio está na posição: {my_position}")

def calculate_score():
    with lock:
        score = len(players_hit) - times_hit
        return score, len(players_hit), times_hit

def print_status():
    with lock:
        print("\n" + "="*30)
        print(f"Posição Atual: {my_position}")
        print(f"Participantes: {list(participants)}")
        print(f"Atingido: {times_hit} vez(es)")
        print(f"Atingiu: {len(players_hit)} jogador(es) únicos")
        print("="*30 + "\n")

def parse_input_preserve(raw_input):
    """
    Recebe a string completa do usuário (sem lower) e retorna:
    (cmd, args_list)
    cmd é lowercased; args preservam case (importante para IPs).
    """
    raw = raw_input.strip()
    if raw == "":
        return "", []
    parts = raw.split()
    cmd = parts[0].lower()
    args = parts[1:]
    return cmd, args

def main():
    global game_running, move_penalty, my_ip
    initialize_game()

    # inicia servidores
    udp_thread = threading.Thread(target=udp_server_thread, daemon=True)
    tcp_thread = threading.Thread(target=tcp_server_thread, daemon=True)
    udp_thread.start()
    tcp_thread.start()

    # dá um segundo para iniciar
    time.sleep(1)

    # anuncia presença
    send_broadcast_udp("Conectando")

    try:
        while game_running:
            print_status()

            if move_penalty:
                print("Penalidade de movimento: esperando 10s adicionais...")
                # Espera em passos para ser mais responsivo ao shutdown
                for _ in range(10):
                    if not game_running:
                        break
                    time.sleep(1)
                move_penalty = False

            print("Próxima ação em 10 segundos...")
            # aguarda 10s (em pequenos passos para responder a shutdown)
            for _ in range(10):
                if not game_running:
                    break
                time.sleep(1)
            if not game_running:
                break

            # coleta input (bloqueante)
            raw = input("Ação (shot X Y | scout X Y IP | move {+|-}{x|y} | sair): ")
            cmd, args = parse_input_preserve(raw)
            if not cmd:
                continue
            print(f"[Ação Enviada]: {raw}")

            if cmd == "shot":
                if len(args) == 2:
                    try:
                        x = int(args[0]); y = int(args[1])
                        send_udp_to_all(f"shot:{x},{y}")
                    except ValueError:
                        print("Coordenadas devem ser inteiros. Use: shot X Y")
                else:
                    print("Formato inválido. Use: shot X Y")

            elif cmd == "scout":
                if len(args) == 3:
                    try:
                        x = int(args[0]); y = int(args[1]); ip = args[2]
                        send_tcp_message(ip, f"scout:{x},{y}")
                    except ValueError:
                        print("Coordenadas devem ser inteiros. Use: scout X Y IP")
                else:
                    print("Formato inválido. Use: scout X Y IP")

            elif cmd == "move":
                if len(args) == 1:
                    move = args[0]
                    valid_move = False
                    with lock:
                        x, y = my_position
                        if move == "+x" and x < GRID_SIZE - 1:
                            x += 1; valid_move = True
                        elif move == "-x" and x > 0:
                            x -= 1; valid_move = True
                        elif move == "+y" and y < GRID_SIZE - 1:
                            y += 1; valid_move = True
                        elif move == "-y" and y > 0:
                            y -= 1; valid_move = True

                        if valid_move:
                            my_position = (x, y)
                            print(f"Nova posição: {my_position}")
                            send_udp_to_all("moved")
                            move_penalty = True
                        else:
                            print("Movimento inválido ou fora dos limites.")
                else:
                    print("Formato inválido. Use: move {+|-}{x|y}")

            elif cmd == "sair":
                game_running = False
                send_udp_to_all("saindo")
                break

            else:
                print("Comando inválido.")

    except KeyboardInterrupt:
        print("\nSaindo por (Ctrl+C)...")
        game_running = False
        send_udp_to_all("saindo")
    except Exception as e:
        print(f"Erro no loop principal: {e}")
        print_exc_context()
        game_running = False
        send_udp_to_all("saindo")

    # finalização: aguarda término das threads (pequena espera)
    time.sleep(1)

    score, p_hit, t_hit = calculate_score()
    print("\n" + "*"*30)
    print("SCORE FINAL")
    print(f"Vezes que foi atingido: {t_hit}")
    print(f"Jogadores únicos atingidos: {p_hit}")
    print(f"Score Total (Jogadores Atingidos - Vezes Atingido): {score}")
    print("*"*30)

if __name__ == "__main__":
    main()
