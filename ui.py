#!/usr/bin/env python3
"""
Pygame UI components for PyNetworkBattleship.
Contains MenuScreen, ScoreScreen, and PygameInterface classes.
"""

import threading
import time

# Optional pygame
try:
    import pygame
    PYGAME_AVAILABLE = True
except Exception:
    PYGAME_AVAILABLE = False

# ============================================================================
# UI HELPER FUNCTION (imported from main)
# ============================================================================

def print_exc_context():
    """Print exception context."""
    import traceback
    traceback.print_exc()


# ============================================================================
# MENU SCREEN
# ============================================================================

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
            self.running = False
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


# ============================================================================
# SCORE SCREEN
# ============================================================================

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
            self.running = False
            self.choice = "menu"  # Auto-return to menu if pygame unavailable
            return
        self.running = True
        super().start()

    def stop(self):
        self.running = False

    def run(self):
        try:
            # Try to initialize pygame with retry
            for attempt in range(3):
                try:
                    pygame.init()
                    break
                except Exception as e:
                    if attempt < 2:
                        import time
                        time.sleep(0.2)
                    else:
                        raise
            
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


# ============================================================================
# GAME INTERFACE
# ============================================================================

class PygameInterface(threading.Thread):
    """Threaded Pygame interface with grid, participants list, two-step scout, action history.

    - Left-click grid: send `shot:x,y` (if cooldown expired).
    - Right-click grid: move to cell and broadcast `moved` (20s cooldown, must be 1 block orthogonal).
    - Two-step scout: left-click IP to select, then left-click grid cell to send `scout:x,y IP`.
    - Action history scrolls below participants list.
    """

    def __init__(self, grid_size, my_position, my_ip, participants, players_hit, times_hit, 
                 game_running_ref, lock, send_udp_to_all, send_tcp_message):
        """
        Args:
            grid_size: Game grid size (typically 10)
            my_position: Reference to player's current position (mutable dict or access function)
            my_ip: Player's IP address
            participants: Set of participant IPs (shared)
            players_hit: Set of players hit (shared)
            times_hit: Number of times hit (shared)
            game_running_ref: Reference to game_running flag (can be globals dict)
            lock: Threading lock for shared state
            send_udp_to_all: Function to send UDP broadcast
            send_tcp_message: Function to send TCP message
        """
        super().__init__(daemon=True)
        self.running = False
        self.cell_size = 40
        self.margin = 20
        self.grid_size = grid_size
        self.grid_px = grid_size * self.cell_size + self.margin * 2
        self.sidebar_width = 220
        self.button_height = 50
        self.width = self.grid_px + self.sidebar_width
        self.height = self.grid_px + self.button_height
        self.clock = None

        # References to game state (shared with main.py)
        self.my_position = my_position
        self.my_ip = my_ip
        self.participants = participants
        self.players_hit = players_hit
        self.times_hit = times_hit
        self.game_running_ref = game_running_ref
        self.lock = lock
        self.send_udp_to_all = send_udp_to_all
        self.send_tcp_message = send_tcp_message

        # GUI state
        self.last_action_time = 0.0
        self.cooldown = 0.0
        self.selected_hover = None
        self.scout_selected_ip = None
        
        # Action history
        self.action_history = []
        self.history_scroll_offset = 0
        
        # Leave button
        self.leave_button_rect = None

    def _add_action(self, action_str):
        """Add an action to the history log."""
        ts = time.time()
        self.action_history.append((ts, action_str))
        if len(self.action_history) > 50:
            self.action_history.pop(0)

    def start(self):
        if not PYGAME_AVAILABLE:
            print("Pygame not available; GUI disabled.")
            self.running = False
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

    def _get_game_running(self):
        """Get current game_running state."""
        if isinstance(self.game_running_ref, dict):
            return self.game_running_ref.get('game_running', False)
        return self.game_running_ref

    def _set_game_running(self, value):
        """Set game_running state."""
        if isinstance(self.game_running_ref, dict):
            self.game_running_ref['game_running'] = value
        else:
            # Try to set in globals
            try:
                import main
                main.game_running = value
            except Exception:
                pass

    def run(self):
        try:
            pygame.init()
            screen = pygame.display.set_mode((self.width, self.height))
            pygame.display.set_caption('PyNetworkBattleship')
            self.clock = pygame.time.Clock()
            font = pygame.font.SysFont(None, 18)
            title_font = pygame.font.SysFont(None, 20)

            while self.running and self._get_game_running():
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        print("Pygame: quit requested")
                        self._set_game_running(False)
                        self.running = False

                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        mx, my = pygame.mouse.get_pos()

                        # Check Leave button click
                        if self.leave_button_rect is not None and self.leave_button_rect.collidepoint(mx, my):
                            self._set_game_running(False)
                            self.send_udp_to_all("saindo")
                            print("Leaving game...")
                            self.running = False
                            continue

                        # Clicked in participants sidebar
                        if mx >= self.grid_px:
                            with self.lock:
                                part_list = list(self.participants)
                            top = 40
                            line_h = 20
                            idx = (my - top) // line_h
                            if 0 <= idx < len(part_list):
                                target_ip = part_list[idx]
                                if self.scout_selected_ip == target_ip:
                                    self.scout_selected_ip = None
                                    print(f"Scout deselected.")
                                else:
                                    self.scout_selected_ip = target_ip
                                    print(f"Scout selected: {target_ip}. Agora clique em uma célula do grid.")
                            continue

                        # Clicked inside grid
                        gx = (mx - self.margin) // self.cell_size
                        gy = (my - self.margin) // self.cell_size
                        if gx < 0 or gy < 0 or gx >= self.grid_size or gy >= self.grid_size:
                            continue

                        # Left click -> shot or scout
                        if event.button == 1:
                            if self.scout_selected_ip is not None:
                                if not self._can_do_action():
                                    print("Aguarde cooldown antes de outra ação.")
                                else:
                                    try:
                                        self.send_tcp_message(self.scout_selected_ip, f"scout:{gx},{gy}")
                                        self._add_action(f"scout:{gx},{gy} -> {self.scout_selected_ip}")
                                        self._set_action(10.0)
                                        self.scout_selected_ip = None
                                    except Exception as e:
                                        print(f"Pygame: erro ao enviar scout: {e}")
                            else:
                                if not self._can_do_action():
                                    print("Aguarde cooldown antes de outra ação.")
                                else:
                                    try:
                                        self.send_udp_to_all(f"shot:{gx},{gy}")
                                        self._add_action(f"shot:{gx},{gy}")
                                        self._set_action(10.0)
                                    except Exception as e:
                                        print(f"Pygame: erro ao enviar shot: {e}")

                        # Right click -> move
                        elif event.button == 3:
                            if not self._can_do_action():
                                print("Aguarde cooldown antes de outra ação.")
                            else:
                                try:
                                    with self.lock:
                                        cur_x, cur_y = self.my_position
                                    dx = abs(gx - cur_x)
                                    dy = abs(gy - cur_y)
                                    if (dx + dy) == 1:
                                        try:
                                            with self.lock:
                                                self.my_position = (gx, gy)
                                            self.send_udp_to_all("moved")
                                            self._add_action(f"move:{gx},{gy}")
                                            self._set_action(20.0)
                                        except Exception as e:
                                            print(f"Pygame: erro ao mover: {e}")
                                    else:
                                        print("Movimento inválido: pode mover somente 1 bloco em x ou y.")
                                except Exception as e:
                                    print(f"Pygame: erro ao validar movimento: {e}")

                # Draw background and grid
                screen.fill((18, 24, 30))
                for i in range(self.grid_size + 1):
                    x = self.margin + i * self.cell_size
                    pygame.draw.line(screen, (120, 120, 120), (x, self.margin), 
                                    (x, self.margin + self.grid_size * self.cell_size))
                    y = self.margin + i * self.cell_size
                    pygame.draw.line(screen, (120, 120, 120), (self.margin, y), 
                                    (self.margin + self.grid_size * self.cell_size, y))

                # Draw my position
                try:
                    with self.lock:
                        pos = self.my_position
                except Exception:
                    pos = None
                if pos is not None:
                    px = self.margin + pos[0] * self.cell_size + self.cell_size // 2
                    py = self.margin + pos[1] * self.cell_size + self.cell_size // 2
                    pygame.draw.circle(screen, (220, 50, 50), (px, py), int(self.cell_size * 0.35))

                # Hover highlight
                mx, my = pygame.mouse.get_pos()
                gx = (mx - self.margin) // self.cell_size
                gy = (my - self.margin) // self.cell_size
                hover_valid = (0 <= gx < self.grid_size and 0 <= gy < self.grid_size)
                if hover_valid:
                    rx = self.margin + gx * self.cell_size
                    ry = self.margin + gy * self.cell_size
                    pygame.draw.rect(screen, (255, 255, 255), (rx, ry, self.cell_size, self.cell_size), 2)
                    self.selected_hover = (gx, gy)
                else:
                    self.selected_hover = None

                # Sidebar: participants list
                sidebar_x = self.grid_px
                pygame.draw.rect(screen, (28, 34, 40), (sidebar_x, 0, self.sidebar_width, self.height))
                title = title_font.render('Participants', True, (230, 230, 230))
                screen.blit(title, (sidebar_x + 10, 10))
                with self.lock:
                    part_list = list(self.participants)
                top = 40
                line_h = 20
                for i, p in enumerate(part_list):
                    if p == self.scout_selected_ip:
                        color = (255, 200, 100)
                    else:
                        color = (200, 200, 200)
                    txt = font.render(p, True, color)
                    screen.blit(txt, (sidebar_x + 10, top + i * line_h))
                
                # Action history
                hist_top = top + len(part_list) * line_h + 20
                hist_title = font.render('History', True, (230, 230, 230))
                screen.blit(hist_title, (sidebar_x + 10, hist_top))
                hist_top += 20
                hist_height = self.height - hist_top - 10
                
                for i, (ts, action_str) in enumerate(self.action_history[self.history_scroll_offset:]):
                    if i * line_h >= hist_height:
                        break
                    display_str = action_str[:28] if len(action_str) > 28 else action_str
                    hist_txt = font.render(display_str, True, (150, 150, 200))
                    screen.blit(hist_txt, (sidebar_x + 10, hist_top + i * line_h))

                # Cooldown and status
                now = time.time()
                remaining = 0.0
                if (now - self.last_action_time) < self.cooldown:
                    remaining = self.cooldown - (now - self.last_action_time)
                status_lines = [f"IP: {self.my_ip}", f"Pos: {self.my_position}", 
                               f"Players: {len(self.participants)}", f"Hits: {self.times_hit}"]
                for i, line in enumerate(status_lines):
                    surf = font.render(line, True, (230, 230, 230))
                    screen.blit(surf, (10, 10 + i * 18))

                if remaining > 0:
                    rem_s = int(remaining + 0.999)
                    cd_surf = title_font.render(f'Cooldown: {rem_s}s', True, (255, 200, 60))
                    screen.blit(cd_surf, (sidebar_x + 10, self.height - 30))

                # Button area background
                pygame.draw.rect(screen, (18, 24, 30), (0, self.grid_px, self.grid_px, self.button_height))

                # Leave button
                button_y = self.grid_px + 10
                button_x = self.margin
                button_w = self.grid_px - self.margin * 2
                button_h = 30
                self.leave_button_rect = pygame.Rect(button_x, button_y, button_w, button_h)
                pygame.draw.rect(screen, (200, 50, 50), self.leave_button_rect)
                button_txt = font.render('Sair', True, (255, 255, 255))
                btn_rect = button_txt.get_rect(center=self.leave_button_rect.center)
                screen.blit(button_txt, btn_rect)

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
