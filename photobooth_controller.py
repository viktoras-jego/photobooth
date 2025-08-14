import threading
import time
import os
import signal
from enum import Enum
import logging
from prometheus_client import start_http_server, Counter, Gauge, Histogram, write_to_textfile, REGISTRY
from prometheus_client.multiprocess import MultiProcessCollector
import json
import sys

from button_manager import ButtonManager
from led_manager import LEDManager
from payment_service import PaymentService
from sound_service import SoundService
from photo_service import PhotoService
from printer_service import PrinterService
from config_loader import load_config

# At the top of the file, after imports
logger = logging.getLogger('PhotoboothController')

# Configure root logger with file handler
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(asctime)s - %(message)s - %(name)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    filename="/home/viktoras/photobooth.log"
)

# Define Prometheus metrics
TRANSACTION_STATE = Counter('transaction_state_total', 'Transaction states with IDs', ['transaction_id', 'state'])

class State(Enum):
    IDLE = 1
    PAYMENT_INITIATED = 2
    PAYMENT_CHECKING = 3
    PAYMENT_SUCCESS = 4
    PAYMENT_FAILED = 5
    PHOTO_PULSING = 6
    PHOTO_TAKING_FAILED = 7
    PHOTO_COUNTDOWN = 8
    PHOTO_TAKING = 9
    PHOTO_DOWNLOADING = 10
    PHOTO_COMPLETE = 11
    PHOTO_PRINTING = 12
    PHOTO_PRINTED = 13

class PhotoboothController:
    def __init__(self, config_file='config.json'):
        self.config = load_config(config_file)
        self.led_manager = LEDManager()
        self.sound_service = SoundService()
        self.photo_service = PhotoService(photos_dir=self.config.get('photos_dir', 'photos'), max_photos=4)
        self.printer_service = PrinterService()
        self.button_manager = ButtonManager(
            button1_callback=self._on_button1_pressed,
            button2_callback=self._on_button2_pressed
        )
        self.payment_service = PaymentService(self.config)
        self.state = State.IDLE
        self.current_transaction_id = None
        self.transaction_code = None
        self.photo_lock = threading.Lock()

        # Track the last state change time
        self.last_state_change = time.time()
        # Inactivity timeout in seconds (5 minutes)
        self.inactivity_timeout = 300
        # Start the inactivity watchdog thread
        self.watchdog_thread = threading.Thread(target=self._inactivity_watchdog, daemon=True)
        self.watchdog_thread.start()

        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def cleanup_photos_directory(self):
        photos_dir = self.photo_service.photos_dir
        try:
            if os.path.exists(photos_dir):
                files = os.listdir(photos_dir)
                if files:
                    for file in files:
                        file_path = os.path.join(photos_dir, file)
                        if os.path.isfile(file_path):
                            os.remove(file_path)
        except Exception as e:
            logger.error(f"Error cleaning up photos directory: {e}")

    def _update_state(self, new_state):
        if self.state != new_state:
            self.state = new_state
            self.last_state_change = time.time()

    def _inactivity_watchdog(self):
        while True:
            try:
                if self.state != State.IDLE:
                    current_time = time.time()
                    if current_time - self.last_state_change > self.inactivity_timeout:
                        logger.error(f"Photobooth inactive for {self.inactivity_timeout} seconds. Last state {self.state}. Resetting to idle.")
                        logger.error("Critical error: inactivity_after_5min_timeout")
                        self.reset_to_idle()
                time.sleep(10)
            except Exception as e:
                logger.error(f"Exception in inactivity watchdog: {str(e)}")

    def _on_button1_pressed(self):
        if self.state == State.IDLE:
            if self.config['demo'] == True:  # Python uses True, not true
                self.led_manager.stop_pulsing_button1()
                self.payment_successful()
            else:
                self.initiate_payment()

    def _on_button2_pressed(self):
        if self.state == State.PHOTO_PULSING:
            self.initiate_photo_capture()
            self.sound_service.play_timer_audio()

    def initiate_payment(self):
        logger.info("Initiating payment...")
        self._update_state(State.PAYMENT_INITIATED)
        self.led_manager.stop_pulsing_button1()
        self.led_manager.set_button1_color(0.7, 0, 1)
        try:
            transaction_id = self.payment_service.create_checkout()
            if transaction_id:
                self.current_transaction_id = transaction_id
                logger.info(f"Payment initiated with transaction ID: {transaction_id}")
                threading.Timer(4.0, self.check_payment_status).start()
            else:
                logger.error("Payment terminal not working, could not initiate the payment")
                self.payment_failed()
        except Exception as e:
            logger.error("Payment terminal not working, could not initiate the payment")
            logger.error(f"Payment initiation error: {str(e)}")
            self.payment_failed()

    def check_payment_status(self):
        if not self.current_transaction_id:
            self.payment_failed()
            return
        self._update_state(State.PAYMENT_CHECKING)
        try:
            result = self.payment_service.poll_transaction_status(self.current_transaction_id)
            status = result['status']
            self.transaction_code = result.get('transaction_code')

            if status == "SUCCESSFUL":
                self.payment_successful()
            else:
                self.payment_failed()
        except Exception as e:
            logger.error(f"Error checking payment: {str(e)}")
            self.payment_failed()

    def payment_successful(self):
        if self.current_transaction_id:
            TRANSACTION_STATE.labels(
                transaction_id=self.current_transaction_id,
                state='payment_successful_but_not_printed_yet'
            ).inc()

        self._update_state(State.PAYMENT_SUCCESS)
        logger.info(f"Payment log: Transaction {self.transaction_code} - Payment successful, but not printed yet")
        self.led_manager.set_button1_color(0, 1, 0)
        self._update_state(State.PHOTO_PULSING)
        self.led_manager.set_pulse_color_button2(red=0.1, green=1.0, blue=1)
        self.led_manager.start_pulsing_button2()

    def payment_failed(self):
        logger.error("Critical error: payment_failed")
        self._update_state(State.PAYMENT_FAILED)
        logger.error("Payment failed!")
        self.led_manager.flash_button_red(5)
        self.reset_to_idle()

    def initiate_photo_capture(self):
        with self.photo_lock:
            if self.state not in [State.PHOTO_PULSING]:
                logger.warning("Photo capture not available in the current state.")
                return
            self.photo_service.kill_gphoto2_process()
            self._update_state(State.PHOTO_COUNTDOWN)
            self.led_manager.stop_pulsing_button2()
            self.led_manager.set_button2_color(1, 0, 1)
            threading.Thread(target=self._countdown_and_capture, daemon=True).start()

    def _countdown_and_capture(self):
        logger.info(f"Taking photo: {self.photo_service.current_photo_count + 1}")

        for remaining in range(4, 0, -1):
            time.sleep(0.97)

        self._update_state(State.PHOTO_TAKING)
        photo_path = self.photo_service.take_photo()
        if photo_path:
            logger.info(f"Photo {self.photo_service.current_photo_count} taken and saved.")

            self._update_state(State.PHOTO_DOWNLOADING)

            if self.photo_service.current_photo_count < self.photo_service.max_photos:
                self.led_manager.set_button2_color(1, 1, 0)

                # Wait for 2 seconds
                time.sleep(2)

                self.photo_service.kill_gphoto2_process()
                self.sound_service.play_timer_audio()
                self.led_manager.set_button2_color(1, 0, 1)  # Increase red to compensate for dimming factor
                threading.Thread(target=self._countdown_and_capture, daemon=True).start()
            else:
                # Reset state when all photos are taken
                self._update_state(State.PHOTO_COMPLETE)
                self.led_manager.set_button2_color(0, 1, 0)
                logger.info("All photos taken successfully!")

                collage_path = self.photo_service.create_final_photo()
                if collage_path:
                    logger.info(f"Final collage created")
                    if self.printer_service.print_collage(collage_path):
                        if self.current_transaction_id:
                            TRANSACTION_STATE.labels(
                                transaction_id=self.current_transaction_id,
                                state='print_successful'
                            ).inc()
                        logger.info(f"Payment log: Transaction {self.transaction_code} - Print also successful")
                        self._update_state(State.PHOTO_PRINTED)
                        self.led_manager.flash_button_green(5)
                        self.reset_to_idle()
                    else:
                        logger.error("Critical error: print_failed")
                        logger.error("Failed to print collage")
                        self.led_manager.flash_button_red(10)
                        self.reset_to_idle()
                else:
                    logger.error("Critical error: collage_creation_failed")
                    logger.error("Failed to create final collage")
                    self.led_manager.flash_button_red(10)
                    self.reset_to_idle()
        else:
            logger.error("Critical error: photo_capture_failed")
            logger.error("Failed to take/download photo.")
            self._update_state(State.PHOTO_TAKING_FAILED)
            self.led_manager.flash_button_red(10)
            self.reset_to_idle()

    def reset_to_idle(self):
        self.cleanup_photos_directory()
        self.current_transaction_id = None
        self.transaction_code = None
        self._update_state(State.IDLE)
        self.photo_service.reset_photo_count()
        self.led_manager.start_pulsing_button1()
        self.led_manager.stop_pulsing_button2()
        self.led_manager.set_button2_color(0, 0, 0)
        logger.info("System reset to idle state.")

    def run(self):
        try:
            logger.info("Photobooth controller starting...")
            # Start Prometheus metrics server first
            start_http_server(8000)
            # Then initialize the system
            self.reset_to_idle()

            while True:
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"Fatal error in main loop: {str(e)}")
            self._handle_shutdown(None, None)
            raise

    def _handle_shutdown(self, signum, frame):
            logger.info("Shutting down photobooth controller...")
            self.led_manager.stop_pulsing_button1()
            self.led_manager.stop_pulsing_button2()
            self.led_manager.set_button1_color(0, 0, 0)
            self.led_manager.set_button2_color(0, 0, 0)
            sys.exit(0)

if __name__ == "__main__":
    controller = PhotoboothController()
    controller.run()
