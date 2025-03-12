import threading
import time
import os
import signal
from enum import Enum
import logging
from prometheus_client import start_http_server, Counter, Gauge, Histogram
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
PAYMENT_INITIATED = Counter('payment_initiated_total', 'Total number of payment initiations')
PAYMENT_SUCCESS = Counter('payment_success_total', 'Total number of successful payments')
PAYMENT_FAILED = Counter('payment_failed_total', 'Total number of failed payments')
PHOTOS_TAKEN = Counter('photos_taken_total', 'Total number of photos taken')
COLLAGES_CREATED = Counter('collages_created_total', 'Total number of collages created')
PRINTS_INITIATED = Counter('prints_initiated_total', 'Total number of print jobs initiated')
PRINTS_SUCCESS = Counter('prints_success_total', 'Total number of successful prints')
PRINTS_FAILED = Counter('prints_failed_total', 'Total number of failed prints')
SYSTEM_RESETS = Counter('system_resets_total', 'Total number of system resets to idle')
ERRORS_TOTAL = Counter('errors_total', 'Total number of errors by type', ['type'])
STATE_CURRENT = Gauge('current_state', 'Current state of the photobooth controller', ['state'])
PRINT_DURATION = Histogram('print_duration_seconds', 'Duration of print processing')
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
        self.photo_lock = threading.Lock()
        self.update_state_metric()

        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def update_state_metric(self):
        # Reset all state gauges to 0
        for state in State:
            STATE_CURRENT.labels(state=state.name).set(0)
        # Set current state to 1
        STATE_CURRENT.labels(state=self.state.name).set(1)

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

    def _on_button1_pressed(self):
        if self.state == State.IDLE:
            self.initiate_payment()

            #self.led_manager.stop_pulsing_button1()
            #self.payment_successful()

    def _on_button2_pressed(self):
        if self.state == State.PHOTO_PULSING:
            self.initiate_photo_capture()
            self.sound_service.play_timer_audio()

    def initiate_payment(self):
        PAYMENT_INITIATED.inc()
        logger.info("Initiating payment...")
        self.state = State.PAYMENT_INITIATED
        self.update_state_metric()
        self.led_manager.stop_pulsing_button1()
        self.led_manager.set_button1_color(0.7, 0, 1)
        try:
            transaction_id = self.payment_service.create_checkout()
            if transaction_id:
                self.current_transaction_id = transaction_id
                logger.info(f"Payment initiated with transaction ID: {transaction_id}")
                threading.Timer(4.0, self.check_payment_status).start()
            else:
                self.payment_failed()
        except Exception as e:
            logger.error(f"Payment initiation error: {str(e)}")
            self.payment_failed()

    def check_payment_status(self):
        if not self.current_transaction_id:
            self.payment_failed()
            return
        self.state = State.PAYMENT_CHECKING
        self.update_state_metric()
        try:
            status = self.payment_service.poll_transaction_status(self.current_transaction_id)
            if status == "SUCCESSFUL":
                self.payment_successful()
            else:
                self.payment_failed()
        except Exception as e:
            logger.error(f"Error checking payment: {str(e)}")
            self.payment_failed()

    def payment_successful(self):
        PAYMENT_SUCCESS.inc()
        if self.current_transaction_id:
            TRANSACTION_STATE.labels(
                transaction_id=self.current_transaction_id,
                state='payment_successful_but_not_printed_yet'
            ).inc()

        self.state = State.PAYMENT_SUCCESS
        self.update_state_metric()
        logger.info("Payment successful!")
        self.led_manager.set_button1_color(0, 1, 0)
        self.state = State.PHOTO_PULSING
        self.update_state_metric()
        self.led_manager.set_pulse_color_button2(red=0.1, green=1.0, blue=1)
        self.led_manager.start_pulsing_button2()

    def payment_failed(self):
        PAYMENT_FAILED.inc()
        ERRORS_TOTAL.labels(type='payment_failed').inc()
        self.state = State.PAYMENT_FAILED
        self.update_state_metric()
        logger.warning("Payment failed!")
        self.led_manager.flash_button_red(5)
        self.reset_to_idle()

    def initiate_photo_capture(self):
        with self.photo_lock:
            if self.state not in [State.PHOTO_PULSING]:
                logger.warning("Photo capture not available in the current state.")
                return
            self.photo_service.kill_gphoto2_process()
            self.state = State.PHOTO_COUNTDOWN
            self.update_state_metric()
            self.led_manager.stop_pulsing_button2()
            self.led_manager.set_button2_color(1, 0, 1)
            threading.Thread(target=self._countdown_and_capture, daemon=True).start()

    def _countdown_and_capture(self):
        logger.info(f"Taking photo: {self.photo_service.current_photo_count + 1}")

        for remaining in range(4, 0, -1):
            time.sleep(0.97)

        self.state = State.PHOTO_TAKING
        self.update_state_metric()
        self.led_manager.set_button2_color(1, 0, 1)
        photo_path = self.photo_service.take_photo()
        if photo_path:
            PHOTOS_TAKEN.inc()
            logger.info(f"Photo {self.photo_service.current_photo_count} taken and saved.")

            self.state = State.PHOTO_DOWNLOADING
            self.update_state_metric()

            if self.photo_service.current_photo_count < self.photo_service.max_photos:
                self.state = State.PHOTO_PULSING
                self.update_state_metric()
                self.led_manager.set_pulse_color_button2(red=0.1, green=1.0, blue=1)
                self.led_manager.start_pulsing_button2()
            else:
                self.state = State.PHOTO_COMPLETE
                self.update_state_metric()
                self.led_manager.set_button2_color(0, 1, 0)
                logger.info("All photos taken successfully!")

                with PRINT_DURATION.time():
                    collage_path = self.photo_service.create_final_photo()
                    if collage_path:
                        COLLAGES_CREATED.inc()
                        logger.info(f"Final collage created")
                        PRINTS_INITIATED.inc()
                        if self.printer_service.print_collage(collage_path):
                            PRINTS_SUCCESS.inc()
                            if self.current_transaction_id:
                                TRANSACTION_STATE.labels(
                                    transaction_id=self.current_transaction_id,
                                    state='print_successful'
                                ).inc()
                            logger.info("Collage sent to printer successfully")
                            self.state = State.PHOTO_PRINTED
                            self.update_state_metric()
                        else:
                            PRINTS_FAILED.inc()
                            ERRORS_TOTAL.labels(type='print_failed').inc()
                            logger.error("Failed to print collage")
                            self.led_manager.flash_button_red(10)
                    else:
                        ERRORS_TOTAL.labels(type='collage_creation_failed').inc()
                        logger.error("Failed to create final collage")
                        self.led_manager.flash_button_red(10)
                threading.Timer(15.0, self.reset_to_idle).start()
        else:
            ERRORS_TOTAL.labels(type='photo_capture_failed').inc()
            logger.error("Failed to take/download photo.")
            self.state = State.PHOTO_TAKING_FAILED
            self.update_state_metric()
            self.led_manager.flash_button_red(10)
            self.reset_to_idle()

    def reset_to_idle(self):
        SYSTEM_RESETS.inc()
        self.cleanup_photos_directory()
        self.current_transaction_id = None
        self.state = State.IDLE
        self.update_state_metric()
        self.photo_service.reset_photo_count()
        self.led_manager.start_pulsing_button1()
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