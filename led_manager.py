"""
LED Manager
Controls the RGB LEDs in the buttons, including patterns and animations
"""

import threading
import time
from gpiozero import PWMLED
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LEDManager:
    def __init__(self):
        # Initialize LED pins
        self.red_led1 = PWMLED(16)
        self.green_led1 = PWMLED(20)
        self.blue_led1 = PWMLED(21)

        self.red_led2 = PWMLED(23)
        self.green_led2 = PWMLED(24)
        self.blue_led2 = PWMLED(25)

        # Flags to control LED pulsing for both buttons
        self.pulsing_active_button1 = False
        self.pulsing_active_button2 = False
        self.pulse_thread_button1 = None
        self.pulse_thread_button2 = None

        # Define pulse colors
        self.pulse_color_button1 = {'red': 1.0, 'green': 1.0, 'blue': 1.0}  # Default pulsing color for Button 1 (e.g., white)
        self.pulse_color_button2 = {'red': 1.0, 'green': 1.0, 'blue': 0.0}  # Default pulsing color for Button 2 (e.g., yellow)

    def set_pulse_color_button1(self, red, green, blue):
        """
        Set the pulsing color for Button 1.

        Args:
            red (float): Red component (0.0 to 1.0)
            green (float): Green component (0.0 to 1.0)
            blue (float): Blue component (0.0 to 1.0)
        """
        self.pulse_color_button1 = {'red': red, 'green': green, 'blue': blue}
        logger.debug(f"Button 1 pulsing color set to: {self.pulse_color_button1}")

    def set_pulse_color_button2(self, red, green, blue):
        """
        Set the pulsing color for Button 2.

        Args:
            red (float): Red component (0.0 to 1.0)
            green (float): Green component (0.0 to 1.0)
            blue (float): Blue component (0.0 to 1.0)
        """
        self.pulse_color_button2 = {'red': red, 'green': green, 'blue': blue}
        logger.debug(f"Button 2 pulsing color set to: {self.pulse_color_button2}")

    def set_button1_color(self, red, green, blue):
        """Set Button 1 to a specific color."""
        self.red_led1.value = red * 0.8  # 20% dimmer for red
        self.green_led1.value = green
        self.blue_led1.value = blue
        logger.debug(f"Button 1 set to color: R={self.red_led1.value}, G={self.green_led1.value}, B={self.blue_led1.value}")

    def set_button2_color(self, red, green, blue):
        """Set Button 2 to a specific color."""
        self.red_led2.value = red
        self.green_led2.value = green
        self.blue_led2.value = blue
        logger.debug(f"Button 2 set to color: R={self.red_led2.value}, G={self.green_led2.value}, B={self.blue_led2.value}")

    def flash_button_red(self, button_number, times):
        if button_number == 1:
            set_color = self.set_button1_color
        elif button_number == 2:
            set_color = self.set_button2_color
        else:
            logger.error(f"Invalid button number: {button_number}. Must be 1 or 2.")
            return

        for _ in range(times):
            # Red on
            set_color(1, 0, 0)
            time.sleep(0.2)
            # Off
            set_color(0, 0, 0)
            time.sleep(0.2)
        logger.debug(f"Button {button_number} flashed red {times} times.")

    def start_pulsing_button1(self):
        """Start pulsing LEDs for Button 1 only."""
        if not self.pulsing_active_button1:
            self.pulsing_active_button1 = True
            self.pulse_thread_button1 = threading.Thread(target=self._pulse_loop, args=(1,), daemon=True)
            self.pulse_thread_button1.start()
            logger.info("Started pulsing Button 1.")

    def start_pulsing_button2(self):
        """Start pulsing LEDs for Button 2 only."""
        if not self.pulsing_active_button2:
            self.pulsing_active_button2 = True
            self.pulse_thread_button2 = threading.Thread(target=self._pulse_loop, args=(2,), daemon=True)
            self.pulse_thread_button2.start()
            logger.info("Started pulsing Button 2.")

    def stop_pulsing_button1(self):
        """Stop pulsing LEDs for Button 1."""
        if self.pulsing_active_button1:
            self.pulsing_active_button1 = False
            if self.pulse_thread_button1:
                self.pulse_thread_button1.join(1.0)  # Wait up to 1 second for the thread to finish
            self.set_button1_color(0, 0, 0)  # Turn off Button 1 LEDs
            logger.info("Stopped pulsing Button 1 and turned off LEDs.")

    def stop_pulsing_button2(self):
        """Stop pulsing LEDs for Button 2."""
        if self.pulsing_active_button2:
            self.pulsing_active_button2 = False
            if self.pulse_thread_button2:
                self.pulse_thread_button2.join(1.0)  # Wait up to 1 second for the thread to finish
            self.set_button2_color(0, 0, 0)  # Turn off Button 2 LEDs
            logger.info("Stopped pulsing Button 2 and turned off LEDs.")

    def _determine_sleep_time(self, brightness):
        """
        Determine sleep time based on current brightness level.

        Args:
            brightness (float): Current brightness level (0.0 to 1.0)

        Returns:
            float: Sleep duration in seconds
        """
        if brightness == 0:
            return 0.25  # Highest delay at 0% brightness
        elif brightness <= 0.3:
            return 0.03  # Slightly longer delay at 30% and below
        elif brightness >= 0.8:
            return 0.045   # Slightly longer delay at 80% and above for smoother peak
        else:
            return 0.04  # Standard delay elsewhere

    def _pulse_loop(self, button_number):
        """
        Pulse LEDs for the specified button in a loop with smoother peak and variable delays.

        Args:
            button_number (int): The button number (1 or 2) to pulse.
        """
        if button_number == 1:
            pulse_color = self.pulse_color_button1
            led_red = self.red_led1
            led_green = self.green_led1
            led_blue = self.blue_led1
            dimming_factor = 0.1  # 20% dimmer for red
        elif button_number == 2:
            pulse_color = self.pulse_color_button2
            led_red = self.red_led2
            led_green = self.green_led2
            led_blue = self.blue_led2
            dimming_factor = 0.1  # Assuming full brightness for Button 2
        else:
            logger.error(f"Invalid button number: {button_number}. Must be 1 or 2.")
            return  # Invalid button number

        logger.debug(f"Starting pulse loop for Button {button_number} with color {pulse_color}.")

        while ((button_number == 1 and self.pulsing_active_button1) or
               (button_number == 2 and self.pulsing_active_button2)):
            # Pulse up
            for i in range(36):
                if ((button_number == 1 and not self.pulsing_active_button1) or
                    (button_number == 2 and not self.pulsing_active_button2)):
                    logger.debug(f"Pulsing stopped for Button {button_number} during pulsing up.")
                    return
                brightness = i / 35  # Normalize between 0 and 1

                # Apply brightness scaling
                led_red.value = pulse_color['red'] * brightness * dimming_factor
                led_green.value = pulse_color['green'] * brightness
                led_blue.value = pulse_color['blue'] * brightness

                # Determine sleep time based on brightness
                sleep_time = self._determine_sleep_time(brightness)
                time.sleep(sleep_time)

            # Pulse down
            for i in range(35, -1, -1):
                if ((button_number == 1 and not self.pulsing_active_button1) or
                    (button_number == 2 and not self.pulsing_active_button2)):
                    logger.debug(f"Pulsing stopped for Button {button_number} during pulsing down.")
                    return
                brightness = i / 35  # Normalize between 0 and 1

                # Apply brightness scaling
                led_red.value = pulse_color['red'] * brightness * dimming_factor
                led_green.value = pulse_color['green'] * brightness
                led_blue.value = pulse_color['blue'] * brightness

                # Determine sleep time based on brightness
                sleep_time = self._determine_sleep_time(brightness)
                time.sleep(sleep_time)

        logger.debug(f"Pulse loop for Button {button_number} has ended.")

    def set_button2_fixed_color(self, red, green, blue):
        """Set Button 2 to a fixed color (non-pulsing)."""
        self.set_button2_color(red, green, blue)