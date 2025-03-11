import threading
import time
from enum import Enum
import logging
from prometheus_client import start_http_server, Counter, Gauge, Histogram
import json

from button_manager import ButtonManager
from led_manager import LEDManager
from payment_service import PaymentService
from sound_service import SoundService
from photo_service import PhotoService
from printer_service import PrinterService
from config_loader import load_config

# Clear handlers
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/home/viktoras/photobooth.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Define Prometheus metrics
PAYMENT_INITIATED = Counter('payment_initiated_total', 'Total number of payment initiations')
PAYMENT_SUCCESS = Counter('payment_success_total', 'Total number of successful payments')
PAYMENT_FAILED = Counter('payment_failed_total', 'Total number of failed payments')
PHOTOS_TAKEN = Counter('photos_taken_total', 'Total number of photos taken')
STATE_CURRENT = Gauge('current_state', 'Current state of the photobooth controller', ['state'])
PAYMENT_DURATION = Histogram('payment_duration_seconds', 'Duration of payment processing')

class State(Enum):
    IDLE = 1
    PAYMENT_INITIATED = 2
    PAYMENT_CHECKING = 3
    PAYMENT_SUCCESS = 4
    PAYMENT_FAILED = 5
    PHOTO_PULSING = 6
    PHOTO_FAILED = 7
    PHOTO_COUNTDOWN = 8
    PHOTO_TAKING = 9
    PHOTO_DOWNLOADING = 10
    PHOTO_COMPLETE = 11

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

    def update_state_metric(self):
        # Reset all state gauges to 0
        for state in State:
            STATE_CURRENT.labels(state=state.name).set(0)
        # Set current state to 1
        STATE_CURRENT.labels(state=self.state.name).set(1)

    def _on_button1_pressed(self):
        if self.state == State.IDLE:
            self.initiate_payment()

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
            with PAYMENT_DURATION.time():
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
        self.state = State.PAYMENT_SUCCESS
        self.update_state_metric()
        logger.info("Payment successful!")
        self.led_manager.set_button1_color(0, 1, 0)
        self.state = State.PHOTO_PULSING
        self.update_state_metric()
        self.led_manager.set_pulse_color_button2(red=0.1, green=1.0, blue=1)
        self.led_manager.start_pulsing_button2()
        logger.info("Ready to take photos. Press Button 2 to start.")

    def payment_failed(self):
        PAYMENT_FAILED.inc()
        self.state = State.PAYMENT_FAILED
        self.update_state_metric()
        logger.error("Payment failed!")
        self.led_manager.flash_button_red(1, 5)
        self.reset_to_idle()

    def initiate_photo_capture(self):
        with self.photo_lock:
            if self.state not in [State.PHOTO_PULSING, State.PHOTO_COUNTDOWN]:
                logger.warning("Photo capture not available in the current state.")
                return
            self.state = State.PHOTO_COUNTDOWN
            self.update_state_metric()
            self.led_manager.stop_pulsing_button2()
            self.led_manager.set_button2_color(1, 0, 1)
            logger.info("Photo capture initiated. Countdown started.")
            threading.Thread(target=self._countdown_and_capture, daemon=True).start()

    def _countdown_and_capture(self):
        for remaining in range(4, 0, -1):
            logger.info(f"Photo will be taken in {remaining} seconds...")
            time.sleep(0.92)
        self.state = State.PHOTO_TAKING
        self.update_state_metric()
        self.led_manager.set_button2_color(1, 0, 1)
        logger.info("Taking photo...")
        photo_path = self.photo_service.take_photo()
        if photo_path:
            PHOTOS_TAKEN.inc()
            logger.info(f"Photo {self.photo_service.current_photo_count} taken and saved to {photo_path}.")
            self.state = State.PHOTO_DOWNLOADING
            self.update_state_metric()
            logger.info("Downloading photo...")
            if self.photo_service.current_photo_count < self.photo_service.max_photos:
                self.state = State.PHOTO_PULSING
                self.update_state_metric()
                self.led_manager.set_pulse_color_button2(red=0.1, green=1.0, blue=1)
                self.led_manager.start_pulsing_button2()
                logger.info(f"Ready to take photo {self.photo_service.current_photo_count + 1}. Press Button 2 to continue.")
            else:
                self.state = State.PHOTO_COMPLETE
                self.update_state_metric()
                self.led_manager.set_button2_color(0, 1, 0)
                logger.info("All photos taken successfully!")
                collage_path = self.photo_service.create_final_photo()
                if collage_path:
                    logger.info(f"Final collage created at: {collage_path}")
                    if self.printer_service.print_collage(collage_path):
                        logger.info("Collage sent to printer successfully")
                    else:
                        logger.error("Failed to print collage")
                else:
                    logger.error("Failed to create final collage")
                threading.Timer(10.0, self.reset_to_idle).start()
        else:
            logger.error("Failed to take/download photo.")
            self.state = State.PHOTO_FAILED
            self.led_manager.flash_button_red(2, 10)
            self.reset_to_idle()

    def reset_to_idle(self):
        self.current_transaction_id = None
        self.state = State.IDLE
        self.update_state_metric()
        self.photo_service.reset_photo_count()
        self.led_manager.start_pulsing_button1()
        self.led_manager.set_button2_color(0, 0, 0)
        logger.info("System reset to idle state.")

    def run(self):
        logger.info("Photobooth controller starting...")
        self.reset_to_idle()

        # Start Prometheus metrics server
        start_http_server(8000)  # Exposes metrics at http://localhost:8000/metrics
        logger.info("Prometheus metrics server started on port 8000.")
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("Shutting down photobooth controller...")
            self.printer_service.stop_watching()
            self.led_manager.stop_pulsing_button1()
            self.led_manager.stop_pulsing_button2()
            self.led_manager.set_button1_color(0, 0, 0)
            self.led_manager.set_button2_color(0, 0, 0)

if __name__ == "__main__":
    controller = PhotoboothController()
    controller.run()