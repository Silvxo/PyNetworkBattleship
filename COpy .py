#!/usr/bin/env python3
"""
Versão corrigida e reforçada do jogo em rede (UDP/TCP).
Melhorias: correção scout dx/dy, checagem recv vazio, SO_REUSEADDR,
timeouts, bind antes de broadcast, decodificação segura, separação de comando/args.

Nota: Apenas a seção "JOGO E INTERFACE" foi alterada conforme solicitado.
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
# (não alterada)
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
# (não alterado)
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
# (não alterado)
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
# -----------------
# >>> A PARTIR DAQUI APENAS ESTA SEÇÃO FOI MODIFICADA <<<
# =============================================================================

# ANSI colors (apenas para terminais que suportam)
ANSI_RESET = '\u001b[0m'
ANSI_RED = '\u001b[31m'
ANSI_GREEN = '\u001b[32m'
ANSI_YELLOW = '\u001b[33m'
ANSI_CYAN = '\u001b[36m'
ANSI_BOLD = '\u001b[1m'

# Pequeno histórico local (apenas para exibição no cliente)
history = []
HISTORY_MAX = 50


def add_history(entry, color=None):
    """Adiciona entrada ao histórico local e imprime formatada."""
    if color:
        entry_text = f"{color}{entry}{ANSI_RESET}"
    else:
        entry_text = entry
    history.append(entry_text)
    if len(history) > HISTORY_MAX:
        history.pop(0)
    print(entry_text)


def initialize_game():
    global my_ip
    my_ip = get_my_ip()
    add_history(f"Meu navio está na posição: {my_position}")


def calculate_score():
    with lock:
        score = len(players_hit) - times_hit
        # cópia para evitar race
        hit_list = list(players_hit)
        return score, len(players_hit), times_hit, hit_list


def print_status():
    """Mostra o status atual com informações mais claras e coloridas."""
    with lock:
        score, p_hit, t_hit, hit_list = calculate_score()
        print("\n" + "="*40)
        print(f"Posição Atual: {ANSI_BOLD}{my_position}{ANSI_RESET}")
        print(f"Participantes ({len(participants)}): {list(participants)}")
        print(f"Atingido (vezes): {ANSI_RED}{t_hit}{ANSI_RESET}")
        print(f"Atingiu (jogadores únicos): {ANSI_GREEN}{p_hit}{ANSI_RESET}")
        if hit_list:
            print(f"Jogadores atingidos: {hit_list}")
        else:
            print("Jogadores atingidos: nenhum")
        print("Últimas ações no cliente (histórico):")
        for h in history[-10:]:
            print(f"  {h}")
        print("="*40 + "\n")


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


# Botão SAIR (Tkinter) para permitir 'botão' que encerra o jogo
# (mantemos o código opcional - se tkinter não estiver disponível, ignora)

def start_exit_button():
    try:
        import tkinter as tk
    except Exception:
        add_history("(GUI SAIR não disponível: tkinter não encontrado)")
        return

    def on_exit():
        global game_running
        game_running = False
        try:
            root.destroy()
        except Exception:
            pass

    def run():
        global root
        root = tk.Tk()
        root.title("Controles - SAIR")
        root.geometry("200x80")
        btn = tk.Button(root, text="SAIR", command=on_exit)
        btn.pack(expand=True, fill='both', padx=10, pady=10)
        # botão como janela pequena sempre em cima
        try:
            root.attributes('-topmost', True)
        except Exception:
            pass
        root.mainloop()

    t = threading.Thread(target=run, daemon=True)
    t.start()


def print_help():
    add_history("Comandos disponíveis:")
    add_history("  shot X Y        -> Atira em coordenadas (UDP) ")
    add_history("  scout X Y IP    -> Scout (peça informação) via TCP; resposta chega assíncrona")
    add_history("  move {+|-}{x|y} -> Move seu navio (penalidade de movimento)")
    add_history("  sair            -> Sai do jogo e anuncia aos participantes")
    add_history("  help            -> Mostra esta ajuda")


def main():
    global game_running, move_penalty, my_ip
    initialize_game()

    # inicia servidores
    udp_thread = threading.Thread(target=udp_server_thread, daemon=True)
    tcp_thread = threading.Thread(target=tcp_server_thread, daemon=True)
    udp_thread.start()
    tcp_thread.start()

    # tenta iniciar botão SAIR
    start_exit_button()

    # dá um segundo para iniciar
    time.sleep(1)

    # anuncia presença
    send_broadcast_udp("Conectando")

    try:
        while game_running:
            print_status()

            if move_penalty:
                add_history("Penalidade de movimento ativa: aguardando 10s...")
                # Espera em passos para ser mais responsivo ao shutdown
                for _ in range(10):
                    if not game_running:
                        break
                    time.sleep(1)
                move_penalty = False

            add_history("Próxima ação em 10 segundos (ou digite antes)...")
            # aguarda 10s (em pequenos passos para responder a shutdown)
            for _ in range(10):
                if not game_running:
                    break
                time.sleep(1)
            if not game_running:
                break

            # coleta input (bloqueante)
            raw = input("Ação (shot X Y | scout X Y IP | move {+|-}{x|y} | help | sair): ")
            cmd, args = parse_input_preserve(raw)
            if not cmd:
                continue
            add_history(f"Ação enviada: {raw}")

            if cmd == "shot":
                if len(args) == 2:
                    try:
                        x = int(args[0]); y = int(args[1])
                        send_udp_to_all(f"shot:{x},{y}")
                        add_history(f"Você atirou em ({x},{y}) — aguardando resultados (assíncrono)")
                    except ValueError:
                        add_history("Coordenadas devem ser inteiros. Use: shot X Y", color=ANSI_YELLOW)
                else:
                    add_history("Formato inválido. Use: shot X Y", color=ANSI_YELLOW)

            elif cmd == "scout":
                if len(args) == 3:
                    try:
                        x = int(args[0]); y = int(args[1]); ip = args[2]
                        # informa que a resposta será assíncrona (chega via TCP quando o alvo processar)
                        send_tcp_message(ip, f"scout:{x},{y}")
                        add_history(f"Scout enviado para {ip} em ({x},{y}). Resposta virá por TCP (info:dx,dy ou hit).", color=ANSI_CYAN)
                    except ValueError:
                        add_history("Coordenadas devem ser inteiros. Use: scout X Y IP", color=ANSI_YELLOW)
                else:
                    add_history("Formato inválido. Use: scout X Y IP", color=ANSI_YELLOW)

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
                            add_history(f"Nova posição: {my_position}")
                            send_udp_to_all("moved")
                            move_penalty = True
                        else:
                            add_history("Movimento inválido ou fora dos limites.", color=ANSI_YELLOW)
                else:
                    add_history("Formato inválido. Use: move {+|-}{x|y}", color=ANSI_YELLOW)

            elif cmd == "help":
                print_help()

            elif cmd == "sair":
                game_running = False
                send_udp_to_all("saindo")
                add_history("Saindo do jogo...", color=ANSI_RED)
                break

            else:
                add_history("Comando inválido.", color=ANSI_YELLOW)

    except KeyboardInterrupt:
        add_history("Saindo por (Ctrl+C)...", color=ANSI_RED)
        game_running = False
        send_udp_to_all("saindo")
    except Exception as e:
        add_history(f"Erro no loop principal: {e}", color=ANSI_RED)
        print_exc_context()
        game_running = False
        send_udp_to_all("saindo")

    # finalização: aguarda término das threads (pequena espera)
    time.sleep(1)

    score, p_hit, t_hit, hit_list = calculate_score()
    add_history("\n" + "*"*30)
    add_history("SCORE FINAL")
    add_history(f"Vezes que foi atingido: {t_hit}", color=ANSI_RED)
    add_history(f"Jogadores únicos atingidos: {p_hit} ({hit_list if hit_list else 'nenhum'})", color=ANSI_GREEN)
    add_history(f"Score Total (Atingiu - Foi Atingido): {score}", color=ANSI_BOLD)
    add_history("*"*30)

if __name__ == "__main__":
    main()
