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

# Optional pygame UI (imported safely)
try:
    import pygame
    PYGAME_AVAILABLE = True
except Exception:
    PYGAME_AVAILABLE = False

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
moved = False
lock = threading.Lock()
ui_instance = None  # Global reference to PygameInterface for logging

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
    #Envia mensagem UDP em broadcast. Faz bind em porta efêmera antes de enviar
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
    #Processa mensagens recebidas (UDP ou TCP); ui é a interface pygame para logging
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
                        if ui is not None:
                            ui._add_action(f"HIT by shot {ip}:{x},{y}")
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
                        ui._add_action(f"HIT by scout {ip}:{shot_x},{shot_y}")
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


class MenuScreen(threading.Thread):
    """Menu screen with Jogar and Sair options."""

    def __init__(self):
        super().__init__(daemon=True)
        self.running = False
        self.clock = None
        self.choice = None  # "play", "quit", or None

    def start(self):
        if not PYGAME_AVAILABLE:
            print("Pygame not available; menu disabled.")
            return
        self.running = True
        super().start()

    def stop(self):
        self.running = False

    def run(self):
        try:
            pygame.init()
            screen = pygame.display.set_mode((600, 400))
            pygame.display.set_caption('PyNetworkBattleship - Menu')
            self.clock = pygame.time.Clock()
            font_title = pygame.font.SysFont(None, 60)
            font_button = pygame.font.SysFont(None, 40)

            play_button_rect = pygame.Rect(150, 150, 300, 60)
            quit_button_rect = pygame.Rect(150, 250, 300, 60)

            while self.running and self.choice is None:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.choice = "quit"
                        self.running = False
                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        mx, my = pygame.mouse.get_pos()
                        if play_button_rect.collidepoint(mx, my):
                            self.choice = "play"
                            self.running = False
                        elif quit_button_rect.collidepoint(mx, my):
                            self.choice = "quit"
                            self.running = False

                # Draw background
                screen.fill((18, 24, 30))

                # Draw title
                title = font_title.render('PyNetworkBattleship', True, (100, 200, 255))
                title_rect = title.get_rect(center=(300, 50))
                screen.blit(title, title_rect)

                # Draw play button
                pygame.draw.rect(screen, (50, 150, 50), play_button_rect)
                play_txt = font_button.render('Jogar', True, (255, 255, 255))
                play_txt_rect = play_txt.get_rect(center=play_button_rect.center)
                screen.blit(play_txt, play_txt_rect)

                # Draw quit button
                pygame.draw.rect(screen, (200, 50, 50), quit_button_rect)
                quit_txt = font_button.render('Sair', True, (255, 255, 255))
                quit_txt_rect = quit_txt.get_rect(center=quit_button_rect.center)
                screen.blit(quit_txt, quit_txt_rect)

                pygame.display.flip()
                self.clock.tick(30)

        except Exception as e:
            print(f"Menu error: {e}")
            print_exc_context()
        finally:
            try:
                if PYGAME_AVAILABLE:
                    pygame.quit()
            except Exception:
                pass


class ScoreScreen(threading.Thread):
    """Score screen shown after game ends, with 'Voltar para o Menu' button."""

    def __init__(self, score, hits, times_hit):
        super().__init__(daemon=True)
        self.running = False
        self.clock = None
        self.choice = None  # "menu" or None
        self.score = score
        self.hits = hits
        self.times_hit = times_hit

    def start(self):
        if not PYGAME_AVAILABLE:
            print("Pygame not available; score screen disabled.")
            return
        self.running = True
        super().start()

    def stop(self):
        self.running = False

    def run(self):
        try:
            pygame.init()
            screen = pygame.display.set_mode((600, 400))
            pygame.display.set_caption('PyNetworkBattleship - Score')
            self.clock = pygame.time.Clock()
            font_title = pygame.font.SysFont(None, 70)
            font_info = pygame.font.SysFont(None, 30)
            font_button = pygame.font.SysFont(None, 35)

            back_button_rect = pygame.Rect(150, 300, 300, 60)

            while self.running and self.choice is None:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.choice = "menu"
                        self.running = False
                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        mx, my = pygame.mouse.get_pos()
                        if back_button_rect.collidepoint(mx, my):
                            self.choice = "menu"
                            self.running = False

                # Draw background
                screen.fill((18, 24, 30))

                # Draw score
                score_txt = font_title.render(f'SCORE: {self.score}', True, (100, 255, 100))
                score_rect = score_txt.get_rect(center=(300, 80))
                screen.blit(score_txt, score_rect)

                # Draw stats
                stats_txt = font_info.render(f'Hits: {self.hits} | Hit by: {self.times_hit}', True, (200, 200, 200))
                stats_rect = stats_txt.get_rect(center=(300, 180))
                screen.blit(stats_txt, stats_rect)

                # Draw back button
                pygame.draw.rect(screen, (50, 100, 200), back_button_rect)
                back_txt = font_button.render('Voltar para o Menu', True, (255, 255, 255))
                back_txt_rect = back_txt.get_rect(center=back_button_rect.center)
                screen.blit(back_txt, back_txt_rect)

                pygame.display.flip()
                self.clock.tick(30)

        except Exception as e:
            print(f"Score screen error: {e}")
            print_exc_context()
        finally:
            try:
                if PYGAME_AVAILABLE:
                    pygame.quit()
            except Exception:
                pass



class PygameInterface(threading.Thread):
    """Threaded Pygame interface with participants list, two-step scout, action cooldowns, and action history.

    - Left-click grid: send `shot:x,y` (if cooldown expired).
    - Right-click grid: move to cell and broadcast `moved` (20s cooldown, must be 1 block orthogonal).
    - Two-step scout: left-click IP to select, then left-click grid cell to send `scout:x,y IP`.
    - Action history scrolls below participants list.
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.running = False
        self.cell_size = 40
        self.margin = 20
        self.grid_px = GRID_SIZE * self.cell_size + self.margin * 2
        self.sidebar_width = 220
        self.button_height = 50  # space for Leave button below grid
        self.width = self.grid_px + self.sidebar_width
        self.height = self.grid_px + self.button_height
        self.clock = None

        # GUI state
        self.last_action_time = 0.0
        self.cooldown = 0.0
        self.selected_hover = None
        
        # Scout selection state
        self.scout_selected_ip = None  # IP selected for next scout action
        
        # Action history (thread-safe with lock)
        self.action_history = []  # list of (timestamp, action_str)
        self.history_scroll_offset = 0  # for scrolling
        
        # Leave button state
        self.leave_button_rect = None  # will be set during rendering
        
    def _add_action(self, action_str):
        """Add an action to the history log."""
        ts = time.time()
        self.action_history.append((ts, action_str))
        # keep last 50 actions
        if len(self.action_history) > 50:
            self.action_history.pop(0)

    def start(self):
        if not PYGAME_AVAILABLE:
            print("Pygame not available; GUI disabled.")
            return
        self.running = True
        super().start()

    def stop(self):
        self.running = False

    def _can_do_action(self):
        now = time.time()
        return (now - self.last_action_time) >= self.cooldown

    def _set_action(self, cooldown_secs):
        self.last_action_time = time.time()
        self.cooldown = cooldown_secs

    def run(self):
        try:
            pygame.init()
            screen = pygame.display.set_mode((self.width, self.height))
            pygame.display.set_caption('PyNetworkBattleship')
            self.clock = pygame.time.Clock()
            font = pygame.font.SysFont(None, 18)
            title_font = pygame.font.SysFont(None, 20)

            while self.running and game_running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        print("Pygame: quit requested")
                        try:
                            globals()['game_running'] = False
                        except Exception:
                            pass
                        self.running = False

                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        mx, my = pygame.mouse.get_pos()

                        # check Leave button click
                        if self.leave_button_rect is not None and self.leave_button_rect.collidepoint(mx, my):
                            self.show_score = True
                            self.score_show_time = time.time()
                            with lock:
                                globals()['game_running'] = False
                            send_udp_to_all("saindo")
                            print("Leaving game...")
                            self.running = False
                            continue

                        # clicked in participants sidebar
                        if mx >= self.grid_px:
                            # compute which participant index
                            with lock:
                                part_list = list(participants)
                            # top margin for list
                            top = 40
                            line_h = 20
                            idx = (my - top) // line_h
                            if 0 <= idx < len(part_list):
                                target_ip = part_list[idx]
                                # toggle selection: click same IP to deselect, different IP to select new one
                                if self.scout_selected_ip == target_ip:
                                    self.scout_selected_ip = None
                                    print(f"Scout deselected.")
                                else:
                                    self.scout_selected_ip = target_ip
                                    print(f"Scout selected: {target_ip}. Agora clique em uma célula do grid.")
                            continue

                        # clicked inside grid
                        gx = (mx - self.margin) // self.cell_size
                        gy = (my - self.margin) // self.cell_size
                        if gx < 0 or gy < 0 or gx >= GRID_SIZE or gy >= GRID_SIZE:
                            continue

                        # left click -> shot or scout (if IP selected)
                        if event.button == 1:
                            # if scout IP is selected, perform scout instead of shot
                            if self.scout_selected_ip is not None:
                                if not self._can_do_action():
                                    print("Aguarde cooldown antes de outra ação.")
                                else:
                                    try:
                                        send_tcp_message(self.scout_selected_ip, f"scout:{gx},{gy}")
                                        self._add_action(f"scout:{gx},{gy} -> {self.scout_selected_ip}")
                                        self._set_action(10.0)
                                        self.scout_selected_ip = None  # deselect after sending
                                    except Exception as e:
                                        print(f"Pygame: erro ao enviar scout para {self.scout_selected_ip}: {e}")
                            else:
                                # normal shot
                                if not self._can_do_action():
                                    print("Aguarde cooldown antes de outra ação.")
                                else:
                                    try:
                                        send_udp_to_all(f"shot:{gx},{gy}")
                                        self._add_action(f"shot:{gx},{gy}")
                                        self._set_action(10.0)
                                    except Exception as e:
                                        print(f"Pygame: erro ao enviar shot: {e}")

                        # right click -> move (20s cooldown) but only 1 block orthogonally
                        elif event.button == 3:
                            if not self._can_do_action():
                                print("Aguarde cooldown antes de outra ação.")
                            else:
                                try:
                                    with lock:
                                        cur_x, cur_y = my_position
                                    dx = abs(gx - cur_x)
                                    dy = abs(gy - cur_y)
                                    # allow only one block movement in a single axis (no diagonal)
                                    if (dx + dy) == 1:
                                        try:
                                            with lock:
                                                globals()['my_position'] = (gx, gy)
                                                globals()['moved'] = True
                                                globals()['move_penalty'] = True
                                            send_udp_to_all("moved")
                                            self._add_action(f"move:{gx},{gy}")
                                            self._set_action(20.0)
                                        except Exception as e:
                                            print(f"Pygame: erro ao mover: {e}")
                                    else:
                                        print("Movimento inválido: pode mover somente 1 bloco em x ou y (sem diagonal).")
                                except Exception as e:
                                    print(f"Pygame: erro ao validar movimento: {e}")

                # draw background and grid
                screen.fill((18, 24, 30))
                for i in range(GRID_SIZE + 1):
                    x = self.margin + i * self.cell_size
                    pygame.draw.line(screen, (120, 120, 120), (x, self.margin), (x, self.margin + GRID_SIZE * self.cell_size))
                    y = self.margin + i * self.cell_size
                    pygame.draw.line(screen, (120, 120, 120), (self.margin, y), (self.margin + GRID_SIZE * self.cell_size, y))

                # draw my position
                try:
                    with lock:
                        pos = my_position
                except Exception:
                    pos = None
                if pos is not None:
                    px = self.margin + pos[0] * self.cell_size + self.cell_size // 2
                    py = self.margin + pos[1] * self.cell_size + self.cell_size // 2
                    pygame.draw.circle(screen, (220, 50, 50), (px, py), int(self.cell_size * 0.35))

                # hover highlight
                mx, my = pygame.mouse.get_pos()
                gx = (mx - self.margin) // self.cell_size
                gy = (my - self.margin) // self.cell_size
                hover_valid = (0 <= gx < GRID_SIZE and 0 <= gy < GRID_SIZE)
                if hover_valid:
                    rx = self.margin + gx * self.cell_size
                    ry = self.margin + gy * self.cell_size
                    pygame.draw.rect(screen, (255, 255, 255), (rx, ry, self.cell_size, self.cell_size), 2)
                    self.selected_hover = (gx, gy)
                else:
                    self.selected_hover = None

                # sidebar: participants list
                sidebar_x = self.grid_px
                pygame.draw.rect(screen, (28, 34, 40), (sidebar_x, 0, self.sidebar_width, self.height))
                title = title_font.render('Participants', True, (230, 230, 230))
                screen.blit(title, (sidebar_x + 10, 10))
                with lock:
                    part_list = list(participants)
                top = 40
                line_h = 20
                for i, p in enumerate(part_list):
                    # highlight selected IP for scout
                    if p == self.scout_selected_ip:
                        color = (255, 200, 100)
                    else:
                        color = (200, 200, 200)
                    txt = font.render(p, True, color)
                    screen.blit(txt, (sidebar_x + 10, top + i * line_h))
                
                # action history
                hist_top = top + len(part_list) * line_h + 20
                hist_title = font.render('History', True, (230, 230, 230))
                screen.blit(hist_title, (sidebar_x + 10, hist_top))
                hist_top += 20
                hist_height = self.height - hist_top - 10
                
                # draw action history entries (scrollable)
                now = time.time()
                for i, (ts, action_str) in enumerate(self.action_history[self.history_scroll_offset:]):
                    if i * line_h >= hist_height:
                        break
                    # shorten to fit sidebar width
                    display_str = action_str[:28] if len(action_str) > 28 else action_str
                    hist_txt = font.render(display_str, True, (150, 150, 200))
                    screen.blit(hist_txt, (sidebar_x + 10, hist_top + i * line_h))

                # cooldown overlay/status
                now = time.time()
                remaining = 0.0
                if (now - self.last_action_time) < self.cooldown:
                    remaining = self.cooldown - (now - self.last_action_time)
                status_lines = [f"IP: {my_ip}", f"Pos: {my_position}", f"Players: {len(participants)}", f"Hits: {times_hit}"]
                for i, line in enumerate(status_lines):
                    surf = font.render(line, True, (230, 230, 230))
                    screen.blit(surf, (10, 10 + i * 18))

                if remaining > 0:
                    rem_s = int(remaining + 0.999)
                    cd_surf = title_font.render(f'Cooldown: {rem_s}s', True, (255, 200, 60))
                    screen.blit(cd_surf, (sidebar_x + 10, self.height - 30))

                # Button area background (below grid)
                pygame.draw.rect(screen, (18, 24, 30), (0, self.grid_px, self.grid_px, self.button_height))

                # Leave button (below grid, spanning width)
                button_y = self.grid_px + 10
                button_x = self.margin
                button_w = self.grid_px - self.margin * 2
                button_h = 30
                self.leave_button_rect = pygame.Rect(button_x, button_y, button_w, button_h)
                pygame.draw.rect(screen, (200, 50, 50), self.leave_button_rect)
                button_txt = font.render('Sair', True, (255, 255, 255))
                btn_rect = button_txt.get_rect(center=self.leave_button_rect.center)
                screen.blit(button_txt, btn_rect)

                # Show score if leaving
                pygame.display.flip()
                self.clock.tick(30)

        except Exception as e:
            print(f"Pygame UI error: {e}")
            print_exc_context()
        finally:
            try:
                if PYGAME_AVAILABLE:
                    pygame.quit()
            except Exception:
                pass



def main():
    """Main game loop with state machine: MENU -> GAME -> SCORE -> MENU"""
    global game_running, move_penalty, moved, my_ip, my_position, ui_instance
    
    state = "MENU"  # START with menu

    while True:
        if state == "MENU":
            # Show menu screen
            menu = MenuScreen()
            menu.start()
            menu.join()  # Wait for menu to finish
            
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
                    ui_instance = PygameInterface()
                    ui_instance.start()
                except Exception as e:
                    print(f"Falha ao iniciar interface Pygame: {e}")
                    print_exc_context()

            state = "GAME"

        elif state == "GAME":
            # Main game loop
            try:
                while game_running:
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

                    # Collect input (blocking)
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
                    ui_instance.join(timeout=1.0)
            except Exception:
                pass

            # Shutdown servers gracefully
            shutdown_servers()
            time.sleep(0.5)

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
            score_screen.join()  # Wait for score screen to finish

            if score_screen.choice == "menu":
                state = "MENU"
            else:
                # Window closed or timeout, return to menu
                state = "MENU"

if __name__ == "__main__":
    main()

