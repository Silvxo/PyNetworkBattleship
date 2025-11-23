# =============================================================================
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