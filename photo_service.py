import subprocess
import os
import time
import logging
import signal
from PIL import Image, ImageOps, ImageDraw

logger = logging.getLogger('PhotoService')
logger.setLevel(logging.INFO)

class PhotoService:
    def __init__(self, photos_dir='photos', max_photos=4):
        self.photos_dir = photos_dir
        self.max_photos = max_photos
        self.current_photo_count = 0
        os.makedirs(self.photos_dir, exist_ok=True)

    def take_photo(self):
        try:
            subprocess.run([
                'gphoto2', '--capture-image-and-download',
                '--filename', os.path.join(self.photos_dir, f"photo_{self.current_photo_count + 1:04d}.jpg")
            ], check=True)
            self.current_photo_count += 1
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

    def kill_gphoto2_process(self):
        try:
            p = subprocess.Popen(['ps', '-A'], stdout=subprocess.PIPE)
            out, _ = p.communicate()
            processes_killed = False
            for line in out.splitlines():
                if b'gvfsd-gphoto2' in line:
                    pid = int(line.split(None, 1)[0])
                    os.kill(pid, signal.SIGKILL)
                    logger.info(f"Killed gphoto2 process with PID: {pid}")
                    processes_killed = True
            return processes_killed
        except Exception as e:
            logger.exception(f"Error while killing gphoto2 processes: {e}")
            return False

    def create_final_photo(self, quality=100, optimize=False):
        """
        Creates a 1200x1800 collage with adjustable line and border widths.

        Parameters:
            quality (int): JPEG quality (1-100). Default is 100.
            optimize (bool): Whether to optimize the image, effectively reducing file size. Default is False.

        Returns:
            str: Path to the saved collage image, or None if an error occurs.
        """
        try:
            logger.info("Creating final photo collage...")

            # Gather Photo Files
            photo_files = sorted([
                os.path.join(self.photos_dir, f)
                for f in os.listdir(self.photos_dir)
                if f.lower().endswith(('.jpg', '.jpeg', '.png'))
            ])

            expected_photos = 4
            if len(photo_files) != expected_photos:
                logger.error(f"Expected 4 photos, but found {len(photo_files)}")
                return None

            # Open Images
            images = [Image.open(photo) for photo in photo_files]

            # Define Collage Parameters with offsets
            collage_width = 1200
            collage_height = 1800
            horizontal_offset = 4  # Example offset, can be negative
            vertical_offset = 8    # Example offset, can be negative

            # Adjustable border and line widths
            base_border_width = 8
            border_width_left = max(0, base_border_width + horizontal_offset)
            border_width_right = max(0, base_border_width - horizontal_offset)
            border_width_top = max(0, base_border_width - vertical_offset) - 1
            border_width_bottom = max(0, base_border_width + vertical_offset) - 8
            middle_line_thickness = 6
            row_line_thickness = 2

            image_width = (collage_width - middle_line_thickness - border_width_left - border_width_right) // 2
            image_height = (collage_height - row_line_thickness * 3 - border_width_top - border_width_bottom) // 4
            border_color = (255, 255, 255)

            # Create Collage Canvas
            collage = Image.new('RGB', (collage_width, collage_height), border_color)

            # Arrange Photos
            for i in range(4):
                for j in range(2):
                    img = images[i]

                    # Resize maintaining height and center crop width
                    img_aspect_ratio = img.width / img.height
                    new_height = image_height
                    new_width = int(new_height * img_aspect_ratio)

                    img_resized = img.resize((new_width, new_height), Image.LANCZOS)

                    left = (new_width - image_width) // 2
                    img_cropped = img_resized.crop((left, 0, left + image_width, new_height))

                    # Calculate position to center the image
                    x = j * image_width + j * middle_line_thickness + border_width_left
                    y = i * (image_height + row_line_thickness) + border_width_top

                    # Paste image on collage
                    collage.paste(img_cropped, (x, y))

            # Draw lines for separation
            draw = ImageDraw.Draw(collage)

            # Vertical middle line
            if middle_line_thickness > 0:
                center_x = (border_width_left + image_width + middle_line_thickness // 2)
                draw.line([(center_x, border_width_top), (center_x, collage_height - border_width_bottom)], fill=border_color, width=middle_line_thickness)

            # Horizontal row lines
            if row_line_thickness > 0:
                for i in range(1, 4):
                    y = i * (image_height + row_line_thickness) + border_width_top - row_line_thickness // 2
                    draw.line([(border_width_left, y), (collage_width - border_width_right, y)], fill=border_color, width=row_line_thickness)

            # Draw borders around the collage
            draw.rectangle([(border_width_left, border_width_top),
                            (collage_width - border_width_right, collage_height - border_width_bottom)],
                           outline=border_color, width=1)

            # Save the Collage
            collage_path = os.path.join(self.photos_dir, "final_collage.jpg")
            collage.save(collage_path, quality=quality, optimize=optimize)

            # Log Information
            collage_size_mb = os.path.getsize(collage_path) / (1024 * 1024)

            return collage_path

        except Exception as e:
            logger.exception(f"Error creating final photo collage: {e}")
            return None