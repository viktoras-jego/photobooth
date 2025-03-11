import os
import cups
import shutil
import tempfile
import logging
from PIL import Image
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PrinterService:
    def __init__(self):
        self.printer_name = "Dai_Nippon_Printing_DS-RX1"
        self.conn = cups.Connection()
        self.temp_directory = tempfile.mkdtemp()
        self.archive_directory = "archive"

        # Create archive directory if it doesn't exist
        if not os.path.exists(self.archive_directory):
            os.makedirs(self.archive_directory)
            logger.info(f"Created archive directory: {self.archive_directory}")

        logger.info(f"Printer service initialized with printer: {self.printer_name}")

    def print_collage(self, collage_path):
        try:
            # Copy the file to temp directory
            temp_file = os.path.join(self.temp_directory, "print_collage.jpg")
            shutil.copy2(collage_path, temp_file)

            # Process image for printing
            image = Image.open(temp_file)
            x, y = image.size

            # Rotate if needed
            if x < y:
                rotated_image = image.rotate(-90, expand=True)
                logger.info("Image rotated for printing")
            else:
                rotated_image = image
                logger.info("Image not rotated for printing")

            # Resize and center
            new_width, new_height = 1844, 1240
            rotated_image.thumbnail((new_width, new_height), Image.LANCZOS)
            canvas = Image.new("RGB", (new_width, new_height), "white")
            offset = ((new_width - rotated_image.width) // 2,
                     (new_height - rotated_image.height) // 2)
            canvas.paste(rotated_image, offset)
            canvas.save(temp_file)

            # Print
            job_id = self.conn.printFile(self.printer_name, temp_file,
                                       "Photobooth Print", {})
            logger.info(f"Collage sent to printer (Job ID: {job_id})")

            # Archive the collage
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_filename = f"collage_{timestamp}.jpg"
            archive_path = os.path.join(self.archive_directory, archive_filename)
            shutil.copy2(collage_path, archive_path)
            logger.info(f"Collage archived to: {archive_path}")

            # Clean up photos directory
            photos_dir = os.path.dirname(collage_path)
            for file in os.listdir(photos_dir):
                file_path = os.path.join(photos_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    logger.info(f"Deleted: {file_path}")

            # Clean up temp file
            os.remove(temp_file)
            logger.info("Temporary files cleaned up")
            return True

        except Exception as e:
            logger.error(f"Error printing collage: {e}")
            return False

    def cleanup(self):
        try:
            if os.path.exists(self.temp_directory):
                shutil.rmtree(self.temp_directory)
                logger.info("Printer service temporary files cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")