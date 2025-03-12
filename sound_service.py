import pygame
import os
import logging
import signal
import sys

logger = logging.getLogger('SoundService')
logger.setLevel(logging.INFO)

class SoundService:
    def __init__(self, volume=1):
        try:
            # Handle SIGTERM so we can gracefully shut down and free the audio device
            signal.signal(signal.SIGTERM, self._handle_termination)
            signal.signal(signal.SIGINT, self._handle_termination)

            pygame.mixer.init()
            pygame.mixer.music.set_volume(volume)
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.audio_file = os.path.join(script_dir, 'timer_audio.wav')
            pygame.mixer.music.load(self.audio_file)
        except Exception as e:
            logger.error(f"Failed to initialize sound service: {e}")

    def play_timer_audio(self):
        try:
            pygame.mixer.music.play()
        except Exception as e:
            logger.error(f"Failed to play timer audio: {e}")

    def set_volume(self, volume):
        try:
            pygame.mixer.music.set_volume(volume)
            logger.info(f"Volume set to {volume}")
        except Exception as e:
            logger.error(f"Failed to set volume: {e}")

    def _handle_termination(self, signum, frame):
        """
        Called when the process receives SIGTERM or SIGINT.
        Stops the mixer and exits cleanly so systemd won't hang.
        """
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
            logger.info("Sound service shut down cleanly.")
        except Exception as e:
            logger.error(f"Failed to shut down sound service: {e}")
        sys.exit(0)