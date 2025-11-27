#!/usr/bin/env python3
"""
PyNetworkBattleship - Network-based Battleship game.
Main game logic, networking, and state machine.

Networking: UDP/TCP on local network.
Grid: 10x10 cells.
UI: Optional Pygame interface (falls back to console).
"""

import socket
import threading
import random
import time
import sys
import ast
import traceback

# Importa componentes do ui.py
try:
    from ui import MenuScreen, ScoreScreen, PygameInterface, PYGAME_AVAILABLE
except Exception as e:
    print(f"Warning: Could not import UI components: {e}")
    PYGAME_AVAILABLE = False
    
    # Classes dummy
    class MenuScreen:
        def __init__(self): pass
        def start(self): pass
        def join(self, timeout=None): pass
        @property
        def choice(self): return "play"
    
    class ScoreScreen:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def join(self, timeout=None): pass
        @property
        def choice(self): return "menu"
    
    class PygameInterface:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def stop(self): pass
        def join(self, timeout=None): pass

UDP_PORT = 5000
TCP_PORT = 5001
GRID_SIZE = 10
BROADCAST_ADDR = '255.255.255.255'

participants = set()
my_position = (0, 0)
my_ip = ""
times_hit = 0
players_hit = set()
game_running = True
move_penalty = False
moved = False
lock = threading.Lock()
ui_instance = None

# --- Network Configuration ---
TCP_SEND_TIMEOUT = 3.0
SERVER_ACCEPT_TIMEOUT = 1.0
UDP_RECV_TIMEOUT = 1.0


# -------------------------
# UTILIDADES
# -------------------------
def safe_decode(data):
    #Decodifica bytes para str de forma segura
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
    #Descobre IP local 'visível' conectando a um destino externo (não envia dados)
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
    #Envia mensagem UDP em broadcast
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
    #Envia UDP para cada participante conhecido (thread-safe)
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
    #Envia uma mensagem TCP, com timeout e tratamento
    try:
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.settimeout(timeout)
        tcp_socket.connect((ip, TCP_PORT))
        tcp_socket.sendall(message.encode())
        tcp_socket.close()
        print(f"[TCP Enviado para {ip}]: {message}")
    except Exception as e:
        print(f"Erro ao enviar TCP para {ip}: {e}")
        # print_exc_context()  # debug

# =============================================================================
# LÓGICA DE MENSAGENS
# =============================================================================

def handle_message(data, ip, protocol, tcp_conn=None, ui=None):
    #Processa mensagens recebidas (UDP ou TCP)
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

        elif message.startswith("shot:"):
            try:
                coords = message.split(':', 1)[1].split(',')
                x, y = int(coords[0]), int(coords[1])
                with lock:
                    if (x, y) == my_position:
                        print(f"ALERTA: Fui atingido por 'shot' de {ip}!")
                        times_hit += 1
                        if ui is not None:
                            ui._add_action(f"HIT por {ip}")
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
                    if ui is not None:
                        ui._add_action(f"HIT por {ip}")
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
            if ui is not None:
                ui._add_action(f"SHOT hit {ip}")

        elif message.startswith("info:"):
            print(f"INFO (Scout): Pista de {ip}: {message}")
            if ui is not None:
                ui._add_action(f"scout info {ip}: {message}")

        elif message == "moved":
            print(f"INFO: Jogador {ip} se moveu.")
            ui._add_action(f"INFO: Jogador {ip} se moveu.")

        elif message == "saindo":
            print(f"INFO: Jogador {ip} saiu do jogo.")
            ui._add_action(f"INFO: Jogador {ip} saiu do jogo.")
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
            handle_message(data, ip, 'tcp', tcp_conn=connection, ui=ui_instance)

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
            handle_message(data, sender_ip, 'udp', ui=ui_instance)
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

def shutdown_servers():
    """Gracefully shutdown UDP and TCP servers."""
    global game_running, udp_socket, tcp_socket
    game_running = False
    time.sleep(0.5)  # Give threads time to notice game_running = False
    
    try:
        if udp_socket:
            udp_socket.close()
    except Exception:
        pass
    
    try:
        if tcp_socket:
            tcp_socket.close()
    except Exception:
        pass

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





def shutdown_servers():
    """Gracefully shutdown UDP and TCP servers."""
    global game_running, udp_socket, tcp_socket
    game_running = False
    time.sleep(0.5)  # Give threads time to notice game_running = False
    
    try:
        if udp_socket:
            udp_socket.close()
    except Exception:
        pass
    
    try:
        if tcp_socket:
            tcp_socket.close()
    except Exception:
        pass


def main():
    """Main game loop with state machine: MENU -> GAME -> SCORE -> MENU"""
    global game_running, move_penalty, moved, my_ip, my_position, ui_instance
    
    state = "MENU"  #Inicia no estado MENU

    while True:
        if state == "MENU":
            # Tela do menu
            menu = MenuScreen()
            menu.start()
            menu.join()
            
            if menu.choice == "play":
                state = "INIT_GAME"
            elif menu.choice == "quit" or menu.choice is None:
                print("Saindo do jogo...")
                return

        elif state == "INIT_GAME":
            # Initialize game and start servers
            game_running = True
            initialize_game()

            # Start servers
            udp_thread = threading.Thread(target=udp_server_thread, daemon=True)
            tcp_thread = threading.Thread(target=tcp_server_thread, daemon=True)
            udp_thread.start()
            tcp_thread.start()

            # Wait for servers to start
            time.sleep(1)

            # Announce presence
            send_broadcast_udp("Conectando")

            # Start Pygame UI
            ui_instance = None
            if PYGAME_AVAILABLE:
                try:
                    ui_instance = PygameInterface(
                        grid_size=GRID_SIZE,
                        my_position=my_position,
                        my_ip=my_ip,
                        participants=participants,
                        players_hit=players_hit,
                        times_hit=times_hit,
                        game_running_ref=globals(),
                        lock=lock,
                        send_udp_to_all=send_udp_to_all,
                        send_tcp_message=send_tcp_message
                    )
                    ui_instance.start()
                except Exception as e:
                    print(f"Falha ao iniciar interface Pygame: {e}")
                    print_exc_context()

            state = "GAME"

        elif state == "GAME":
            try:
                while game_running:
                    # If Pygame UI is running, don't use console input - just monitor game_running flag
                    if ui_instance is not None and ui_instance.is_alive():
                        # UI is handling all input, just wait for game_running to become False
                        time.sleep(0.5)
                        continue
                    
                    # Console-only mode (no Pygame)
                    print_status()

                    if move_penalty:
                        print("Penalidade de movimento: esperando 10s adicionais...")
                        for _ in range(10):
                            if not game_running:
                                break
                            time.sleep(1)
                        move_penalty = False

                    print("Próxima ação em 10 segundos...")
                    for _ in range(10):
                        if not game_running:
                            break
                        time.sleep(1)
                    if not game_running:
                        break

                    # coleta input
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
                                    move_penalty = True
                                    moved = True
                                else:
                                    print("Movimento inválido ou fora dos limites.")
                        else:
                            print("Formato inválido. Use: move {+|-}{x|y}")
                        if moved:
                            send_udp_to_all("moved")
                            moved = False
                    if game_running == False:
                        cmd = "sair"
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

            # Stop UI
            try:
                if ui_instance is not None:
                    ui_instance.stop()
                    if ui_instance.is_alive():
                        ui_instance.join(timeout=2.0)
            except Exception:
                pass

            # Shutdown servers gracefully
            shutdown_servers()
            time.sleep(1.0)  # Give pygame time to fully shut down before restarting

            # Calculate final score
            score, p_hit, t_hit = calculate_score()
            state = "SCORE"
            final_score = score
            final_hits = p_hit
            final_times_hit = t_hit

        elif state == "SCORE":
            # Show score screen
            score_screen = ScoreScreen(final_score, final_hits, final_times_hit)
            score_screen.start()
            if score_screen.is_alive():
                score_screen.join(timeout=5.0)  # Wait with timeout
            else:
                # Thread didn't start, use the default choice
                if not hasattr(score_screen, 'choice') or score_screen.choice is None:
                    score_screen.choice = "menu"

            if score_screen.choice == "menu":
                state = "MENU"
            else:
                # Window closed or timeout, return to menu
                state = "MENU"

if __name__ == "__main__":
    main()

