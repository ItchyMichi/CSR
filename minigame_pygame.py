import pygame
import sys
import time

def run_minigame(minigame_name, difficulty, time_limit):
    """
    A simplified PyGame loop simulating the minigame described.
    * minigame_name: currently "Image Selection Game"
    * difficulty: "Easy", "Medium", or "Hard"
    * time_limit: number of seconds player has
    """

    # Initialize PyGame
    pygame.init()

    # Window setup
    width, height = 800, 600
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("Language Learning Mini-Game")

    clock = pygame.time.Clock()

    # Game state
    lives = 3
    total_rounds = 5  # number of levels
    current_round = 1
    start_time = time.time()

    # Dummy assets (replace with real images and load audio in a real scenario)
    # We'll just fill surfaces with colors for now.
    correct_image = pygame.Surface((200,200))
    correct_image.fill((0,255,0))  # green as correct
    distractor_image = pygame.Surface((200,200))
    distractor_image.fill((255,0,0)) # red as distractor

    # Positions
    correct_rect = correct_image.get_rect(center=(width*0.3, height*0.5))
    distractor_rect = distractor_image.get_rect(center=(width*0.7, height*0.5))

    # Dummy sentence and audio
    sentence_text = "猫がソファーで寝ている。"
    font = pygame.font.SysFont(None, 48)

    # Dummy audio: In a real scenario, you'd use pygame.mixer to play an audio file.
    # For now, no actual audio playing.

    # Helper function to draw lives
    def draw_lives(lives_count):
        # Draw hearts or just text
        lives_surf = font.render(f"Lives: {lives_count}", True, (255,255,255))
        screen.blit(lives_surf, (10,10))

    # Helper to draw timer
    def draw_timer(remaining):
        timer_surf = font.render(f"Time: {remaining}s", True, (255,255,255))
        screen.blit(timer_surf, (width-200,10))

    # Game loop
    running = True
    while running:
        current_time = time.time()
        elapsed = current_time - start_time
        remaining = time_limit - int(elapsed)

        if remaining <= 0:
            # Time's up, lose a life and move to next round
            lives -= 1
            current_round += 1
            if lives <= 0 or current_round > total_rounds:
                running = False
                break
            # Reset timer for next round
            start_time = time.time()
            continue

        # Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = pygame.mouse.get_pos()
                # Check if clicked correct_image
                if correct_rect.collidepoint(mx,my):
                    # Correct choice
                    current_round += 1
                    if current_round > total_rounds:
                        running = False
                        break
                    # Reset timer
                    start_time = time.time()
                elif distractor_rect.collidepoint(mx,my):
                    # Wrong choice
                    lives -= 1
                    current_round += 1
                    if lives <= 0 or current_round > total_rounds:
                        running = False
                        break
                    # Reset timer
                    start_time = time.time()

        # Visual feedback if time is low
        if remaining <= 10:
            # Change background color or shake screen
            # For simplicity, just change background color to yellowish
            bg_color = (255,255,0)
        else:
            bg_color = (0,0,0)

        screen.fill(bg_color)

        # Draw images
        screen.blit(correct_image, correct_rect)
        screen.blit(distractor_image, distractor_rect)

        # Draw UI elements
        draw_lives(lives)
        draw_timer(remaining)

        # In last 10 seconds, show sentence
        if remaining <= 10:
            sentence_surf = font.render(sentence_text, True, (255,255,255))
            sentence_rect = sentence_surf.get_rect(center=(width/2, height*0.3))
            screen.blit(sentence_surf, sentence_rect)

        # Round indicator
        round_surf = font.render(f"Round {current_round}/{total_rounds}", True, (255,255,255))
        round_rect = round_surf.get_rect(center=(width/2,50))
        screen.blit(round_surf, round_rect)

        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
