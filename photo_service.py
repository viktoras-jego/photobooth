import subprocess
import os
import time
import logging
import signal
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PhotoService:
    def __init__(self, photos_dir='photos', max_photos=4):
        self.photos_dir = photos_dir
        self.max_photos = max_photos
        self.current_photo_count = 0
        os.makedirs(self.photos_dir, exist_ok=True)

    def take_photo(self):
        try:
            self.kill_gphoto2_process()
            time.sleep(0.5)
            logger.info("Taking photo...")
            subprocess.run([
                'gphoto2', '--capture-image-and-download',
                '--filename', os.path.join(self.photos_dir, f"photo_{self.current_photo_count + 1:04d}.jpg")
            ], check=True)
            self.current_photo_count += 1
            logger.info(f"Photo {self.current_photo_count} taken and downloaded.")
            return self.get_latest_photo_path()
        except subprocess.CalledProcessError as e:
            logger.error(f"Error taking photo: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error during photo capture: {e}")
            return None

    def get_latest_photo_path(self):
        try:
            files = [os.path.join(self.photos_dir, f) for f in os.listdir(self.photos_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            return max(files, key=os.path.getctime)
        except ValueError:
            logger.warning("No photos found in the directory.")
            return None

    def reset_photo_count(self):
        self.current_photo_count = 0
        logger.info("Photo count reset to zero.")

    def kill_gphoto2_process(self):
        try:
            logger.info("Checking for existing gphoto2 processes...")
            p = subprocess.Popen(['ps', '-A'], stdout=subprocess.PIPE)
            out, _ = p.communicate()
            processes_killed = False
            for line in out.splitlines():
                if b'gvfsd-gphoto2' in line:
                    pid = int(line.split(None, 1)[0])
                    os.kill(pid, signal.SIGKILL)
                    logger.info(f"Killed gphoto2 process with PID: {pid}")
                    processes_killed = True
            logger.info("Successfully killed interfering gphoto2 processes" if processes_killed else "No interfering gphoto2 processes found")
            return processes_killed
        except Exception as e:
            logger.exception(f"Error while killing gphoto2 processes: {e}")
            return False

    def create_final_photo(self, quality=85, optimize=True):
        try:
            logger.info("Creating final photo collage...")
            photo_files = sorted([os.path.join(self.photos_dir, f) for f in os.listdir(self.photos_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
            if len(photo_files) != 4:
                logger.error(f"Expected 4 photos, but found {len(photo_files)}")
                return None
            images = [Image.open(photo) for photo in photo_files]
            max_width, max_height = max(img.width for img in images), max(img.height for img in images)
            padding = 140
            collage = Image.new('RGB', ((max_width * 2) + (padding * 3), (max_height * 4) + (padding * 5)), (255, 255, 255))
            for row, img in enumerate(images):
                x_pos, y_pos = padding, padding + (row * (max_height + padding))
                collage.paste(img, (x_pos, y_pos))
                collage.paste(img, (x_pos + max_width + padding, y_pos))
            collage_path = os.path.join(self.photos_dir, "final_collage.jpg")
            collage.save(collage_path, quality=quality, optimize=optimize)
            logger.info(f"Collage created and compressed successfully at {collage_path}")
            logger.info(f"Compression settings: quality={quality}, optimize={optimize}")
            logger.info(f"Collage file size: {os.path.getsize(collage_path) / (1024 * 1024):.2f} MB")
            return collage_path
        except Exception as e:
            logger.exception(f"Error creating final photo collage: {e}")
            return None