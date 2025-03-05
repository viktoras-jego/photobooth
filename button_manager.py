import logging
from gpiozero import Button

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ButtonManager:
    def __init__(self, button1_callback, button2_callback=None, button1_pin=12, button2_pin=18):
        self.button1 = Button(button1_pin)
        self.button2 = Button(button2_pin) if button2_callback else None
        self.button1.when_pressed = button1_callback
        logger.info(f"Button 1 initialized on GPIO pin {button1_pin}.")
        if self.button2:
            self.button2.when_pressed = button2_callback
            logger.info(f"Button 2 initialized on GPIO pin {button2_pin}.")

    def wait(self):
        from signal import pause
        pause()