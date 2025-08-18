import os
import cups
import shutil
import tempfile
import logging
from PIL import Image
from datetime import datetime
import time
from prometheus_client import Gauge

PRINTS_REMAINING = Gauge('prints_remaining', 'Number of prints remaining in the printer')
PRINTS_REMAINING_PERCENT = Gauge('prints_remaining_percent', 'Percent of prints remaining in the printer')


logger = logging.getLogger('PrinterService')
logger.setLevel(logging.INFO)

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


    def print_collage(self, collage_path):
        try:
            # Process and prepare the image
            temp_file = self.process_image_for_printing(collage_path)

            # Step 1: Submit job and verify it's in the queue
            job_id = self.conn.printFile(self.printer_name, temp_file, "print_collage.jpg", {})
            logger.info(f"Print job submitted with ID: {job_id}")

            timeout = 10
            start_time = time.time()
            while time.time() - start_time < timeout:
                jobs = self.conn.getJobs()
                if job_id in jobs:
                    logger.info(f"Job {job_id} found in queue")
                    break
                time.sleep(0.5)
            else:
                logger.error("Job not found in queue")
                self.conn.cancelJob(job_id)
                return False

            # Step 2: Verify printer is printing
            timeout = 20
            start_time = time.time()
            while time.time() - start_time < timeout:
                printer_info = self.conn.getPrinterAttributes(self.printer_name)
                printer_state = printer_info.get('printer-state', 0)
                job_info = self.conn.getJobAttributes(job_id)
                job_state = job_info.get('job-state', 0)

                if printer_state == 4 and job_state == cups.IPP_JOB_PROCESSING:
                    logger.info("Printer is printing")
                    break
                elif job_state in [cups.IPP_JOB_HELD, cups.IPP_JOB_STOPPED, cups.IPP_JOB_CANCELED, cups.IPP_JOB_ABORTED]:
                    logger.error(f"Printer is not printing, job error state: {job_state}. Cancelling job")
                    self.conn.cancelJob(job_id)
                    return False
                time.sleep(1)
            else:
                logger.error("Printer failed to start processing")
                self.conn.cancelJob(job_id)
                return False

            # Step 3: Monitor completion
            timeout = 40
            start_time = time.time()
            while time.time() - start_time < timeout:
                printer_info = self.conn.getPrinterAttributes(self.printer_name)
                printer_state = printer_info.get('printer-state', 0)
                job_info = self.conn.getJobAttributes(job_id)
                job_state = job_info.get('job-state', 0)

                if job_state == cups.IPP_JOB_COMPLETED and printer_state == 3:
                    logger.info("Print job completed successfully")

                    # Update print counts after successful print
                    self.update_remaining_print_count()

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

                    # Clean up temp file
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        logger.info("Temporary files cleaned up")

                    return True
                elif job_state in [cups.IPP_JOB_HELD, cups.IPP_JOB_STOPPED, cups.IPP_JOB_CANCELED, cups.IPP_JOB_ABORTED]:
                    logger.error(f"Job entered error state: {job_state}")
                    self.conn.cancelJob(job_id)
                    return False
                time.sleep(1)

            logger.error("Print job timed out")
            self.conn.cancelJob(job_id)
            return False

        except Exception as e:
            logger.error(f"Error printing collage: {e}")
            if 'job_id' in locals():
                try:
                    self.conn.cancelJob(job_id)
                except:
                    pass
            return False

    def process_image_for_printing(self, source_path):
        temp_file = os.path.join(self.temp_directory, "print_collage.jpg")
        shutil.copy2(source_path, temp_file)

        image = Image.open(temp_file)
        x, y = image.size

        if x < y:
            rotated_image = image.rotate(-90, expand=True)
        else:
            rotated_image = image

        new_width, new_height = 1842, 1240
        rotated_image.thumbnail((new_width, new_height), Image.LANCZOS)
        canvas = Image.new("RGB", (new_width, new_height), "white")
        offset = ((new_width - rotated_image.width) // 2,
                 (new_height - rotated_image.height) // 2)
        canvas.paste(rotated_image, offset)
        canvas.save(temp_file)

        return temp_file

    def update_remaining_print_count(self):
        try:
            printer_info = self.conn.getPrinterAttributes(self.printer_name)
            marker_message = printer_info.get('marker-message', '')
            marker_levels = printer_info.get('marker-levels', [0])

            # Extract remaining prints count
            if marker_message:
                count = marker_message.split(' ')[0]
                prints_remaining = int(count) if count.isdigit() else 0
                PRINTS_REMAINING.set(prints_remaining)

            # Extract percentage
            if marker_levels and len(marker_levels) > 0:
                PRINTS_REMAINING_PERCENT.set(marker_levels[0])

            logger.info(f"Updated print metrics: {prints_remaining} prints remaining, {marker_levels[0]}% remaining")
        except Exception as e:
            logger.error(f"Error updating print counts: {e}")

    def is_printer_ready(self):
        """Check if printer is ready for printing (state 3 = idle)."""
        try:
            printer_info = self.conn.getPrinterAttributes(self.printer_name)
            printer_state = printer_info.get('printer-state', 0)
            
            if printer_state == 3:
                return True
            else:
                logger.error(f"Printer not ready. Cannot start transaction Current state: {printer_state}")
                return False
        except Exception as e:
            logger.error(f"Error checking printer readiness: {e}")
            return False

    def cleanup(self):
        try:
            if os.path.exists(self.temp_directory):
                shutil.rmtree(self.temp_directory)
                logger.info("Printer service temporary files cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")